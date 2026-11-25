"""Export portable startup recipes from selected ready compilations and import new operator inputs."""

import argparse
import asyncio
import json
import re
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import asyncpg
from autoeval.catalog.standard_compilation import (
    digest,
    discover,
    safe_json,
    validate_config,
)
from autoeval.infrastructure.config import get_settings
from evaluation_seed import SeedError, require

REPOSITORY = "local-operator/deployment-startup"
FORMAT = "autoeval.startup-inputs.v1"
ADAPTOR = "955089ab32ef696c231d628f5ad0d9da28f430c4"
# Field names are allowlisted through every nesting level. Controlled connection and allocation
# values are reconstructed by the destination compiler. Unknown options require operator review.
GENERATION = {
    "temperature": None,
    "top_p": None,
    "max_tokens": None,
    "reasoning_effort": None,
}
AGENT = {
    "cost_limit": None,
    "step_limit": None,
    "reasoning_effort": None,
    "sampling_args": {
        "max_tokens": None,
        "extra_body": {
            "thinking": {"type": None},
            "max_tokens": None,
            "reasoning_effort": None,
        },
    },
}
PORTABLE = {
    **dict.fromkeys(
        (
            "model_type",
            "datasets",
            "max_out_len",
            "batch_size",
            "num_prompts",
            "max_num_workers",
            "dump_eval_details",
            "agent_name",
            "dataset_abbr",
            "agent_import_path",
            "python_executable",
            "environment_type",
            "n_attempts",
            "max_retries",
            "n_concurrent_trials",
        )
    ),
    "generation_kwargs": GENERATION,
    "llm_kwargs": GENERATION,
    "agent_kwargs": AGENT,
    "environment_kwargs": {"host_network": None},
    "model_info": dict.fromkeys(
        (
            "max_input_tokens",
            "max_output_tokens",
            "input_cost_per_token",
            "output_cost_per_token",
        )
    ),
}
BOUND = {
    "url",
    "abbr",
    "model",
    "api_base",
    "model_names",
    "work_dir",
    "ais_bench_root",
    "path",
    "datasets_dir",
    "container_name",
    "execution",
}


def safe_values(values, schema, path=""):
    result = {}
    for key, value in values.items():
        field = path + key
        if (not path and key in BOUND) or field == "agent_kwargs.base_url":
            continue
        require(key in schema, f"Review unsupported portable option: {field}")
        if isinstance(schema[key], dict):
            require(isinstance(value, dict), "Expected structured tool options")
            result[key] = safe_values(value, schema[key], field + ".")
        elif key == "datasets":
            require(
                isinstance(value, list)
                and len(value) == 1
                and re.fullmatch(r"[A-Za-z0-9_.-]+", value[0]),
                "Expected one named dataset",
            )
            result[key] = value
        else:
            require(
                isinstance(value, (int, float))
                or (
                    isinstance(value, str)
                    and re.fullmatch(r"[A-Za-z0-9_./:-]{1,256}", value)
                    and "://" not in value
                    and ".." not in value
                    and "@" not in value
                ),
                f"Review nonportable value: {field}",
            )
            result[key] = value
    return result


def config(raw, *, locks=False):
    validate_config(raw)
    result = {**raw, "params": safe_values(raw["params"], PORTABLE)}
    if locks:
        controlled = set(raw["params"]) & BOUND
        require(
            controlled <= {"path"},
            "Source locks target-specific fields; review manually",
        )
        if "path" in controlled:
            path = raw["params"]["path"]
            require(
                isinstance(path, str)
                and re.fullmatch(r"/[A-Za-z0-9_./-]+", path)
                and ".." not in path,
                "Review locked container dataset path",
            )
            result["params"]["path"] = path
    return result


def normalized(recipe):
    require(
        set(recipe) == {"source", "standard", "startup", "target_agent_base_url"},
        "Unexpected recipe fields",
    )
    source = recipe["source"]
    require(
        set(source)
        == {
            "source_model",
            "benchmark",
            "repository",
            "revision",
            "content_sha256",
            "compilation_sha256",
            "adaptor_revision",
        },
        "Unsupported source identity",
    )
    require(
        all(
            re.fullmatch(r"[A-Za-z0-9_.-]+", source[k])
            for k in ("source_model", "benchmark")
        )
        and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", source["repository"])
        and re.fullmatch("[a-f0-9]{40}", source["revision"])
        and all(
            re.fullmatch("[a-f0-9]{64}", source[k])
            for k in ("compilation_sha256", "content_sha256")
        )
        and source["adaptor_revision"] == ADAPTOR,
        "Invalid source identity or adaptor",
    )
    require(
        isinstance(recipe["target_agent_base_url"], bool),
        "Invalid target binding option",
    )
    for label in ("standard", "startup"):
        require(
            recipe[label] == config(recipe[label], locks=label == "standard"),
            "Startup recipe contains source environment fields",
        )
    model, dataset = source["source_model"], source["benchmark"]
    files = {
        f"{model}/{dataset}/{name}": json.dumps(
            recipe[label], ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
        )
        for name, label in (
            ("standard_config.json", "standard"),
            ("benchmark_config.json", "startup"),
        )
    }
    entry = discover(SimpleNamespace(files=files))[0]
    entry["origin"] = "operator_deployment_startup"
    entry["deployment_source"] = source
    entry["requires_target_agent_base_url"] = recipe["target_agent_base_url"]
    content = digest(entry)
    # This is an operator-generated immutable revision, never labeled as an upstream Git commit.
    revision = content[:40]
    row_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"urn:autoeval:{REPOSITORY}:{content}"))
    return {
        "id": row_id,
        "repository": REPOSITORY,
        "revision": revision,
        "source_model": model,
        "benchmark": dataset,
        "content_sha256": content,
        "payload": entry,
    }


async def load_recipe(db, compilation_id):
    row = await db.fetchrow(
        "SELECT s.source_model,s.benchmark,s.repository,s.revision,s.content_sha256, "
        "s.payload->'files'->'standard_config.json'->>'raw' AS standard, "
        "c.sha256 AS compilation_sha256,c.payload->>'adaptor_revision' AS adaptor_revision, "
        "c.payload->>'input_ready' AS ready, c.payload->'config' AS config "
        "FROM public.standard_input_compilation c JOIN public.standard_input_version s "
        "ON s.id=c.input_id WHERE c.id=$1",
        compilation_id,
    )
    require(
        row and row["ready"] == "true",
        f"Missing or blocked compilation: {compilation_id}",
    )
    standard = safe_json(row["standard"])
    startup = safe_json(row["config"])
    source = {
        k: row[k]
        for k in (
            "source_model",
            "benchmark",
            "repository",
            "revision",
            "content_sha256",
            "compilation_sha256",
            "adaptor_revision",
        )
    }
    return {
        "source": source,
        "standard": config(standard, locks=True),
        "startup": config(startup),
        "target_agent_base_url": "base_url"
        in startup["params"].get("agent_kwargs", {}),
    }


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    for command in ("export", "import"):
        sub = subs.add_parser(command)
        sub.add_argument("--file", type=Path, required=True)
        if command == "export":
            sub.add_argument(
                "--compilation-id", type=uuid.UUID, action="append", required=True
            )
    args = parser.parse_args()
    dsn = (
        get_settings()
        .database_url.get_secret_value()
        .replace("postgresql+asyncpg://", "postgresql://", 1)
    )
    db = await asyncpg.connect(dsn)
    try:
        if args.command == "export":
            async with db.transaction(readonly=True, isolation="repeatable_read"):
                recipes = [
                    await load_recipe(db, i) for i in dict.fromkeys(args.compilation_id)
                ]
            rows = [normalized(r) for r in recipes]
            payload = {"format": FORMAT, "recipes": recipes}
            data = (
                json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
                + "\n"
            )
            with args.file.open("x", encoding="utf-8") as out:
                out.write(data)
        else:
            require(args.file.stat().st_size <= 2_000_000, "Recipe file exceeds 2 MB")
            payload = safe_json(args.file.read_text(encoding="utf-8"))
            require(
                set(payload) == {"format", "recipes"}
                and payload["format"] == FORMAT
                and isinstance(payload["recipes"], list)
                and payload["recipes"],
                "Unsupported recipe file",
            )
            rows = [normalized(r) for r in payload["recipes"]]
            columns = (
                "id,repository,revision,source_model,benchmark,content_sha256,payload"
            )
            async with db.transaction():
                await db.execute("SELECT pg_advisory_xact_lock(27109, 32017)")
                for row in rows:
                    raw = json.dumps(row)
                    record = "jsonb_populate_record(NULL::public.standard_input_version,$1::jsonb)"
                    await db.execute(
                        f"INSERT INTO public.standard_input_version ({columns}) "
                        f"SELECT {columns} FROM {record} ON CONFLICT DO NOTHING",
                        raw,
                    )
                    require(
                        await db.fetchval(
                            f"SELECT EXISTS(SELECT 1 FROM public.standard_input_version t, {record} v "
                            "WHERE to_jsonb(t)-'created_at' @> (to_jsonb(v)-'created_at') "
                            "AND t.id=v.id)",
                            raw,
                        ),
                        f"Existing input ID or natural key conflicts: {row['id']}",
                    )
        for row in rows:
            print(f"{row['benchmark']}\t{row['id']}\t{row['content_sha256']}")
    finally:
        await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except SeedError as exc:
        sys.exit(str(exc))
    except Exception as exc:  # noqa: BLE001 - SQL, URL and validation errors can include secrets
        sys.exit(
            f"Startup inputs failed ({type(exc).__name__}); check release and recipe"
        )
