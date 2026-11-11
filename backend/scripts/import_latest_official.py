"""Capture selected own-model benchmark columns; publish only with --publish.

Run from the repository root. Evidence and exact source bytes are retained beside entries.
"""

import argparse
import hashlib
import json
import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/official-data/2026-11-11/latest-models"
API = "http://127.0.0.1:8000/api/autoeval/v1"


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], [], None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        if tag in {"td", "th"}:
            self.cell = ""
        if tag in {"br", "div"} and self.cell is not None:
            self.cell += " "

    def handle_data(self, data):
        if self.cell is not None:
            self.cell += data

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.cell is not None:
            self.row.append(" ".join(self.cell.split()))
            self.cell = None
        if tag == "tr" and self.row:
            self.rows.append(self.row)


# HF publisher repository, verified ModelScope ID, exact table column, column header.
SPECS = [
    ("zai-org/GLM-5.2", "ZhipuAI/GLM-5.2", 1, "GLM-5.2"),
    ("zai-org/GLM-5.3", "ZhipuAI/GLM-5.3", 1, "GLM-5.3"),
    ("moonshotai/Kimi-K3", "moonshotai/Kimi-K3", 1, "Kimi K3 (max)"),
    ("moonshotai/Kimi-K3.1-Pro", "moonshotai/Kimi-K3.1-Pro", 1, "Kimi K3.1 Pro (max)"),
    ("MiniMaxAI/MiniMax-M3.1-Flash", "MiniMax/MiniMax-M3.1-Flash", 1, "MiniMax M3.1 Flash"),
    ("deepseek-ai/DeepSeek-V4.1-Flash", "deepseek-ai/DeepSeek-V4.1-Flash", 7, "DS-V4.1-Flash"),
    (
        "deepseek-ai/DeepSeek-V4.1-Flash-1017",
        "deepseek-ai/DeepSeek-V4.1-Flash-1017",
        1,
        "DS-V4.1-Flash-1017",
    ),
    ("Qwen/Qwen3.8-2.4T-A95B", "Qwen/Qwen3.8-2.4T-A95B", 5, "Qwen3.8-Max"),
    ("Qwen/Qwen3.8-27B", "Qwen/Qwen3.8-27B", 1, "Qwen3.8-27B"),
    ("Qwen/Qwen3.8-Flash-Next", "Qwen/Qwen3.8-Flash-Next", 1, "Qwen3.8-Flash-Next"),
]


def request(path, body=None):
    req = urllib.request.Request(
        API + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)["data"]


def table_rows(text):
    parser = Tables()
    parser.feed(text)
    rows = list(parser.rows)
    for line in text.splitlines():
        if line.strip().startswith("|"):
            rows.append(
                [re.sub(r"<[^>]*>|\*\*", "", v).strip() for v in line.strip().strip("|").split("|")]
            )
    return rows


def benchmark(label):
    if re.search(r"GPQA[ -]Diamond", label, re.IGNORECASE):
        return "GPQA-Diamond"
    if "DeepSWE" in label:
        return "DeepSWE"
    if "Terminal" in label and "Science" not in label:
        version = re.search(r"\d+\.\d+", label)
        return "Terminal-Bench " + (version[0] if version else "unknown")
    if "Automation" in label:
        return "AutomationBench-AA" if "AA" in label else "AutomationBench"
    if "MMMU-Pro" in label:
        return "MMMU-Pro"
    return None


def capture():
    OUT.mkdir(parents=True, exist_ok=True)
    metadata = json.loads((OUT.parent / "deepswe/model-metadata.json").read_text(encoding="utf-8"))[
        "metadata"
    ]
    aliases = {
        "zai-org/GLM-5.2": "glm-5.2",
        "zai-org/GLM-5.3": "glm-5.3",
        "moonshotai/Kimi-K3": "kimi-k3",
        "Qwen/Qwen3.8-2.4T-A95B": "qwen3.8-max",
    }
    entries, evidence, identities = [], [], {}
    for hf, model, index, header in SPECS:
        # Capture once; reruns use immutable bytes, not a moving main branch.
        card = OUT / (hf.replace("/", "--") + ".md")
        if not card.exists():
            card.write_bytes(
                urllib.request.urlopen(
                    f"https://huggingface.co/{hf}/raw/main/README.md", timeout=30
                ).read()
            )
        raw = card.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        ms_file = OUT / (model.replace("/", "--") + ".identity.json")
        if not ms_file.exists():
            ms_file.write_bytes(
                urllib.request.urlopen(
                    f"https://modelscope.cn/api/v1/models/{model}", timeout=30
                ).read()
            )
        identity = json.loads(ms_file.read_bytes())
        assert identity["Code"] == 200 and identity["Data"]["Name"] == model.split("/")[1]
        assert identity["Data"]["Path"] == model.split("/")[0]
        identities[model] = {"huggingface_id": hf, "modelscope_id": model}
        active, seen = False, set()
        for row in table_rows(raw.decode()):
            if len(row) > index and row[index] == header:
                active = True
                continue
            if row and row[0] in {"Benchmark", "Benchmark (Metric)", ""}:
                active = False
            if not active or len(row) <= index:
                continue
            label = row[0]
            dataset = benchmark(label)
            if not dataset or (label, row[index]) in seen:
                continue
            # Paired MMMU values explicitly mean without/with Python, never average them.
            values = row[index].split("/")
            if not all(re.fullmatch(r"\s*\d+(?:\.\d+)?\s*", v) for v in values):
                continue
            assert len(values) == 1 or dataset == "MMMU-Pro", row
            seen.add((label, row[index]))
            for pos, value in enumerate(values):
                conditions = {
                    "mode": "publisher reported; see method",
                    "published_benchmark_label": label,
                    "huggingface_model_id": hf,
                    "modelscope_model_id": model,
                    "tool_revision": "unknown",
                    "sample_manifest": "unknown",
                    "evaluated_at": "未披露",
                    "captured_on": "2026-11-11",
                    "score_scope_note": "Publisher reference; not independently reproduced",
                }
                conditions.update(metadata.get(aliases.get(hf, ""), {}))
                if hf.startswith("moonshotai/"):
                    conditions.update(mode="max", temperature=1.0, top_p=0.95)
                    if "K3.1" in hf:
                        conditions.update(
                            model_release_date="2026-10-23",
                            parameter_count="2.8T total / 104B active",
                            release_date_source_url="https://www.kimi.com/code/docs/en/kimi-code/whats-new.html",
                            release_date_kind="Kimi Code full rollout",
                        )
                    if dataset == "DeepSWE" or dataset.startswith("Terminal"):
                        conditions["harness"] = "Claude Code" if "K3.1" in hf else "Kimi Code"
                    if dataset == "MMMU-Pro":
                        conditions["tools"] = "python" if pos == 1 or "python" in label else "none"
                if hf.startswith("Qwen/"):
                    conditions["parameter_count"] = {
                        "Qwen3.8-2.4T-A95B": "2.4T total / 95B active",
                        "Qwen3.8-27B": "27B",
                        "Qwen3.8-Flash-Next": "125B / 6B active; plus 51B n-gram embedding and 4B MTP",
                    }[hf.split("/")[1]]
                    if dataset == "DeepSWE":
                        conditions["harness"] = (
                            "mini-swe-agent; best across two harnesses"
                            if "Flash-Next" in hf
                            else "Claude Code"
                        )
                if "DeepSeek-V4.1" in hf:
                    conditions.update(
                        model_release_date="2026-10-17" if "1017" in hf else "2026-09-10",
                        release_date_source_url="https://api-docs.deepseek.com/news/news261017/"
                        if "1017" in hf
                        else "https://deepseek.com/en/news/deepseek-v4-1-flash/",
                        mode="max" if "1017" not in hf else "publisher reported; see method",
                    )
                    if "1017" not in hf:
                        conditions["parameter_count"] = (
                            "552B backbone / 8B prefill / 16B decode active"
                        )
                if "MiniMax" in hf:
                    conditions["parameter_count"] = "approximately 428B total / 23B active"
                    if dataset == "DeepSWE":
                        conditions.update(harness="mini-SWE-agent 2.4.5", context_window=524288)
                if dataset == "DeepSWE":
                    conditions["dataset_version"] = (
                        "v1.1"
                        if "1.1" in label or "Kimi-K3" in hf
                        else "not specified in table label; see method"
                    )
                if "Automation" in dataset:
                    conditions["dataset_version"] = (
                        "v1.0.6" if "1.0.6" in label else "not specified in table label; see method"
                    )
                key = hashlib.sha256(f"{model}|{label}|{pos}|{sha}".encode()).hexdigest()[:32]
                entry = {
                    "source_key": "latest-official-" + key,
                    "source_type": "official",
                    "model_name": model,
                    "dataset": dataset,
                    "metric": "publisher_reported_score",
                    "value": float(value),
                    "unit": "points",
                    "direction": "higher_is_better",
                    "scope": "full",
                    "conditions": conditions,
                    "source_name": "Publisher official Hugging Face model card",
                    "source_url": f"https://huggingface.co/{hf}",
                    "source_version": "sha256:" + sha,
                    "source_sha256": sha,
                    "report_id": None,
                    "notes": "Own-model column only. Original scale retained. See captured card footnotes for sampling, harness and version. full denotes published scope, not independently verified completeness. Not a Release baseline.",
                }
                entries.append(entry)
                evidence.append(
                    {
                        "source_key": entry["source_key"],
                        "source_file": card.name,
                        "sha256": sha,
                        "column_index": index,
                        "column_header": header,
                        "source_row": row,
                        "paired_value_index": pos,
                    }
                )
        assert seen, f"No own-model rows extracted for {hf}; inspect changed source structure"
    # This publisher card uses a chart, not a numeric table. Transcribe only the
    # labelled blue own-model bars; retain the exact image as primary evidence.
    hf, model = "zai-org/GLM-5.3-Flash", "ZhipuAI/GLM-5.3-Flash"
    image_url = (
        "https://raw.githubusercontent.com/zai-org/GLM-5/refs/heads/main/resources/bench_53.png"
    )
    image_path = OUT / "GLM-5.3-Flash-benchmark.png"
    if not image_path.exists():
        image_path.write_bytes(urllib.request.urlopen(image_url, timeout=30).read())
    image_sha = hashlib.sha256(image_path.read_bytes()).hexdigest()
    identity_path = OUT / "ZhipuAI--GLM-5.3-Flash.identity.json"
    if not identity_path.exists():
        identity_path.write_bytes(
            urllib.request.urlopen(
                f"https://modelscope.cn/api/v1/models/{model}", timeout=30
            ).read()
        )
    identity = json.loads(identity_path.read_bytes())
    assert identity["Code"] == 200 and identity["Data"]["Name"] == "GLM-5.3-Flash"
    assert identity["Data"]["Path"] == "ZhipuAI"
    identities[model] = {"huggingface_id": hf, "modelscope_id": model}
    for dataset, value, version, harness in [
        ("Terminal-Bench 2.1", 84.3, "2.1", "Claude Code 2.1.207"),
        ("DeepSWE", 63.4, "v1.1", "mini-swe-agent"),
        ("AutomationBench", 48.8, "v1.0.6", "see publisher method"),
    ]:
        key = hashlib.sha256(f"{model}|{dataset}|{image_sha}".encode()).hexdigest()[:32]
        entry = {
            "source_key": "latest-official-" + key,
            "source_type": "official",
            "model_name": model,
            "dataset": dataset,
            "metric": "publisher_reported_score",
            "value": value,
            "unit": "points",
            "direction": "higher_is_better",
            "scope": "full",
            "conditions": {
                **metadata["glm-5.3-flash"],
                "huggingface_model_id": hf,
                "modelscope_model_id": model,
                "mode": "max",
                "evaluated_at": "未披露",
                "dataset_version": version,
                "harness": harness,
                "tool_revision": "unknown",
                "sample_manifest": "unknown",
                "extraction": "visually checked labelled own-model blue bar",
                "captured_on": "2026-11-11",
                "method_source_url": f"https://huggingface.co/{hf}",
            },
            "source_name": "Z.ai official benchmark chart",
            "source_url": image_url,
            "source_version": "sha256:" + image_sha,
            "source_sha256": image_sha,
            "report_id": None,
            "notes": "Original chart value, own-model bar only. Publisher reference, not independently reproduced. Not a Release baseline.",
        }
        entries.append(entry)
        evidence.append(
            {
                "source_key": entry["source_key"],
                "source_file": image_path.name,
                "sha256": image_sha,
                "source_region": dataset + ": blue GLM-5.3-Flash labelled bar",
                "transcribed_value": value,
            }
        )
    for name, content in [
        ("entries.json", entries),
        ("evidence.json", evidence),
        ("identities.json", identities),
    ]:
        (OUT / name).write_text(
            json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return entries


def publish(entries):
    before = {r["id"]: r for g in request("/data-workbench/published") for r in g["entries"]}
    for entry in entries:
        row = request("/data-workbench/entries", entry)
        if row["state"] == "draft":
            row = request(
                f"/data-workbench/entries/{row['id']}/review",
                {
                    "action": "approve",
                    "expected_revision": row["revision"],
                    "reason": "User requested latest official model records; own-model column and ModelScope identity checked; preserve source evidence, versions, missing dates and method distinctions.",
                },
            )
        assert row["state"] == "approved"
    after = {r["id"]: r for g in request("/data-workbench/published") for r in g["entries"]}
    assert all(after.get(key) == value for key, value in before.items()), (
        "Historical records changed"
    )
    published = {r["entry"]["source_key"]: r["entry"] for r in after.values()}
    assert all(published.get(e["source_key"]) == e for e in entries)
    return {
        "before": len(before),
        "after": len(after),
        "added": len(after) - len(before),
        "read_back_verified": len(entries),
        "historical_records_unchanged": True,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    result = capture()
    print(json.dumps({"entries": len(result), "models": len({e["model_name"] for e in result})}))
    if args.publish:
        check = publish(result)
        (OUT / "verification.json").write_text(json.dumps(check, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(check))
