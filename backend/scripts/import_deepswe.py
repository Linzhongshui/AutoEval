"""Publish the previously captured official DeepSWE snapshot, preserving model aliases."""

import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
path = ROOT / "docs/official-data/2026-11-11/deepswe/official-results.json"
rows = json.loads(path.read_text(encoding="utf-8"))
assert len(rows) == 21
API = "http://127.0.0.1:8000/api/autoeval/v1"


def request(endpoint, body=None):
    req = urllib.request.Request(
        API + endpoint,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    return json.load(urllib.request.urlopen(req, timeout=30))["data"]


entries = []
for row in rows:
    identity = (
        row["source_model_name"]
        + "|"
        + row["effort"]
        + "|"
        + row["dataset_version"]
        + "|"
        + row["source_sha256"]
    )
    entry = {
        "source_key": "deepswe-" + hashlib.sha256(identity.encode()).hexdigest()[:32],
        "source_type": "official",
        "model_name": row["source_model_name"],
        "dataset": "DeepSWE",
        "metric": "pass@1",
        "value": float(row["pass_at_1_percent"]),
        "unit": "%",
        "direction": "higher_is_better",
        "scope": "full",
        "conditions": {
            "dataset_version": row["dataset_version"],
            "tasks": row["tasks"],
            "harness": row["harness"],
            "effort": row["effort"],
            "mode": row["effort"],
            "reported_uncertainty_percent": row["uncertainty_percent"],
            "modelscope_model_id": "unknown",
            "model_identity_status": "official alias; ModelScope mapping unverified",
            "model_release_date": "未披露",
            "evaluated_at": "未披露",
            "parameter_count": "未披露",
        },
        "source_name": "Datacurve DeepSWE official leaderboard",
        "source_url": row["source_url"],
        "source_version": row["dataset_version"] + " / snapshot " + row["retrieved_date"],
        "source_sha256": row["source_sha256"],
        "notes": "User explicitly authorized publishing these 21 official aliases without confirmed ModelScope mapping. Captured visible rounded scores and uncertainty, not reconstructed precise scores. Not an AutoEval reproduction or release baseline.",
    }
    record = request("/data-workbench/entries", entry)
    if record["state"] == "draft":
        record = request(
            "/data-workbench/entries/" + record["id"] + "/review",
            {
                "action": "approve",
                "expected_revision": record["revision"],
                "reason": "User explicitly requested publishing captured 21 official DeepSWE rows; retain original aliases and mark ModelScope mapping unverified, preserve v1.1/effort/uncertainty/source checksum.",
            },
        )
    assert record["state"] == "approved"
    entries.append(entry)
keys = {
    r["entry"]["source_key"] for g in request("/data-workbench/published") for r in g["entries"]
}
assert all(e["source_key"] in keys for e in entries)
(path.parent / "entries.json").write_text(
    json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("Published and read-back verified:", len(entries))
