"""Allowed tool dataset names derived only from frozen compilation inputs."""

import copy
import json
import math
import re
from pathlib import PurePosixPath


def allowed_result_datasets(dataset, config):
    params = config["params"]
    aliases = {"GPQA": "GPQA_diamond", "MMMU-Pro": "mmmu_pro", "DeepSWE": "harbor_deepswe-v1.1"}
    names = {
        dataset,
        aliases.get(dataset),
        params.get("dataset_abbr"),
        *(params.get("datasets") or []),
    }
    if config.get("subcommand") == "harbor_agent" and not params.get("dataset_abbr"):
        source = params.get("dataset_name_version")
        base = (
            str(source).split("@", 1)[0].rsplit("/", 1)[-1]
            if source
            else PurePosixPath(str(params.get("path", "agent")).rstrip("/")).name
        )
        base = re.sub(r"[^0-9A-Za-z_.-]+", "_", base).strip("_") or "agent"
        names.add("harbor_" + base)
    return names - {None}


def result_case_aliases(dataset, samples):
    """Harbor filters local directory IDs, but the official adapter names results.

    Only the pinned AutomationBench namespace is accepted; arbitrary prefixes
    and unknown sample IDs remain invalid.
    """
    aliases = {s["tool_case_id"]: s["sample_id"] for s in samples}
    if dataset == "AutomationBench":
        for sample in samples:
            native = sample["tool_case_id"]
            if not native.startswith("automationbench/"):
                aliases["automationbench/" + native] = sample["sample_id"]
    return aliases


def normalize_result_identities(result, dataset, config, samples):
    value = copy.deepcopy(result)
    allowed = allowed_result_datasets(dataset, config)
    aliases = result_case_aliases(dataset, samples)
    sample_ids = {s["sample_id"] for s in samples}
    if not isinstance(value.get("cases"), list):
        raise ValueError("Invalid result cases")  # noqa: TRY004 - result validation contract
    recovered_score = False
    for case in value["cases"]:
        if not isinstance(case, dict):
            raise ValueError("Invalid result case")  # noqa: TRY004 - result validation contract
        reported = case.get("dataset")
        # Harbor's per-trial contract omits dataset; the child input fixes it.
        if reported is not None and reported not in allowed:
            raise ValueError("Unexpected result dataset")
        identifier = case.get("case_id")
        if not isinstance(identifier, str):
            raise ValueError("Invalid result sample")  # noqa: TRY004 - result validation contract
        if identifier in aliases:
            case["case_id"] = aliases[identifier]
        elif identifier not in sample_ids:
            raise ValueError("Unexpected result sample")
        case["dataset"] = dataset
        if dataset == "AutomationBench" and case.get("status") == "success":
            missing_score = case.get("score") is None
            apply_automationbench_accuracy(case)
            recovered_score |= missing_score and case.get("score") is not None
    if recovered_score:
        # The adapter aggregate was computed without these named metrics. Preserve
        # it as provenance, rather than publishing its placeholder as a grade.
        value["upstream_adapter_total_score"] = value.get("total_score")
        value["total_score"] = None
        value["score_source"] = "harbor_native_verifier_accuracy"
    return value


def apply_automationbench_accuracy(case):
    """Recover the official named metric only when both native files agree.

    The original adapter output is archived separately by the caller. Do not
    infer a grade from execution success, a missing verifier, or other metrics.
    """
    if case.get("score") is not None:
        return
    files = (case.get("harbor_artifact") or {}).get("files", {})
    if "verifier/reward.json" not in files or "result.json" not in files:
        return
    try:
        reward = json.loads(files["verifier/reward.json"])
        native = json.loads(files["result.json"])
        accuracy = reward.get("accuracy")
        confirmed = (native.get("verifier_result") or {}).get("rewards", {}).get("accuracy")
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("Invalid native AutomationBench score") from exc
    if accuracy is None and confirmed is None:
        return
    if (
        type(accuracy) not in {int, float}
        or not math.isfinite(accuracy)
        or not 0 <= accuracy <= 1
        or type(confirmed) not in {int, float}
        or accuracy != confirmed
        or native.get("exception_info")
    ):
        raise ValueError("Native AutomationBench score evidence conflicts")
    case["score"] = accuracy
    case["score_name"] = "accuracy"
    case["score_source"] = "harbor_native_verifier"
