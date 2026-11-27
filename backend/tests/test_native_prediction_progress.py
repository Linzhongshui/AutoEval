import hashlib
import json

import pytest

from autoeval_runtime.native_predictions import collect, selected


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


async def test_nonzero_slice_uses_original_ids_for_intent_and_results(tmp_path, monkeypatch):
    from autoeval.planning.planning_observations import case_contract
    from autoeval_runtime.planning_runtime import restore_accuracy_indices
    from autoeval_runtime.sample_dispatch import install

    task = {
        "dataset": "GPQA",
        "compilation": {"config": {"params": {"abbr": "model-run", "dataset_test_range": "[4:6]"}}},
        "samples": [{"tool_case_id": str(i), "sample_id": f"sample:{i}"} for i in (4, 5)],
    }
    selection = case_contract(task)
    fsynced = []
    calls = []

    class Inferencer:
        async def do_request(self, data):
            assert (tmp_path / "4").is_file()
            assert len(fsynced) == 2
            calls.append(data["index"])

    # Directory fsync is only available on the Linux executor.
    import os

    original_open = os.open
    monkeypatch.setattr(
        "autoeval_runtime.sample_dispatch.os.open",
        lambda path, flags, *rest: (
            original_open(tmp_path / "4", flags)
            if path == tmp_path
            else original_open(path, flags, *rest)
        ),
    )
    monkeypatch.setattr("autoeval_runtime.sample_dispatch.os.fsync", fsynced.append)
    install(Inferencer, tmp_path, selection)
    inferencer = Inferencer()
    await inferencer.do_request({"index": 0, "data_abbr": selection["dataset_abbr"]})
    with pytest.raises(ValueError):
        await inferencer.do_request({"index": 3, "data_abbr": selection["dataset_abbr"]})
    assert calls == [0]
    assert not (tmp_path / "0").exists()

    payload = json.dumps(row(0))
    file = {"content": payload, "sha256": hashlib.sha256(payload.encode()).hexdigest()}
    assert set(selected([file], selection)) == {"4"}
    unified = {"cases": [{"case_id": "0"}]}
    restore_accuracy_indices(unified, selection)
    assert unified["cases"] == [{"case_id": "4", "native_case_id": "0"}]


@pytest.mark.parametrize("has_predictions", [True, False])
def test_runtime_publishes_observed_counts_and_archives_native_files_without_models(
    tmp_path, monkeypatch, has_predictions
):
    import sys
    import time

    from autoeval_runtime import native_predictions
    from autoeval_runtime import planning_runtime as runtime

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
            if has_predictions:
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
                "config": {"subcommand": "llm_accuracy", "params": {"ais_bench_root": str(tmp_path)}},
            },
        },
    )
    assert [p["finish_count"] for p in seen] == ([1, 2, 3] if has_predictions else [0, 0, 0])
    final = json.loads((tmp_path / "progress.json").read_text())
    assert (
        final["finish_count"] == (3 if has_predictions else 0)
        and final["total_count"] == 3
        and final["snapshot_kind"] == "final"
    )
    assert final["process_id"] == 1234
    assert bool(result["native_files"]) is has_predictions
    assert result["tool_exit_code"] == 0
    if has_predictions:
        assert result["diagnostic"] is None
    else:
        assert "produced no unified cases" in result["diagnostic"]
    assert not (tmp_path / "credential.json").exists()
