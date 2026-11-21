import asyncio
import copy

from fastapi import HTTPException
from sqlalchemy import select

from autoeval.catalog.datasets import DatasetManifest, read_manifest
from autoeval.catalog.standard_inputs import StandardInputCompilation, StandardInputVersion
from autoeval.planning.planning_engine import PLANNER_REVISION, apply_concurrency, selected_samples
from autoeval.resources.models import TargetBinding


async def target_data(session, target_id):
    target = await session.get(TargetBinding, target_id)
    if target is None:
        raise HTTPException(404, "Target not found")
    return {"base_url": target.base_url, "model": target.remote_model}


def manifest_dataset_matches(dataset, asset_key):
    aliases = {"GPQA": {"GPQA", "GPQA_Diamond", "gpqa-diamond"}}
    return asset_key in aliases.get(dataset, {dataset})


async def resolve_inputs(session, settings, body):
    from autoeval.catalog.models import EvaluationProfile
    from autoeval.catalog.registry import Asset, AssetVersion

    target = await target_data(session, body.target_id)
    tasks = []
    for spec in body.tasks:
        if spec.compilation_id in getattr(settings, "archived_compilation_ids", []):
            raise HTTPException(409, "该执行配置已归档，请选择新版配置")
        if spec.manifest_id in settings.archived_manifest_ids:
            raise HTTPException(409, "该样本清单已归档，请重新选择可用清单")
        compilation = await session.get(StandardInputCompilation, spec.compilation_id)
        manifest = await session.get(DatasetManifest, spec.manifest_id)
        if not compilation or not manifest:
            raise HTTPException(404, "Compilation or manifest not found")
        version = await session.get(AssetVersion, manifest.dataset_version_id)
        asset_row = await session.get(Asset, version.asset_id)
        if not manifest_dataset_matches(spec.dataset, asset_row.asset_key):
            raise HTTPException(422, "Manifest dataset identity mismatch")
        profile = await session.scalar(
            select(EvaluationProfile)
            .where(
                EvaluationProfile.dataset_name == spec.dataset,
                (EvaluationProfile.full_manifest_id == manifest.id)
                | (EvaluationProfile.lite_manifest_id == manifest.id),
            )
            .order_by(EvaluationProfile.created_at.desc())
            .limit(1)
        )
        if not profile:
            raise HTTPException(422, "Versioned tool/scorer profile required for selected manifest")
        compiled = copy.deepcopy(compilation.payload)
        resource_ids = compiled.get("runtime_config", {}).get("resource_ids")
        from autoeval.evaluation.resource_allocation import allocate_resource

        candidates = body.resource_ids or [body.resource_id]
        if resource_ids is not None:
            allocate_resource(candidates, resource_ids)
        if (
            not compiled.get("input_ready")
            or compiled.get("adaptor_revision") != "955089ab32ef696c231d628f5ad0d9da28f430c4"
        ):
            raise HTTPException(422, "Compilation is blocked or uses an unsupported adaptor")
        if (compiled.get("credential_binding") or {}).get("target_id") != str(body.target_id):
            raise HTTPException(422, "Compilation belongs to another target")
        source_input = await session.get(StandardInputVersion, compilation.input_id)
        if source_input.benchmark != ("GPQA_Diamond" if spec.dataset == "GPQA" else spec.dataset):
            raise HTTPException(422, "Compilation dataset identity mismatch")
        if spec.concurrency is not None:
            try:
                compiled = apply_concurrency(compiled, spec.concurrency)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        config = compiled["config"]
        params = config["params"]
        if config["subcommand"] == "llm_accuracy":
            if params.get("dump_eval_details") is False:
                raise HTTPException(
                    422, "Per-case scoring details are required for report evidence"
                )
            params["dump_eval_details"] = True
        if config["subcommand"] == "llm_accuracy" and len(params.get("datasets", [])) != 1:
            raise HTTPException(422, "Each compilation must select exactly one dataset")
        if (spec.dataset in {"DeepSWE", "AutomationBench"}) != (
            config["subcommand"] == "harbor_agent"
        ):
            raise HTTPException(422, "Dataset tool family mismatch")
        from autoeval.planning.planning_transport import select_execution_template

        assignment = select_execution_template(
            settings, candidates, resource_ids, {"compilation": compiled, "tool": profile.contract}
        )
        if assignment is None:
            raise HTTPException(
                422,
                f"所选 SSH 节点缺少 {spec.dataset} 的执行模板"
                f"（{profile.contract['family']} / {profile.contract['revision'][:12]}）。"
                "请配置节点的工具版本、镜像和数据挂载。模板匹配后，平台会自动创建独立容器。",
            )
        assigned_resource, template = assignment
        full = await session.get(DatasetManifest, profile.full_manifest_id)
        source = await asyncio.to_thread(read_manifest, settings, full)
        samples = [
            dict(
                sample,
                tool_case_id=str(i)
                if spec.dataset not in {"DeepSWE", "AutomationBench"}
                else sample["sample_id"],
            )
            for i, sample in enumerate(source["samples"])
        ]
        if manifest.scope == "lite":
            lite = await asyncio.to_thread(read_manifest, settings, manifest)
            wanted = {s["sample_id"]: s["sha256"] for s in lite["samples"]}
            if any(
                wanted.get(s["sample_id"]) != s["sha256"]
                for s in samples
                if s["sample_id"] in wanted
            ):
                raise HTTPException(422, "Lite manifest differs from full manifest")
            # Accuracy Lite selections must map to a contiguous tool range.
            positions = [i for i, s in enumerate(samples) if s["sample_id"] in wanted]
            if len(positions) != len(wanted):
                raise HTTPException(422, "Lite samples missing from full manifest")
            if config["subcommand"] == "llm_accuracy":
                if positions != list(range(positions[0], positions[-1] + 1)):
                    raise HTTPException(
                        422,
                        "Non-contiguous accuracy Lite selection is not supported by this adaptor",
                    )
                params["dataset_test_range"] = f"[{positions[0]}:{positions[-1] + 1}]"
            else:
                params["task_names"] = list(wanted)
        chosen = selected_samples(config, samples)
        if config["subcommand"] == "llm_accuracy":
            # AISBench dataset slicing is authoritative; num_prompts is not consistently
            # honored across supported versions. Freeze the exact effective tool range.
            params["dataset_test_range"] = (
                f"[{chosen[0]['tool_case_id']}:{int(chosen[-1]['tool_case_id']) + 1}]"
            )
        from autoeval.evaluation.tool_dispatch import tool_for

        field = tool_for({"compilation": compiled}).concurrency_field
        attempts = (
            int(params.get("n_attempts", 1))
            if spec.dataset in {"DeepSWE", "AutomationBench"}
            else 1
        )
        concurrency = int(params.get(field, 1))
        if not 1 <= concurrency <= 256 or not 1 <= attempts <= 100:
            raise HTTPException(422, "Invalid concurrency or attempts")
        tasks.append(
            {
                **spec.model_dump(mode="json"),
                "assigned_resource_id": assigned_resource,
                "assigned_resource_kind": body.resource_kind,
                "execution_template": template,
                "compilation": compiled,
                "compilation_sha256": compilation.sha256,
                "standard_baseline_source": {
                    "source_model": source_input.source_model,
                    "revision": source_input.revision,
                    "repository": source_input.repository,
                    "benchmark": source_input.benchmark,
                    "file": copy.deepcopy(source_input.payload.get("files", {}).get("baseline.json")),
                },
                "manifest_sha256": manifest.sha256,
                "profile_sha256": profile.sha256,
                "tool": profile.contract,
                "samples": chosen,
                "dataset_samples": full.sample_count,
                "subset_scope": manifest.scope,
                "attempts": attempts,
                "concurrency": concurrency,
            }
        )
    return {
        **body.model_dump(mode="json"),
        "target": target,
        "tasks": tasks,
        "planner_revision": PLANNER_REVISION,
    }


def selection_identity(inputs):
    return sorted(
        (
            {
                **{
                    key: task[key]
                    for key in ("task_id", "dataset", "compilation_id", "manifest_id")
                },
                "profile_sha256": task.get("profile_sha256"),
                "concurrency": task.get("concurrency"),
                "assigned_resource_id": task.get("assigned_resource_id"),
                "assigned_resource_kind": task.get("assigned_resource_kind"),
                "execution_template": task.get("execution_template"),
            }
            for task in inputs.get("tasks", [])
        ),
        key=lambda task: task["task_id"],
    )
