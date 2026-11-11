"""Apply verified metadata with complete curation history, without altering scores."""

import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
metadata = json.loads(
    (ROOT / "docs/official-data/2026-11-11/deepswe/model-metadata.json").read_text(encoding="utf-8")
)["metadata"]
API = "http://127.0.0.1:8000/api/autoeval/v1"


def request(path, body=None):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    return json.load(urllib.request.urlopen(req, timeout=30))["data"]


updated = []
for group in request("/data-workbench/published"):
    for record in group["entries"]:
        entry = record["entry"]
        values = metadata.get(entry["model_name"])
        if entry["dataset"] != "DeepSWE" or not values:
            continue
        if all(entry["conditions"].get(k) == v for k, v in values.items()):
            continue
        reason = "Verified primary-source model metadata enrichment; preserve original score and score evidence; never infer evaluation dates."
        path = "/data-workbench/entries/" + record["id"]
        withdrawn = request(
            path + "/review",
            {"action": "withdraw", "expected_revision": record["revision"], "reason": reason},
        )
        entry["conditions"].update(values)
        draft = request(
            path + "/edit",
            {"entry": entry, "expected_revision": withdrawn["revision"], "reason": reason},
        )
        request(
            path + "/review",
            {"action": "approve", "expected_revision": draft["revision"], "reason": reason},
        )
        updated.append(entry["model_name"])
print("Updated:", updated)
