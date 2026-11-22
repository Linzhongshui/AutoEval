"""Write an AISBench sample intent before handing it to the pinned inferencer."""

import hashlib
import json
import os
import re
import sys
from functools import wraps
from pathlib import Path


def is_task_process(tool_root, kind, argv=None):
    """Exclude the adaptor, launcher, and scorer from the coverage marker."""
    arguments = sys.argv if argv is None else argv
    scripts = {
        "llm_accuracy": "ais_bench/benchmark/tasks/openicl_api_infer.py",
        "harbor_agent": "ais_bench/benchmark/tasks/custom_tasks/harbor_agent_task.py",
    }
    if not arguments or kind not in scripts:
        return False
    return Path(arguments[0]).resolve() == (Path(tool_root) / scripts[kind]).resolve()


def install_harbor(trial, journal, aliases):
    original = trial.run
    journal = Path(journal)
    journal.mkdir(mode=0o700, exist_ok=True)

    @wraps(original)
    async def observe(self, *args, **kwargs):
        task_id = aliases.get(self.task.name)
        if task_id is None:
            raise ValueError("Harbor trial exceeds the frozen sample selection")
        trial_name = self.config.trial_name
        if not isinstance(trial_name, str) or not trial_name:
            raise ValueError("Harbor trial has no stable identity")
        raw = json.dumps({"tool_case_id": task_id, "trial_name": trial_name}).encode()
        name = hashlib.sha256(raw).hexdigest()
        with (journal / name).open("wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        directory = os.open(journal, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return await original(self, *args, **kwargs)

    trial.run = observe
    (journal / "instrumented").touch(mode=0o600, exist_ok=True)


def install(inferencer, journal, contract):
    original = inferencer.do_request
    expected = set(contract["case_ids"])
    if any(not re.fullmatch(r"[0-9]+", case_id) for case_id in expected):
        raise ValueError("Dispatch journal requires numeric tool sample IDs")
    journal = Path(journal)
    journal.mkdir(mode=0o700, exist_ok=True)

    @wraps(original)
    async def observe(self, data, *args, **kwargs):
        index = str(data.get("index"))
        mapping = contract.get("slice_index_to_tool_id")
        case_id = mapping.get(index) if mapping is not None else index
        if data.get("data_abbr") != contract["dataset_abbr"] or case_id not in expected:
            raise ValueError("Inference exceeds the frozen sample selection")
        # A durable intent precedes any model I/O. A crash may leave an intent
        # without a result, which must be reconciled rather than resent.
        descriptor = os.open(journal / case_id, os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        directory = os.open(journal, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return await original(self, data, *args, **kwargs)

    inferencer.do_request = observe
    (journal / "instrumented").touch(mode=0o600, exist_ok=True)
