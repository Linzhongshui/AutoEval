import hashlib
import json

import pytest

from autoeval.native_predictions import collect, selected


def contract():
    return {
        "model_abbr": "model-run",
        "dataset_abbr": "GPQA_diamond",
        "case_ids": ["0", "1", "2"],
        "sample_ids": {str(i): f"sample:{i}" for i in range(3)},
        "dataset": "GPQA",
    }


def row(index, **changes):
    return {
        "data_abbr": "GPQA_diamond",
        "id": index,
        "uuid": f"uuid-{index}",
        "success": True,
        "prediction": "A",
        "origin_prompt": [{"prompt": "Question"}],
        **changes,
    }


def test_streaming_partial_multiline_and_duplicate_files_do_not_inflate_progress(tmp_path):
    path = tmp_path / "predictions/model-run/tmp/partial.jsonl"
    path.parent.mkdir(parents=True)
    data = json.dumps(row(0), indent=2) + "\n" + json.dumps(row(1), indent=2)
    path.write_text(data + '\n{"data_abbr":', encoding="utf-8")
    observations = selected(collect(tmp_path, contract()), contract())
    assert set(observations) == {"0", "1"}
    final = path.parent.parent / "GPQA_diamond.jsonl"
    final.write_text(data, encoding="utf-8")
    assert len(selected(collect(tmp_path, contract()), contract())) == 2
    path.write_text(
        data + "\n" + json.dumps(row(2, success=False, prediction=None)), encoding="utf-8"
    )
    assert len(selected(collect(tmp_path, contract()), contract())) == 3


def test_wrong_dataset_model_and_out_of_range_records_are_not_current_progress(tmp_path):
    path = tmp_path / "predictions/other-model/results.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(row(0)), encoding="utf-8")
    assert collect(tmp_path, contract()) == []
    content = json.dumps(row(9)) + "\n" + json.dumps(row(0, data_abbr="other"))
    file = {"content": content, "sha256": hashlib.sha256(content.encode()).hexdigest()}
    assert selected([file], contract()) == {}
    with pytest.raises(ValueError):
        selected([{**file, "sha256": "0" * 64}], contract())


def test_conflicting_case_identity_is_not_silently_replaced():
    content = json.dumps(row(0)) + "\n" + json.dumps(row(0, uuid="foreign-request"))
    with pytest.raises(ValueError):
        selected(
            [{"content": content, "sha256": hashlib.sha256(content.encode()).hexdigest()}],
            contract(),
        )


def test_runtime_publishes_observed_counts_and_archives_native_files_without_models(
    tmp_path, monkeypatch
):
    import sys
    import time

    from autoeval import native_predictions
    from autoeval import planning_runtime as runtime

    monkeypatch.setitem(sys.modules, "native_predictions", native_predictions)
    monkeypatch.setattr(runtime, "installed_revision", lambda _: runtime.ADAPTOR_REVISION)
    monkeypatch.setattr(runtime, "verify_tool", lambda _: "fixture-revision")
    (tmp_path / "credential.json").write_text('{"value":"TEST-only"}')
    output = tmp_path / "output"
    seen = []

    class Process:
        pid = 1234
        returncode = None
        calls = 0

        def __init__(self, command, **kwargs):
            assert command[0] == "autoeval-adaptor"

        def poll(self):
            self.calls += 1
            path = output / "predictions/model-run/tmp/current.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(json.dumps(row(i)) for i in range(min(self.calls, 3))))
            if self.calls == 4:
                (output / "unified_result.json").write_text("{}")
                self.returncode = 0
            return self.returncode

    monkeypatch.setattr(runtime.subprocess, "Popen", Process)
    monkeypatch.setattr(
        time, "sleep", lambda _: seen.append(json.loads((tmp_path / "progress.json").read_text()))
    )
    result = runtime.execute(
        tmp_path,
        {
            "kind": "adaptor",
            "credential": "runtime-only",
            "tool": {},
            "case_contract": contract(),
            "compilation": {
                "adaptor_revision": runtime.ADAPTOR_REVISION,
                "config": {"subcommand": "llm_accuracy", "params": {}},
            },
        },
    )
    assert [p["finish_count"] for p in seen] == [1, 2, 3]
    final = json.loads((tmp_path / "progress.json").read_text())
    assert (
        final["finish_count"] == 3
        and final["total_count"] == 3
        and final["snapshot_kind"] == "final"
    )
    assert final["process_id"] == 1234 and result["native_files"]
    assert not (tmp_path / "credential.json").exists()
