"""Deterministic allocation within an explicitly selected resource pool."""
from fastapi import HTTPException
from sqlalchemy import select, text

from autoeval.evaluation.models import CapacityLease


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


def execution_compilation(compilation):
    """Keep platform allocation metadata out of the strict remote runtime contract."""
    import copy

    value = copy.deepcopy(compilation)
    for field in ("resource_ids", "manifest_ids"):
        value.get("runtime_config", {}).pop(field, None)
    return value


def demand_for(item):
    count = item["concurrency"]
    params = item["compilation"]["config"]["params"]
    if item["dataset"] in {"DeepSWE", "AutomationBench"}:
        return {
            "cpu": 0.5 + count * max(2, float(params.get("override_cpus") or 2)),
            "mem": 256 + count * max(8192, int(params.get("override_memory_mb") or 8192)),
            "disk": count * max(20, float(params.get("override_storage_mb") or 20480) / 1024),
            "networks": count,
        }
    return {"cpu": 1 + count * 0.02, "mem": 1024 + count * 16, "disk": 0, "networks": 0}


def fits(demand, used, resource):
    limits = {
        "cpu": resource["cpu_cores"] * 0.8,
        "mem": resource["mem_mb"] * 0.8,
        "disk": resource["disk_gb"] * 0.8,
        "networks": resource.get("network_available") or 0,
    }
    return all(
        (k == "networks" and demand[k] == 0)
        or demand[k] + used.get(k, 0) <= limits[k]
        for k in limits
    )


async def acquire(session, owner, resource, demand):
    node = resource["node_id"]
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": "capacity:" + node}
    )
    existing = await session.scalar(select(CapacityLease).where(CapacityLease.owner_id == owner))
    if existing:
        return not existing.released
    leases = (
        await session.scalars(
            select(CapacityLease).where(
                CapacityLease.node_id == node,
                CapacityLease.released.is_(False),
            )
        )
    ).all()
    used = {k: sum(row.demand.get(k, 0) for row in leases) for k in demand}
    if not fits(demand, used, resource):
        return False
    session.add(CapacityLease(owner_id=owner, node_id=node, demand=demand))
    return True


async def release(session, owner):
    lease = await session.scalar(select(CapacityLease).where(CapacityLease.owner_id == owner))
    if lease:
        lease.released = True
