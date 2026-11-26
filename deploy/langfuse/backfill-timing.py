"""Recover measured timing from retained Harbor evidence. Run with explicit --apply."""

import asyncio
import hashlib
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def index_events(root, output):
    output.mkdir(parents=True, exist_ok=True)
    for path in root.rglob("agent/events.jsonl"):
        trajectory = path.with_name("trajectory.json")
        if not trajectory.is_file() or path.stat().st_size > 64 * 1024**2:
            continue
        events = []
        try:
            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    row = json.loads(line)
                    kind = row["kind"]
                    item = {"kind": kind, "time": row["time"]}
                    if kind == "model_response":
                        item["message"] = digest(row["response"]["message"].get("content") or "")
                    elif kind == "tool_started":
                        item["id"] = row["call"]["id"]
                    elif kind == "tool_result":
                        item["id"] = row["message"]["tool_call_id"]
                    events.append(item)
            key = digest(trajectory.read_text(encoding="utf-8"))
            target = output / (key + ".json")
            body = json.dumps(events)
            if target.exists() and target.read_text() != body:
                target.with_suffix(".ambiguous").touch()
            else:
                target.write_text(body)
        except (OSError, ValueError, TypeError, KeyError):
            continue
    print("indexed", len(list(output.glob("*.json"))), flush=True)


def apply_events(rec, plan, events):
    pending, results, models, batches = {}, {}, [], {}
    request = None
    for event in events:
        kind, time = event["kind"], event["time"]
        if kind == "model_request":
            if request is not None or pending:
                return 0, 0
            request = time
        elif kind == "model_response":
            if request is None or request > time:
                return 0, 0
            models.append((request, time, event["message"]))
            request = None
        elif kind in {"tool_started", "tool_result"}:
            entries = pending if kind == "tool_started" else results
            identifier = event["id"]
            if identifier in entries:
                return 0, 0
            entries[identifier] = time
        elif kind == "world_checkpoint":
            if pending.keys() != results.keys() or pending.keys() & batches.keys():
                return 0, 0
            if pending:
                interval = min(pending.values()), max(results.values()), len(pending)
                batches.update(dict.fromkeys(pending, interval))
            pending.clear()
            results.clear()
    if request is not None or pending or results:
        return 0, 0

    generators = [span for span in plan if span.role == "generation"]
    steps = [step for step in rec.steps if step.source == "agent"]
    tools = [span for span in plan if span.role == "tool"]
    if len(generators) != len(models) or len(steps) != len(models):
        return 0, 0
    if any(digest(step.message or "") != item[2] for step, item in zip(steps, models, strict=True)):
        return 0, 0
    root = plan[0]
    lo, hi = (datetime.fromisoformat(t).timestamp() for t in (root.start_ts, root.end_ts))
    if any(not lo <= start <= end <= hi for start, end, _ in models):
        return 0, 0

    for span, (start, end, _) in zip(generators, models, strict=True):
        span.start_ts, span.end_ts = (
            datetime.fromtimestamp(t, UTC).isoformat() for t in (start, end)
        )
        span.attributes["atif.timing_source"] = "measured_model_event_window"
    matched = 0
    for span in tools:
        interval = batches.get(span.attributes.get("atif.tool_call_id"))
        if interval is None:
            continue
        start, end, count = interval
        parent = plan[span.parent] if span.parent is not None else root
        lower = datetime.fromisoformat(parent.end_ts).timestamp() if parent is not root else lo
        if not lower <= start <= end <= hi:
            continue
        span.start_ts, span.end_ts = (
            datetime.fromtimestamp(t, UTC).isoformat() for t in (start, end)
        )
        span.attributes.update(
            {"atif.timing_source": "tool_batch_window", "atif.tool_batch_size": count}
        )
        matched += 1
    return len(models), matched


async def backfill(index, apply, repair=False):
    from sqlalchemy import select

    import autoeval.langfuse_integration as lf
    from autoeval.entrypoints.api import create_app
    from autoeval.audit import AuditEvent
    from autoeval.config import get_settings
    from autoeval.db import create_database

    create_app()
    settings = get_settings()
    engine, sessions = create_database(settings)
    original = lf.build_plan
    evidence = {}

    def build(artifact, directory, identity, mode):
        rec, plan = original(artifact, directory, identity, mode)
        entry = evidence.get(identity)
        if entry is not None:
            events, stats = entry
            stats["trial"] = plan[0].attributes.get("atif.timing_source") == "harbor_trial_result"
            if stats["trial"] and events:
                stats["model_intervals"], stats["tool_batch_members"] = apply_events(
                    rec, plan, events
                )
        return rec, plan

    lf.build_plan = build
    async with sessions() as db:
        rows = (
            await db.scalars(select(lf.TraceImport.id).where(lf.TraceImport.status == "succeeded"))
        ).all()
    semaphore = asyncio.Semaphore(8)

    async def process(identifier):
        import tempfile

        async with semaphore, sessions() as db, db.begin():
            row = await db.get(lf.TraceImport, identifier, with_for_update=True)
            old = row.trace_id
            existing = await db.scalar(
                select(AuditEvent.details)
                .where(
                    AuditEvent.resource_id == str(row.id),
                    AuditEvent.action == "trace_timing_backfill",
                )
                .order_by(AuditEvent.created_at.desc())
                .limit(1)
            )
            if (existing and (not repair or existing.get("model_intervals"))) or (
                repair and not existing
            ):
                return {"status": "already_backfilled", "old": old}
            artifact = await asyncio.to_thread(lf.read_manifest, settings, row)
            key = digest(artifact["files"]["agent/trajectory.json"])
            path = index / (key + ".json")
            events = (
                json.loads(path.read_text())
                if path.exists() and not path.with_suffix(".ambiguous").exists()
                else []
            )
            identity = uuid.uuid5(
                row.attempt_id, "historical-timing-v3" if repair else "historical-timing-v2"
            )
            stats = {
                "old": old,
                "attempt": str(row.attempt_id),
                "run": str(row.run_id),
                "model_intervals": 0,
                "tool_batch_members": 0,
            }
            evidence[str(identity)] = events, stats
            try:
                with tempfile.TemporaryDirectory() as directory:
                    build(artifact, Path(directory), str(identity), row.content_mode)
                if not stats["trial"]:
                    return {**stats, "status": "no_trial_interval"}
                if repair and not stats["model_intervals"]:
                    return {**stats, "status": "event_match_unavailable"}
                if not apply:
                    return {**stats, "status": "eligible"}
                target = await lf.import_one(
                    SimpleNamespace(attempt_id=identity, content_mode=row.content_mode),
                    settings,
                    artifact,
                )
                row.trace_id = target
                stats.update(new=target, model_requests=0)
                db.add(
                    AuditEvent(
                        actor="local-operator",
                        action="trace_timing_backfill",
                        resource_type="langfuse_trace_import",
                        resource_id=str(row.id),
                        run_id=row.run_id,
                        outcome="succeeded",
                        request_id=str(uuid.uuid4()),
                        details=stats,
                    )
                )
                return {**stats, "status": "updated"}
            finally:
                evidence.pop(str(identity), None)

    async def report(identifier):
        try:
            result = await process(identifier)
        except Exception as exc:  # noqa: BLE001 -- isolate each historical import
            result = {
                "status": "error",
                "import_id": str(identifier),
                "error_type": type(exc).__name__,
            }
        print(json.dumps(result), flush=True)

    try:
        await asyncio.gather(*(report(identifier) for identifier in rows))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    if sys.argv[1] == "index":
        index_events(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        asyncio.run(
            backfill(Path(sys.argv[2]), "--apply" in sys.argv[3:], "--repair" in sys.argv[3:])
        )
