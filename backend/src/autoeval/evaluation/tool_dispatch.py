"""Tool capabilities used for admission and resource scheduling."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolDispatch:
    name: str
    concurrency_field: str
    uses_trials: bool = False


TOOLS = {
    "llm_accuracy": ToolDispatch("aisbench", "batch_size"),
    "harbor_agent": ToolDispatch("harbor", "n_concurrent_trials", uses_trials=True),
    "peir": ToolDispatch("peir", "concurrency"),
    "llm_perf": ToolDispatch("llm_perf", "concurrency"),
    "agentx": ToolDispatch("agentx", "concurrency"),
}


def tool_for(task):
    config = task["compilation"]["config"]
    subcommand = config.get("subcommand")
    if subcommand is None:
        # Older frozen allocations carried only params and dataset identity.
        subcommand = (
            "harbor_agent" if task["dataset"] in {"DeepSWE", "AutomationBench"} else "llm_accuracy"
        )
    return TOOLS[subcommand]
