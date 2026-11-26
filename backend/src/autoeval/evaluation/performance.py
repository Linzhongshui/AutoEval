"""Resolve a performance workload against the selected SSH node and model binding."""

from pathlib import PurePosixPath

from fastapi import HTTPException

from autoeval.catalog.standard_inputs import digest
from autoeval.planning.planning_transport import execution_template, executor_templates
from autoeval_runtime.performance_adapter import REVISION, adapter_digest


def performance_inputs(settings, body, target):
    workload = body.performance.model_dump(exclude_none=True)
    agentx = workload["kind"] == "agentx"
    command = "agentx" if agentx else "llm_perf"
    dataset = "AgentX" if agentx else "Synthetic"
    node = str(body.resource_id)
    entry = executor_templates(settings, node).get(command, {})
    binding = entry.get("targets", {}).get(str(body.target_id), {})
    context = binding.get("context_tokens")
    required = 262144 if agentx else workload["input_tokens"] + workload["max_output_tokens"]
    if not entry or not binding:
        raise HTTPException(422, "SSH 节点尚未登记此模型的性能镜像和 tokenizer 挂载")
    if type(context) is not int or context < required:
        raise HTTPException(422, "模型登记的上下文窗口不足")
    path = binding.get("tokenizer_path", "")
    if not PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
        raise HTTPException(422, "需要有效的容器内 tokenizer 绝对路径")
    params = {
        **workload,
        "model": target["model"],
        "url": target["base_url"],
        "ais_bench_root": "/benchmark",
        "tokenizer_path": path,
        "context_tokens": context,
    }
    if agentx:
        params["corpus_path"] = "/data/weka/" + workload["variant"]
    tool = {
        "family": command,
        "revision": REVISION,
        "scorer_reference": "ais_bench/benchmark/summarizers/"
        + ("agentx.py" if agentx else "default_perf.py"),
        "scorer_sha256": "0dc12ac0a03baa6d7fa4c46d42bf16d99c8892b5776cbb53dd566cb47674de38"
        if agentx
        else "a00183b0a4d1b2ac07ab5e49567ef0a83e39e1f9f4b05816dad666c60d835a5b",
    }
    compiled = {
        "config": {"subcommand": command, "params": params},
        "adaptor_revision": adapter_digest(),
    }
    task = {
        "task_id": command,
        "dataset": dataset,
        "tool": tool,
        "compilation": compiled,
        "compilation_sha256": digest(compiled),
        "concurrency": max(workload["concurrency"])
        if isinstance(workload["concurrency"], list)
        else workload["concurrency"],
        "assigned_resource_id": node,
        "assigned_resource_kind": "customer_ssh",
        "attempts": 1,
        "samples": [],
    }
    template = execution_template(settings, node, task)
    if not template:
        raise HTTPException(422, "SSH 性能模板的版本或镜像不匹配")
    task["execution_template"] = template
    return {
        **body.model_dump(mode="json"),
        "target": target,
        "dataset_concurrency": 1,
        "tasks": [task],
    }
