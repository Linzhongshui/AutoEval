"""Allowed tool dataset names derived only from frozen compilation inputs."""

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
