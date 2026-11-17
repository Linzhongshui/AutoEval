"""Register operator-supplied acceptance configuration; never calls a model.
The official standard repository has no AutomationBench configuration. Provenance
is explicitly local-operator, with the official dataset revision recorded separately.
"""

import asyncio
import json
import sys
import uuid

from sqlalchemy import select

from autoeval.config import get_settings
from autoeval.db import create_database
from autoeval.registry import AssetVersion
from autoeval.ssh_resources import SSHResourceBinding
from autoeval.standard_inputs import (
    CompileInput,
    StandardInputCompilation,
    StandardInputVersion,
    compile_config,
    digest,
)
from autoeval.targets import TargetBinding


async def main():
    target_id = uuid.UUID(sys.argv[1])
    settings = get_settings()
    if settings.environment not in {"development", "test"}:
        raise RuntimeError("Acceptance registration requires development/test")
    engine, sessions = create_database(settings)
    try:
        async with sessions() as session, session.begin():
            target = await session.get(TargetBinding, target_id)
            version = await session.get(AssetVersion, target.model_version_id)
            source = await session.get(
                SSHResourceBinding, uuid.UUID("51278e81-b71b-4425-b89f-fd90ce287402")
            )
            resource = await session.scalar(
                select(SSHResourceBinding).where(
                    SSHResourceBinding.binding_key == "automationbench-acceptance-shared-20261117"
                )
            )
            if resource is None:
                resource = SSHResourceBinding(
                    provider_id=source.provider_id,
                    binding_key="automationbench-acceptance-shared-20261117",
                    version=1,
                    host=source.host,
                    port=source.port,
                    username=source.username,
                    fingerprint=source.fingerprint,
                    auth_kind=source.auth_kind,
                    credential_ref=source.credential_ref,
                    workdir="/home/chenluwen/autoeval-automationbench-acceptance-20261116",
                )
                session.add(resource)
                await session.flush()
            config = {
                "tool": "ais_bench",
                "subcommand": "harbor_agent",
                "params": {
                    "agent_import_path": "automationbench_adapter.agent:AutomationBenchOfficialAgent",
                    "python_executable": "/acceptance/runtime/bin/python",
                    "dataset_abbr": "automationbench-acceptance",
                    "agent_kwargs": {
                        "base_url": "https://api.deepseek.com/v1",
                        "sampling_args": {
                            "max_tokens": 65536,
                            "extra_body": {
                                # Verifiers renames max_tokens; retain DeepSeek wire field.
                                "max_tokens": 65536,
                                "thinking": {"type": "enabled"},
                                "reasoning_effort": "max",
                            },
                        },
                    },
                    "n_attempts": 1,
                    "n_concurrent_trials": 1,
                    "max_retries": 0,
                    "environment_type": "docker",
                    "environment_kwargs": {"host_network": True},
                    "max_num_workers": 1,
                },
            }
            entry = {
                "repository": "local-operator/automationbench-acceptance-deepseek-wire",
                "revision": "4a8e1061254004d9dac807054eed33fad7d1ff14",
                "source_model": "deepseek-flash",
                "benchmark": "AutomationBench",
                "startup_missing": False,
                "origin": "operator_acceptance_configuration",
                "files": {"standard_config.json": {"raw": json.dumps(config)}},
            }
            body = CompileInput(
                model_id=version.asset_id,
                target_id=target_id,
                execution="local",
                task_path="/home/chenluwen/autoeval-automationbench-acceptance-20261116/tasks-public",
                tool_root="/benchmark",
                template_version="operator-automationbench-acceptance-v1",
            )
            compiled = compile_config(entry, body, target)
            if not compiled["input_ready"]:
                raise ValueError(compiled["blocking_reasons"])
            inp = await session.scalar(
                select(StandardInputVersion).where(
                    StandardInputVersion.repository == entry["repository"],
                    StandardInputVersion.revision == entry["revision"],
                    StandardInputVersion.source_model == entry["source_model"],
                    StandardInputVersion.benchmark == entry["benchmark"],
                )
            )
            if inp is None:
                inp = StandardInputVersion(
                    repository=entry["repository"],
                    revision=entry["revision"],
                    source_model=entry["source_model"],
                    benchmark=entry["benchmark"],
                    content_sha256=digest(entry),
                    payload=entry,
                )
                session.add(inp)
                await session.flush()
            row = await session.scalar(
                select(StandardInputCompilation).where(
                    StandardInputCompilation.sha256 == compiled["sha256"]
                )
            )
            if row is None:
                row = StandardInputCompilation(
                    input_id=inp.id,
                    model_id=version.asset_id,
                    sha256=compiled["sha256"],
                    payload=compiled,
                )
                session.add(row)
                await session.flush()
            print(
                json.dumps(
                    {
                        "resource_id": str(resource.id),
                        "compilation_id": str(row.id),
                        "target_id": str(target_id),
                        "model_requests": 0,
                    }
                )
            )
    finally:
        await engine.dispose()


asyncio.run(main())
