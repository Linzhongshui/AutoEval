"""Deterministic allocation within an explicitly selected resource pool."""
from fastapi import HTTPException


def allocate_resource(candidates, supported):
    candidates = list(dict.fromkeys(map(str, candidates)))
    if len(candidates) > 1 and not supported:
        raise HTTPException(422, "多资源自动分配需要配置登记支持的执行资源")
    matching = [r for r in candidates if supported is None or r in supported]
    if not matching:
        raise HTTPException(422, "该执行配置不适用于所选资源，请选择配置绑定的执行资源")
    return matching[0]


def resource_for_task(snapshot, task_id):
    return snapshot.get("task_resources", {}).get(task_id, snapshot)
