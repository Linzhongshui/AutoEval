"""Fixed native Linux AISBench code; synthetic inputs are not benchmark scores."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from autoeval.config import get_settings

pytestmark = pytest.mark.skipif(
    not os.environ.get("AE_AISBENCH_NATIVE_TEST"), reason="Pinned native tool required in Docker"
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


def test_native_scorer_matches_direct_path_and_preserves_empty_output_rule():
    payload = {
        "operation": "score_gpqa_0shot",
        "predictions": ["The correct answer is A", ""],
        "references": ["A", "B"],
    }
    adapted = bridge(payload)
    direct = invoke(
        [
            "-c",
            "import json,sys; from ais_bench.benchmark.datasets.gpqa import GPQAEvaluator; from ais_bench.benchmark.utils.postprocess.text_postprocessors import first_option_postprocess; p=json.load(sys.stdin); print(json.dumps(GPQAEvaluator().score([first_option_postprocess(t,options='ABCD') for t in p['predictions']],p['references'])))",
        ],
        payload,
    )
    assert adapted["native_result"] == json.loads(direct.stdout)
    assert adapted["native_result"]["accuracy"] == 50
    assert adapted["diagnostics"]["empty_outputs"] == [1]
    assert adapted["scoring_rules_changed"] is False
    lock = json.loads((Path(__file__).parents[1] / "tool-locks/aisbench.json").read_text())
    assert adapted["tool_revision"] == lock["revision"]


def test_native_loader_keeps_full_dataset_option_permutation():
    # Fixture is deliberately not a downloaded GPQA question.
    csv = "h0,h1,h2,h3,h4,h5,h6,Question,A,B,C,D\n,,,,,,,Fixture one,right,wrong1,wrong2,wrong3\n,,,,,,,Fixture two,right2,wrong4,wrong5,wrong6\n"
    invoke(
        [
            "-c",
            "import json,sys; from pathlib import Path; Path('/work/tools/aisbench/fixture.csv').write_text(json.load(sys.stdin), encoding='utf-8')",
        ],
        csv,
    )
    data = bridge(
        {"operation": "prepare_gpqa_diamond", "csv_path": "/work/tools/aisbench/fixture.csv"}
    )
    assert len(data["samples"]) == 2
    assert [row["native_sample"]["answer"] for row in data["samples"]] == ["D", "C"]
    assert [row["sample_id"] for row in data["samples"]] == ["gpqa_diamond:0", "gpqa_diamond:1"]
    assert all(len(row["sha256"]) == 64 for row in data["samples"])
