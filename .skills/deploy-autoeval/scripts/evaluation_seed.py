"""Transfer explicitly selected AutoEval dataset profiles using the backend environment."""

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import tempfile
import uuid
import zipfile
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

import asyncpg
from autoeval.catalog.datasets import ManifestInput, canonical_manifest, storage
from autoeval.catalog.profiles import ToolContract
from autoeval.infrastructure.config import get_settings
from botocore.exceptions import ClientError

TABLES = {
    "asset": "id created_at asset_key kind name",
    "asset_version": "id created_at asset_id version metadata",
    "dataset_manifest": "id created_at dataset_version_id manifest_key scope parent_id "
    "sha256 object_key sample_count",
    "evaluation_profile": "id created_at profile_key version dataset_name full_manifest_id "
    "lite_manifest_id contract sha256",
}
NATURAL = {
    "asset": "asset_key",
    "asset_version": "asset_id version",
    "dataset_manifest": "dataset_version_id manifest_key",
    "evaluation_profile": "profile_key version",
}
FORMAT = "autoeval.evaluation-seed.v1"
LIMIT = 16 * 1024 * 1024  # Same per-manifest read limit as the API.
NATIVE_LIMIT = 256 * 1024 * 1024
TEST_KEY = r"^(fixture-|browser-|model-browser-|navigation-|pipeline-|TEST-)"


class SeedError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise SeedError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def portable_url(value):
    url = urlsplit(value)
    return (
        url.scheme == "https"
        and url.hostname
        and not (url.username or url.password or url.query or url.fragment)
    )


def object_ref(row, native=False):
    checksum = row["sha256"]
    prefix = "dataset-bundles" if native else "dataset-manifests"
    key = f"{prefix}/{checksum}.json"
    require(
        re.fullmatch("[a-f0-9]{64}", checksum) and row["object_key"] == key,
        "Unsupported or non-content-addressed dataset object",
    )
    return key


async def layout(db):
    scoped = False
    for table, columns in TABLES.items():
        fields = await db.fetch(
            "SELECT column_name,is_nullable,column_default FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=$1",
            table,
        )
        expected = set(columns.split())
        names = {field["column_name"] for field in fields}
        require(
            expected <= names,
            f"Missing required {table} columns; migrate the database first",
        )
        for field in fields:
            require(
                field["column_name"] in expected
                or field["is_nullable"] == "YES"
                or field["column_default"] is not None,
                f"Unsupported required column in {table}; use matching release",
            )
        if table == "evaluation_profile":
            scoped = "compilation_id" in names
    return scoped


async def select_row(db, table, row_id, scoped):
    columns = ", ".join(TABLES[table].split())
    if table == "evaluation_profile" and scoped:
        columns += ", (compilation_id IS NOT NULL) AS scoped"
    raw = await db.fetchval(
        f"SELECT to_jsonb(r)::text FROM (SELECT {columns} FROM public.{table} WHERE id=$1) r",
        uuid.UUID(str(row_id)),
    )
    if raw is None:
        return None
    row = json.loads(raw)
    require(
        not row.pop("scoped", False),
        "Profile is tied to a source compilation; register a target-specific profile",
    )
    return row


async def selected(db, ids, scoped):
    result = {table: {} for table in TABLES}

    async def load(table, row_id):
        key = str(row_id)
        if key not in result[table]:
            row = await select_row(db, table, row_id, scoped)
            require(row is not None, f"Missing {table} {key}")
            result[table][key] = row
        return result[table][key]

    for profile_id in ids:
        profile = await load("evaluation_profile", profile_id)
        for manifest_id in (profile["full_manifest_id"], profile["lite_manifest_id"]):
            if manifest_id:
                manifest = await load("dataset_manifest", manifest_id)
                version = await load("asset_version", manifest["dataset_version_id"])
                await load("asset", version["asset_id"])
    return {table: list(rows.values()) for table, rows in result.items()}


def get_object(client, bucket, key):
    limit = NATIVE_LIMIT if key.startswith("dataset-bundles/") else LIMIT
    try:
        response = client.get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in {"NoSuchKey", "404", "NotFound"}:
            return None
        raise
    with response["Body"] as body:
        raw = body.read(limit + 1)
    require(
        len(raw) <= limit and digest(raw) == Path(key).stem,
        f"Object integrity check failed: {key}",
    )
    return raw


def inspect_rows(rows):
    require(set(rows) == TABLES.keys(), "Unexpected tables in seed")
    index = {}
    for table, fields in TABLES.items():
        require(
            all(set(row) == set(fields.split()) for row in rows[table]),
            f"Unexpected columns in {table}",
        )
        index[table] = {str(uuid.UUID(row["id"])): row for row in rows[table]}
        require(len(index[table]) == len(rows[table]), f"Duplicate IDs in {table}")

    objects = set()
    reached = {table: set() for table in TABLES}
    profiles = rows["evaluation_profile"]
    require(profiles, "Select at least one evaluation profile")
    for p in profiles:
        reached["evaluation_profile"].add(p["id"])
        dataset = p["dataset_name"]
        require(
            dataset in {"GPQA", "MMMU-Pro", "DeepSWE", "AutomationBench"},
            "Unsupported evaluation dataset",
        )
        tool = ToolContract.model_validate(p["contract"])
        require(
            portable_url(tool.source_url),
            "Tool URL includes nonportable authority or query",
        )
        require(
            portable_url(tool.scorer_reference)
            if "://" in tool.scorer_reference
            else re.fullmatch(r"[A-Za-z0-9_./:+#-]+", tool.scorer_reference),
            "Unsupported scorer reference; use a public URL or a repository path",
        )
        require(
            (tool.family == "harbor") == (dataset in {"DeepSWE", "AutomationBench"}),
            "Dataset and tool family disagree",
        )
        body = {
            k: p[k]
            for k in (
                "profile_key",
                "version",
                "dataset_name",
                "full_manifest_id",
                "lite_manifest_id",
            )
        }
        body["tool"] = tool.model_dump(mode="json")
        require(
            digest(canonical_manifest(body)) == p["sha256"],
            f"Profile contract hash mismatch: {p['profile_key']}",
        )
        full = index["dataset_manifest"][p["full_manifest_id"]]
        for scope, manifest_id in (
            ("full", full["id"]),
            ("lite", p["lite_manifest_id"]),
        ):
            if not manifest_id:
                continue
            m = index["dataset_manifest"][manifest_id]
            reached["dataset_manifest"].add(manifest_id)
            require(
                m["scope"] == scope
                and m["parent_id"] == (full["id"] if scope == "lite" else None)
                and m["dataset_version_id"] == full["dataset_version_id"],
                "Profile references incompatible manifests",
            )
            objects.add(object_ref(m))
        v = index["asset_version"][full["dataset_version_id"]]
        a = index["asset"][v["asset_id"]]
        reached["asset_version"].add(v["id"])
        reached["asset"].add(a["id"])
        aliases = (
            {"GPQA", "GPQA_Diamond", "gpqa-diamond"} if dataset == "GPQA" else {dataset}
        )
        require(
            a["kind"] == "dataset" and a["asset_key"] in aliases,
            "Dataset identity mismatch",
        )
        meta = v["metadata"]
        if meta:
            require(
                set(meta)
                == {
                    "sha256",
                    "source",
                    "object_key",
                    "sample_count",
                    "tool_revision",
                    "schema_version",
                    "approval_status",
                }
                and meta["schema_version"] == "dataset-content.v1",
                "Unknown dataset metadata",
            )
            source = meta["source"]
            require(
                set(source)
                == {
                    "csv_sha256",
                    "source_url",
                    "archive_sha256",
                    "license_sha256",
                    "source_revision",
                }
                and portable_url(source["source_url"])
                and all(
                    re.fullmatch("[0-9a-f]{64}", source[k])
                    for k in ("csv_sha256", "archive_sha256", "license_sha256")
                )
                and re.fullmatch("[A-Za-z0-9_.-]{1,128}", source["source_revision"])
                and re.fullmatch("[a-f0-9]{40}([a-f0-9]{24})?", meta["tool_revision"])
                and re.fullmatch("[a-z_]{1,64}", meta["approval_status"]),
                "Unsupported native dataset provenance",
            )
            objects.add(object_ref(meta, True))
    require(
        all(reached[t] == index[t].keys() for t in TABLES),
        "Seed contains unrelated rows",
    )
    return index, objects


def check_payloads(index, read):
    members = {}
    for m in index["dataset_manifest"].values():
        parsed = ManifestInput.model_validate_json(read(m["object_key"]))
        v = index["asset_version"][m["dataset_version_id"]]
        a = index["asset"][v["asset_id"]]
        parent = str(parsed.parent_id) if parsed.parent_id else None
        require(
            (
                parsed.dataset_key,
                parsed.name,
                parsed.version,
                parsed.manifest_key,
                parsed.scope,
                parent,
                len(parsed.samples),
            )
            == (
                a["asset_key"],
                a["name"],
                v["version"],
                m["manifest_key"],
                m["scope"],
                m["parent_id"],
                m["sample_count"],
            ),
            f"Manifest object disagrees with database: {m['id']}",
        )
        members[m["id"]] = {
            sample.sample_id: sample.sha256 for sample in parsed.samples
        }
    for m in index["dataset_manifest"].values():
        if m["parent_id"]:
            require(
                members[m["id"]].items() <= members[m["parent_id"]].items(),
                "Lite manifest differs from full manifest",
            )
        elif meta := index["asset_version"][m["dataset_version_id"]]["metadata"]:
            native = json.loads(read(meta["object_key"]))
            refs = {row["sample_id"]: row["sha256"] for row in native["samples"]}
            require(
                native["schema_version"] == "native-dataset.v1"
                and refs == members[m["id"]]
                and len(native["samples"]) == meta["sample_count"] == len(refs)
                and native["tool_revision"] == meta["tool_revision"]
                and native["source_sha256"] == meta["source"]["csv_sha256"],
                "Native dataset bundle disagrees with registered full manifest",
            )


def read_entry(archive, key, limit):
    info = archive.getinfo(key)
    require(info.file_size <= limit, f"ZIP member exceeds size limit: {key}")
    raw = archive.read(info)
    if key != "seed.json":
        require(digest(raw) == Path(key).stem, f"Corrupt ZIP member: {key}")
    return raw


def payload_reader(archive):
    def read(key):
        limit = NATIVE_LIMIT if key.startswith("dataset-bundles/") else LIMIT
        return read_entry(archive, key, limit)

    return read


async def export(db, scoped, client, settings, args):
    async with db.transaction(isolation="repeatable_read", readonly=True):
        rows = await selected(db, args.profile_id, scoped)
        revision = await db.fetchval("SELECT version_num FROM public.alembic_version")
    index, keys = inspect_rows(rows)
    with tempfile.NamedTemporaryFile(dir=args.bundle.parent, delete=False) as tmp:
        temp_path = Path(tmp.name)
    try:
        with zipfile.ZipFile(
            temp_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            archive.writestr(
                "seed.json",
                canonical_manifest(
                    {"format": FORMAT, "source_revision": revision, "rows": rows}
                ),
            )
            for key in sorted(keys):
                raw = get_object(client, settings.s3_bucket, key)
                require(raw is not None, f"Missing source object: {key}")
                archive.writestr(key, raw)
        with zipfile.ZipFile(temp_path) as archive:
            check_payloads(index, payload_reader(archive))
        os.link(
            temp_path, args.bundle
        )  # Atomic publication; never replace an existing release.
    finally:
        temp_path.unlink(missing_ok=True)
    print(
        f"Exported {len(rows['evaluation_profile'])} profiles, {len(keys)} objects ({revision})"
    )


async def reconcile(db, table, row, scoped, apply):
    existing = await select_row(db, table, row["id"], scoped)
    if existing is not None:
        require(
            all(existing[k] == v for k, v in row.items() if k != "created_at"),
            f"Existing {table} ID has different immutable contents: {row['id']}",
        )
        return
    # Compare using PostgreSQL's column types. Never interpolate an archive-provided identifier.
    condition = " AND ".join(f"t.{k}=v.{k}" for k in NATURAL[table].split())
    if table == "dataset_manifest" and row["scope"] == "full":
        condition = f"({condition}) OR (t.dataset_version_id=v.dataset_version_id AND t.scope='full')"
    record = f"jsonb_populate_record(NULL::public.{table},$1::jsonb)"
    payload = json.dumps(row)
    conflict = await db.fetchval(
        f"SELECT EXISTS(SELECT 1 FROM public.{table} t, {record} v WHERE {condition})",
        payload,
    )
    require(
        not conflict, f"Existing {table} natural key belongs to another ID: {row['id']}"
    )
    if apply:
        columns = ", ".join(TABLES[table].split())
        await db.execute(
            f"INSERT INTO public.{table} ({columns}) SELECT {columns} FROM {record}",
            payload,
        )


async def install(db, scoped, client, settings, args):
    apply = args.command == "import"
    bucket = settings.s3_bucket
    with zipfile.ZipFile(args.bundle) as archive:
        seed = json.loads(read_entry(archive, "seed.json", LIMIT))
        require(
            set(seed) == {"format", "source_revision", "rows"}
            and seed["format"] == FORMAT,
            "Unsupported seed file format",
        )
        rows = seed["rows"]
        index, keys = inspect_rows(rows)
        require(
            sorted(archive.namelist()) == sorted(keys | {"seed.json"}),
            "Incomplete, duplicate or unexpected files in ZIP",
        )
        read = payload_reader(archive)
        check_payloads(index, read)
        async with db.transaction(readonly=not apply):
            if apply:
                await db.execute("SELECT pg_advisory_xact_lock(27109, 32016)")
            for table in TABLES:
                for row in sorted(
                    rows[table], key=lambda r: r.get("scope", "") == "lite"
                ):
                    await reconcile(db, table, row, scoped, apply)
            missing = 0
            client.head_bucket(Bucket=bucket)
            for key in sorted(keys):
                if get_object(client, bucket, key) is None:
                    missing += 1
                    if apply:
                        try:
                            client.put_object(
                                Bucket=bucket,
                                Key=key,
                                Body=read(key),
                                ContentType="application/json",
                                IfNoneMatch="*",
                            )
                        except ClientError as exc:
                            if exc.response["Error"]["Code"] not in {
                                "412",
                                "PreconditionFailed",
                            }:
                                raise
                        require(
                            get_object(client, bucket, key) is not None,
                            f"Missing after put: {key}",
                        )
        target = await db.fetchval("SELECT version_num FROM public.alembic_version")
        print(
            f"{args.command}: {len(rows['evaluation_profile'])} profiles, {len(keys)} objects, "
            f"{missing} objects initially absent; source={seed['source_revision']} target={target}"
        )


async def main():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "list", help="show selectable real dataset profiles in this database"
    )
    for command in ("export", "check", "import"):
        parser = commands.add_parser(command)
        parser.add_argument("--bundle", required=True, type=Path)
        if command == "export":
            parser.add_argument(
                "--profile-id", required=True, type=uuid.UUID, action="append"
            )
    args = cli.parse_args()
    settings = get_settings()
    dsn = settings.database_url.get_secret_value().replace(
        "postgresql+asyncpg://", "postgresql://", 1
    )
    db = await asyncpg.connect(dsn)
    try:
        scoped = await layout(db)
        if args.command == "list":
            rows = await db.fetch(
                "SELECT id, dataset_name, profile_key, version, full_manifest_id, lite_manifest_id "
                "FROM public.evaluation_profile WHERE profile_key !~ $1 "
                + ("AND compilation_id IS NULL " if scoped else "")
                + "ORDER BY dataset_name, created_at DESC",
                TEST_KEY,
            )
            for row in rows:
                print("\t".join(str(value) if value else "-" for value in row.values()))
        else:
            with closing(storage(settings)) as client:
                if args.command == "export":
                    await export(db, scoped, client, settings, args)
                else:
                    await install(db, scoped, client, settings, args)
    finally:
        await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except SeedError as exc:
        sys.exit(str(exc))
    except Exception as exc:  # noqa: BLE001 - protect deployment secrets at the CLI boundary
        # DB drivers, validation errors and URLs may contain SQL parameters or secret values.
        code = (
            exc.response["Error"]["Code"]
            if isinstance(exc, ClientError)
            else type(exc).__name__
        )
        sys.exit(
            f"Seed operation failed ({code}); verify database layout, object store and bundle"
        )
