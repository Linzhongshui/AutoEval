"""Fetch Qwen ModelScope cards and publish explicitly authorized official scores."""

import hashlib
import json
import re
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000/api/autoeval/v1"
ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "docs" / "official-data" / "2026-11-11"
OUTPUT.mkdir(parents=True, exist_ok=True)


def request(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)["data"]


entries = []
for size in ["3B", "7B", "72B"]:
    model = f"Qwen/Qwen2.5-VL-{size}-Instruct"
    url = f"https://modelscope.cn/api/v1/models/{model}/repo?Revision=master&FilePath=README.md"
    raw = urllib.request.urlopen(url, timeout=30).read()
    sha = hashlib.sha256(raw).hexdigest()
    text = raw.decode()
    for dataset in ["MMMU", "MMMU-Pro"]:
        marker = f"| {dataset}<sub>val</sub>"
        lines = [line for line in text.splitlines() if line.startswith(marker)]
        if not lines:
            continue
        assert len(lines) == 1
        line = lines[0]
        value = float(re.sub(r"[*\s]", "", line.strip().strip("|").split("|")[-1]))
        entry = {
            "source_key": f"modelscope-qwen25vl-{size.lower()}-{dataset.lower()}-{sha[:12]}",
            "source_type": "official",
            "model_name": model,
            "dataset": dataset,
            "metric": "accuracy",
            "value": value,
            "unit": "%",
            "direction": "higher_is_better",
            "scope": "full",
            "conditions": {
                "split": "validation",
                "evaluation_protocol": "publisher model card",
                "tool_revision": "unknown",
                "prompt_template": "unknown",
                "modelscope_model_id": model,
            },
            "source_name": "Qwen official ModelScope model card",
            "source_url": f"https://modelscope.cn/models/{model}/summary",
            "source_version": "sha256:" + sha,
            "source_sha256": sha,
            "notes": "Official published reference, not reproduced by AutoEval; full denotes the published validation split, not AutoEval full execution. Tool and prompt were not disclosed in the extracted table. Not a release gate baseline.",
        }
        entries.append(entry)
        (OUTPUT / f"{size}-{dataset}-source.json").write_text(
            json.dumps(
                {
                    "url": url,
                    "sha256": sha,
                    "modelscope_model_id": model,
                    "table_row": line,
                    "retrieved_date": "2026-11-11",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
(OUTPUT / "entries.json").write_text(
    json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
)
for entry in entries:
    row = request("/data-workbench/entries", entry)
    if row["state"] == "draft":
        row = request(
            "/data-workbench/entries/" + row["id"] + "/review",
            {
                "action": "approve",
                "expected_revision": row["revision"],
                "reason": "User explicitly authorized publishing official data; verified own-model column from Qwen official ModelScope card. External reference only, not AutoEval reproduction or gate baseline.",
            },
        )
    assert row["state"] == "approved"
    print(entry["model_name"], entry["dataset"], entry["value"], row["state"])
published = request("/data-workbench/published")
keys = {v["entry"]["source_key"] for group in published for v in group["entries"]}
assert all(e["source_key"] in keys for e in entries)
print("Published and verified:", len(entries))
