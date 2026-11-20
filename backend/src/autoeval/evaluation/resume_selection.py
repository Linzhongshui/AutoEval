"""Exact tool selections derived from a frozen evaluation task."""

from copy import deepcopy


def remaining_payloads(task: dict, sample_ids: set[str]) -> list[dict]:
    """Return ordered, disjoint payloads for the confirmed samples."""
    samples = task["samples"]
    frozen_ids = {sample["sample_id"] for sample in samples}
    if len(frozen_ids) != len(samples) or not sample_ids <= frozen_ids:
        raise ValueError("Invalid frozen sample selection")
    selected = [sample for sample in samples if sample["sample_id"] in sample_ids]
    if not selected:
        return []

    command = task["compilation"]["config"]["subcommand"]
    if command == "llm_accuracy":
        groups = []
        for sample in selected:
            index = int(sample["tool_case_id"])
            if index < 0 or (groups and index <= int(groups[-1][-1]["tool_case_id"])):
                raise ValueError("Invalid frozen accuracy case order")
            if not groups or index != int(groups[-1][-1]["tool_case_id"]) + 1:
                groups.append([])
            groups[-1].append(sample)
    elif command == "harbor_agent":
        groups = [selected]
    else:
        raise ValueError("Unsupported evaluation command")

    result = []
    for group in groups:
        payload = deepcopy({**task, "samples": group})
        params = payload["compilation"]["config"]["params"]
        if command == "llm_accuracy":
            start = int(group[0]["tool_case_id"])
            params["dataset_test_range"] = f"[{start}:{start + len(group)}]"
            params.pop("num_prompts", None)
        else:
            names = [sample["tool_case_id"] for sample in group]
            if len(set(names)) != len(names):
                raise ValueError("Duplicate frozen Harbor task name")
            params["task_names"] = names
            params.pop("exclude_task_names", None)
            params.pop("n_tasks", None)
        result.append(payload)
    return result
