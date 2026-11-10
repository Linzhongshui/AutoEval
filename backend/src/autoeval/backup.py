"""Local file backups with integrity-checked restores into empty scratch targets."""

import argparse
import asyncio
import hashlib
import json
import re
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url

from autoeval.audit import AuditEvent
from autoeval.config import Settings, get_settings
from autoeval.datasets import storage
from autoeval.db import create_database


class DumpRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: Literal["database.sql"]
    size: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ObjectRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=1024)
    path: str = Field(pattern=r"^objects/[0-9a-f]{64}\.bin$")
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BackupManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["autoeval-backup.v1"]
    created_at: str
    alembic_version: str = Field(min_length=1, max_length=128)
    database_dump: DumpRef
    objects: list[ObjectRef]


def canonical_json(body) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def digest_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def database_identity(settings: Settings) -> tuple[str, str]:
    url = make_url(settings.database_url.get_secret_value())
    if not re.fullmatch(r"[A-Za-z0-9_]+", url.username or "") or not re.fullmatch(
        r"[A-Za-z0-9_]+", url.database or ""
    ):
        raise ValueError("Unsupported PostgreSQL identity")
    return url.username, url.database


def run_postgres(settings: Settings, container: str, command: str, dump: Path, restore: bool):
    user, database = database_identity(settings)
    arguments = [settings.docker_executable]
    if restore:
        arguments.append("exec")
        arguments.append("-i")
    else:
        arguments.append("exec")
    arguments.extend([container, command, "-U", user])
    if restore:
        arguments.extend(["-v", "ON_ERROR_STOP=1", "-d", database])
        with dump.open("rb") as stream:
            subprocess.run(
                [*arguments], stdin=stream, capture_output=True, timeout=300, check=True
            )
    else:
        arguments.extend(["--no-password", "-d", database])
        with dump.open("xb") as stream:
            subprocess.run(
                [*arguments], stdout=stream, stderr=subprocess.PIPE, timeout=300, check=True
            )


def audit_event(action: str, manifest_sha256: str, details: dict) -> AuditEvent:
    return AuditEvent(
        actor="local-operator",
        action=action,
        resource_type="backup",
        resource_id=manifest_sha256,
        run_id=None,
        outcome="succeeded",
        request_id=f"{action}:{uuid.uuid4()}",
        details=details,
    )


async def create_backup(settings: Settings, destination: Path, postgres_container: str):
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "objects").mkdir()
    engine, sessions = create_database(settings)
    client = storage(settings)
    try:
        async with sessions() as session:
            version = await session.scalar(text("SELECT version_num FROM alembic_version"))
        if not version:
            raise ValueError("Alembic version is missing")
        dump_path = destination / "database.sql"
        await asyncio.to_thread(
            run_postgres, settings, postgres_container, "pg_dump", dump_path, False
        )
        dump_size, dump_sha256 = digest_file(dump_path)
        objects = []
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=settings.s3_bucket):
            for item in page.get("Contents", []):
                key = item["Key"]
                relative = f"objects/{hashlib.sha256(key.encode()).hexdigest()}.bin"
                response = client.get_object(Bucket=settings.s3_bucket, Key=key)
                body = response["Body"]
                digest = hashlib.sha256()
                size = 0
                try:
                    with (destination / relative).open("xb") as stream:
                        while chunk := body.read(1024 * 1024):
                            size += len(chunk)
                            digest.update(chunk)
                            stream.write(chunk)
                finally:
                    response["Body"].close()
                objects.append(
                    {"key": key, "path": relative, "size": size, "sha256": digest.hexdigest()}
                )
        manifest = BackupManifest(
            schema_version="autoeval-backup.v1",
            created_at=datetime.now(UTC).isoformat(),
            alembic_version=version,
            database_dump={
                "path": "database.sql",
                "size": dump_size,
                "sha256": dump_sha256,
            },
            objects=objects,
        )
        raw = canonical_json(manifest.model_dump())
        (destination / "manifest.json").write_bytes(raw)
        manifest_sha256 = hashlib.sha256(raw).hexdigest()
        details = {
            "manifest_sha256": manifest_sha256,
            "object_count": len(objects),
            "alembic_version": version,
        }
        async with sessions() as session, session.begin():
            session.add(audit_event("backup.create", manifest_sha256, details))
        return details
    finally:
        client.close()
        await engine.dispose()


def validate_backup(manifest_path: Path) -> BackupManifest:
    manifest = BackupManifest.model_validate_json(manifest_path.read_bytes())
    root = manifest_path.parent
    size, sha256 = digest_file(root / manifest.database_dump.path)
    if size != manifest.database_dump.size or sha256 != manifest.database_dump.sha256:
        raise ValueError("Backup database integrity mismatch")
    keys = set()
    for item in manifest.objects:
        expected = f"objects/{hashlib.sha256(item.key.encode()).hexdigest()}.bin"
        if item.path != expected or item.key in keys:
            raise ValueError("Backup object manifest integrity mismatch")
        keys.add(item.key)
        size, sha256 = digest_file(root / item.path)
        if size != item.size or sha256 != item.sha256:
            raise ValueError("Backup object integrity mismatch")
    return manifest


async def restore_backup(settings: Settings, manifest_path: Path, postgres_container: str):
    _user, database = database_identity(settings)
    if not re.fullmatch(r"autoeval_scratch_[a-z0-9_]+", database):
        raise ValueError("Restore requires an isolated autoeval_scratch_* database")
    if not re.fullmatch(r"autoeval-scratch-[a-z0-9-]+", settings.s3_bucket):
        raise ValueError("Restore requires an isolated autoeval-scratch-* bucket")
    engine, sessions = create_database(settings)
    client = storage(settings)
    try:
        async with sessions() as session:
            table_count = await session.scalar(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            )
        if table_count:
            raise ValueError("Restore database must be empty")
        if client.list_objects_v2(Bucket=settings.s3_bucket, MaxKeys=1).get("KeyCount", 0):
            raise ValueError("Restore bucket must be empty")
        manifest = validate_backup(manifest_path)
        await asyncio.to_thread(
            run_postgres,
            settings,
            postgres_container,
            "psql",
            manifest_path.parent / "database.sql",
            True,
        )
        async with sessions() as session:
            restored_version = await session.scalar(text("SELECT version_num FROM alembic_version"))
        if restored_version != manifest.alembic_version:
            raise ValueError("Restored Alembic version does not match manifest")
        for item in manifest.objects:
            with (manifest_path.parent / item.path).open("rb") as stream:
                client.put_object(
                    Bucket=settings.s3_bucket,
                    Key=item.key,
                    Body=stream,
                    ContentLength=item.size,
                )
        manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        details = {
            "manifest_sha256": manifest_sha256,
            "object_count": len(manifest.objects),
            "alembic_version": restored_version,
        }
        async with sessions() as session, session.begin():
            session.add(audit_event("backup.restore", manifest_sha256, details))
        return details
    finally:
        client.close()
        await engine.dispose()


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["create", "restore"])
    parser.add_argument("--postgres-container", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--target-database-url")
    parser.add_argument("--target-bucket")
    args = parser.parse_args()
    settings = get_settings()
    if args.action == "create":
        if not args.output:
            parser.error("create requires --output")
        result = await create_backup(settings, args.output, args.postgres_container)
    else:
        if not args.manifest or not args.target_database_url or not args.target_bucket:
            parser.error("restore requires --manifest, --target-database-url and --target-bucket")
        target = settings.model_copy(
            update={
                "database_url": SecretStr(args.target_database_url),
                "s3_bucket": args.target_bucket,
            }
        )
        result = await restore_backup(target, args.manifest, args.postgres_container)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
