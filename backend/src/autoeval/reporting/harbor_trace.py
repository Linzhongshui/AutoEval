"""Convert an archived Harbor trial into the existing Langfuse span plan."""

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
    return rec, build_span_plan(rec, mode=mode, run_name=identity, dataset_id=rec.task_id)
