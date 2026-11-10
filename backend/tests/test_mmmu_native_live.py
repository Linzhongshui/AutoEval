"""Pinned native MMMU-Pro paths with synthetic fixtures, never benchmark scores."""

import json
import os
import subprocess

import pytest

from autoeval.config import get_settings

pytestmark = pytest.mark.skipif(
    not os.environ.get("AE_MMMU_NATIVE_TEST"), reason="Pinned native tool required in Docker"
)


def invoke(arguments, payload):
    settings = get_settings()
    return subprocess.run(
        [
            settings.docker_executable,
            "exec",
            "-i",
            "-e",
            "PYTHONPATH=/work/tools/aisbench/site-packages:/work/tools/aisbench/source",
            "autoeval-demo-executor-1",
            "python",
            *arguments,
        ],
        input=json.dumps(payload).encode(),
        capture_output=True,
        check=True,
        timeout=120,
    )


def bridge(payload):
    result = invoke(
        [
            "/work/tools/aisbench/bridge.py",
            "/work/tools/aisbench/source",
            "/work/tools/aisbench/lock.json",
        ],
        payload,
    )
    return json.loads(result.stdout)


def fixture():
    image = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    rows = [
        {"index": 11, "question": "Choose A", "A": "one", "B": "two", "answer": "A", "category": "fixture-a", "image": image},
        {"index": 22, "question": "Choose B", "A": "one", "B": "two", "answer": "B", "category": "fixture-b", "image": image},
    ]
    invoke(
        [
            "-c",
            "import json,sys; from pathlib import Path; import pandas as pd; p=Path('/work/tools/aisbench/mmmu-fixture'); p.mkdir(exist_ok=True); pd.DataFrame(json.load(sys.stdin)).to_csv(p/'fixture.tsv',sep='\t',index=False)",
        ],
        rows,
    )


def test_native_mmmu_loader_and_prompt_keep_all_rows_before_lite_selection():
    fixture()
    prepared = bridge(
        {
            "operation": "prepare_mmmu_pro_options10",
            "tsv_path": "/work/tools/aisbench/mmmu-fixture/fixture.tsv",
        }
    )
    assert len(prepared["samples"]) == 2
    assert [row["sample_id"] for row in prepared["samples"]] == [
        "mmmu_pro_options10:11",
        "mmmu_pro_options10:22",
    ]
    assert all(set(row["native_sample"]) == {"content", "answer"} for row in prepared["samples"])
    assert all(len(row["sha256"]) == 64 for row in prepared["samples"])
    assert all("/work/" not in row["native_sample"]["content"] for row in prepared["samples"])
    assert all(len(row["images"]) == 1 and len(row["images"][0]["sha256"]) == 64 for row in prepared["samples"])
    prompt = bridge(
        {
            "operation": "prompt_mmmu_pro_options10_cot",
            "sample": prepared["samples"][0]["native_sample"],
            "images": prepared["samples"][0]["images"],
        }
    )["prompt"]
    human = next(item for item in prompt if item.get("role") == "HUMAN")
    assert human["prompt_mm"][0]["image_url"]["url"].startswith("file://")
    assert "Question: Choose A" in human["prompt_mm"][1]["text"]


def test_native_mmmu_scorer_matches_direct_path_and_preserves_categories():
    payload = {
        "operation": "score_mmmu_pro_options10_cot",
        "predictions": ["Reasoning\nAnswer: A", "Answer: A", ""],
        "references": [
            json.dumps([{"A": "one", "B": "two"}, "A", "fixture-a"]),
            json.dumps([{"A": "one", "B": "two"}, "B", "fixture-b"]),
            json.dumps([{"A": "one", "B": "two"}, "A", "fixture-a"]),
        ],
    }
    adapted = bridge(payload)
    direct = invoke(
        [
            "-c",
            "import json,sys; from ais_bench.benchmark.datasets.mmmu_pro import MMMUProCotEvaluator; from ais_bench.benchmark.utils.postprocess.text_postprocessors import last_option_postprocess; p=json.load(sys.stdin); print(json.dumps(MMMUProCotEvaluator().score([last_option_postprocess(t,options='ABCDEFGHIJ') for t in p['predictions']],p['references'])))",
        ],
        payload,
    )
    assert adapted["native_result"] == json.loads(direct.stdout)
    assert adapted["native_result"]["Overall"] == 100 / 3
    assert adapted["native_result"]["fixture-a"] == 50
    assert adapted["native_result"]["fixture-b"] == 0
    assert adapted["diagnostics"]["empty_outputs"] == [2]
    assert adapted["scoring_rules_changed"] is False
