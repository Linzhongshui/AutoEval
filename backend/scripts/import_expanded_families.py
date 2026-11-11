"""Import conservatively extracted own-model scores; preserve unpublished conditions."""

import hashlib
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".screenshots/official-cards"
OUT = ROOT / "docs/official-data/2026-11-11/mainstream"
OUT.mkdir(parents=True, exist_ok=True)
API = "http://127.0.0.1:8000/api/autoeval/v1"
# Explicit own-model columns, zero based including category/benchmark cells.
SPECS = {
    "ZhipuAI/GLM-4.7": [("GLM-4.7", 1, "publisher default")],
    "moonshotai/Kimi-K2-Thinking": [("K2 Thinking", 2, "thinking")],
    "MiniMax/MiniMax-M2": [("MiniMax-M2", 1, "publisher default")],
    "MiniMax/MiniMax-M2.1": [("MiniMax-M2.1", 1, "publisher default")],
    "deepseek-ai/DeepSeek-R1": [("DeepSeek R1", 7, "reasoning")],
    "deepseek-ai/DeepSeek-R1-0528": [("DeepSeek R1 0528", 3, "reasoning")],
    "deepseek-ai/DeepSeek-V3.1": [
        ("DeepSeek V3.1-NonThinking", 2, "non-thinking"),
        ("DeepSeek V3.1-Thinking", 4, "thinking"),
    ],
    "Qwen/Qwen3-235B-A22B-Instruct-2507": [("Qwen3-235B-A22B-Instruct-2507", 6, "non-thinking")],
    "Qwen/Qwen3-30B-A3B-Instruct-2507": [("Qwen3-30B-A3B-Instruct-2507", 6, "non-thinking")],
    "Qwen/Qwen2.5-VL-32B-Instruct": [("Qwen2.5-VL-32B", 3, "publisher default")],
    "moonshotai/Kimi-K2-Instruct-0905": [("K2-Instruct-0905", 2, "publisher default")],
}
PATTERN = re.compile(
    r"(MMLU|GPQA|AIME|MATH|HumanEval|Human Eval|MBPP|LiveCodeBench|SWE.?Bench|Terminal.?Bench|MMMU|MMStar|IFEval|IF-Eval|BBH|DROP|SimpleQA|FRAMES|Arena.Hard|AlpacaEval|LongBench|C-Eval|C.?Eval|C.?SimpleQA|CLUEWSC|CMMLU|HMMT)",
    re.IGNORECASE,
)


def clean(s):
    return re.sub("<[^>]+>", "", s).replace("**", "").strip()


def request(path, body=None):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    return json.load(urllib.request.urlopen(req, timeout=30))["data"]


entries = []
evidence = []
coverage = []
for model, specs in SPECS.items():
    if model not in {
        "ZhipuAI/GLM-4.7",
        "moonshotai/Kimi-K2-Thinking",
        "MiniMax/MiniMax-M2",
        "MiniMax/MiniMax-M2.1",
    }:
        continue
    raw = (CACHE / (model.replace("/", "--") + ".md")).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    for header, index, mode in specs:
        active = False
        seen = set()
        for line in raw.decode().splitlines():
            if not line.strip().startswith("|"):
                active = False
                continue
            cells = [clean(v) for v in line.strip().strip("|").split("|")]
            if len(cells) > index and header in cells[index]:
                active = True
                continue
            if not active or len(cells) <= index:
                continue
            candidates = (
                cells[1:2]
                if cells[0] in {"Math", "English", "Code", "Chinese", "General", "Coding"}
                else cells[:2]
            )
            label = next((v for v in candidates if PATTERN.search(v)), None)
            if not label or label in seen:
                continue
            match = re.fullmatch(r"(\d+(?:\.\d+)?)(?:\s*±\s*(\d+(?:\.\d+)?))?", cells[index])
            if not match:
                continue
            seen.add(label)
            value = float(match[1])
            metric = "publisher_reported_score"
            conditions = {
                "mode": mode,
                "published_benchmark_label": label,
                "tool_revision": "unknown",
                "sample_manifest": "unknown",
                "scale": "as published; no conversion",
                "model_release_date": "未披露",
                "evaluated_at": "未披露",
                "parameter_count": {
                    "moonshotai/Kimi-K2-Thinking": "总参数 1T / 激活 32B",
                    "MiniMax/MiniMax-M2": "总参数 230B / 激活 10B",
                }.get(model, "未披露"),
            }
            if match[2]:
                conditions["reported_uncertainty"] = float(match[2])
            key = hashlib.sha256((model + label + mode + sha).encode()).hexdigest()[:32]
            entry = {
                "source_key": "official-ms-" + key,
                "source_type": "official",
                "model_name": model,
                "dataset": label,
                "metric": metric,
                "value": value,
                "unit": "points",
                "direction": "higher_is_better",
                "scope": "full",
                "conditions": conditions,
                "source_name": "Official publisher ModelScope card",
                "source_url": f"https://modelscope.cn/models/{model}/summary",
                "source_version": "sha256:" + sha,
                "source_sha256": sha,
                "notes": "Publisher reference only; not reproduced. Dataset label retains metric/split/version. Score scale unchanged, not assumed percent. full denotes published benchmark, completeness not independently verified. Not a gate baseline.",
            }
            entries.append(entry)
            evidence.append(
                {
                    "source_key": entry["source_key"],
                    "url": entry["source_url"],
                    "sha256": sha,
                    "column_header": header,
                    "column_index": index,
                    "source_row": line,
                }
            )
        coverage.append({"modelscope_id": model, "mode": mode, "importable_scores": len(seen)})
(OUT / "expanded-entries.json").write_text(
    json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
)
(OUT / "expanded-evidence.json").write_text(
    json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
)
(OUT / "expanded-coverage.json").write_text(
    json.dumps(coverage, ensure_ascii=False, indent=2), encoding="utf-8"
)
for e in entries:
    row = request("/data-workbench/entries", e)
    if row["state"] == "draft":
        row = request(
            "/data-workbench/entries/" + row["id"] + "/review",
            {
                "action": "approve",
                "expected_revision": row["revision"],
                "reason": "User authorized mainstream official data collection and display; extracted own-model numeric column; preserve mode, source row, hash and unknown comparison conditions.",
            },
        )
    assert row["state"] == "approved"
keys = {
    v["entry"]["source_key"] for g in request("/data-workbench/published") for v in g["entries"]
}
assert all(e["source_key"] in keys for e in entries)
print(json.dumps({"published": len(entries), "coverage": coverage}, ensure_ascii=True))
