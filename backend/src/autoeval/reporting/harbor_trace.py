"""Convert an archived Harbor trial into the existing Langfuse span plan."""

import json
from datetime import datetime
from pathlib import Path

FILES = {
    "agent/trajectory.json",
    "result.json",
    "verifier/reward.txt",
    "verifier/reward.json",
    "verifier/reward-details.json",
}


def build_plan(artifact, directory, identity, mode="structural"):
    from harborstack.convert.plan import build_span_plan
    from harborstack.convert.scan import load_trial

    if mode not in {"structural", "full"}:
        raise ValueError("Unsupported trace content mode")
    # Preserve existing structural IDs; full exports get a distinct stable identity.
    if mode == "full":
        identity += ":full"
    name = artifact.get("trial_name", "")
    if not name or Path(name).name != name or name in {".", ".."}:
        raise ValueError("Invalid trial name")
    root = directory / name
    for relative, text in artifact["files"].items():
        if relative not in FILES or not isinstance(text, str):
            raise ValueError("Invalid artifact file")
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    rec = load_trial(root, run_id_hint=identity)
    # Namespace native sessions by platform attempt; stable across retries/restores.
    rec.session_id = identity + ":" + rec.session_id
    rec.run_id = identity
    plan = build_span_plan(rec, mode=mode, run_name=identity, dataset_id=rec.task_id)
    if plan[0].attributes.get("atif.timing_missing"):
        apply_trial_timing(plan, artifact["files"].get("result.json", "{}"))
    return rec, plan


def apply_trial_timing(plan, native_result):
    """Use Harbor's measured trial interval without assigning it to individual steps."""
    try:
        result = json.loads(native_result)
        start = datetime.fromisoformat(result["started_at"])
        end = datetime.fromisoformat(result["finished_at"])
    except (KeyError, TypeError, ValueError):
        return
    if start.utcoffset() is None or end.utcoffset() is None or end < start:
        return
    root = plan[0]
    root.start_ts, root.end_ts = start.isoformat(), end.isoformat()
    root.attributes["atif.timing_source"] = "harbor_trial_result"
    for span in plan[1:]:
        # Unknown steps are shown as points inside the measured trial.
        span.start_ts = span.end_ts = root.start_ts
