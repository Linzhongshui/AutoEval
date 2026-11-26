"""在控制端运行 MiniSwe 2.4.6，将 shell 命令送入已有的 DeepSWE Lite 样本容器。"""

import json
import math
import os
import re
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlsplit

from minisweagent.agents.default import AgentConfig, DefaultAgent
from minisweagent.config import get_config_from_spec
from minisweagent.environments.docker import DockerEnvironment
from minisweagent.models import get_model, get_model_class

LITE_IMAGE = "sha256:85f743fa1c3b772abbac100056350657e771a10196c31512f68fc4dc114c19cd"
LOG_MOUNTS = {"/logs/agent", "/logs/verifier", "/logs/artifacts"}
MODES = {"tools": ("mini.yaml", "litellm"), "text": ("default.yaml", "litellm_textbased")}


class ExistingTrialDocker(DockerEnvironment):
    def _start_container(self):
        container_id = os.environ["MINISWE_TRIAL_CONTAINER"]
        if not re.fullmatch(r"[a-f0-9]{64}", container_id):
            raise ValueError("Unexpected trial container ID")
        details = json.loads(subprocess.check_output(["docker", "inspect", container_id]))[0]
        if (
            not details["State"]["Running"]
            or details["HostConfig"]["NetworkMode"] != "none"
            or details["HostConfig"]["Privileged"]
            or self.config.forward_env
            or details["Image"] != LITE_IMAGE
        ):
            raise ValueError("Trial identity or isolation does not match")
        if any(mount["Destination"] not in LOG_MOUNTS for mount in details["Mounts"]):
            raise ValueError("Unexpected mount in trial environment")
        self.container_id = container_id

    def cleanup(self):
        # Pier 负责收集补丁并销毁本次试验容器。
        pass


def build_configs(mode):
    if mode not in MODES:
        raise ValueError("MINISWE_MODE must be tools or text")
    yaml_name, model_class = MODES[mode]
    config = get_config_from_spec(yaml_name)
    agent = config["agent"]
    agent.pop("mode", None)
    agent["max_consecutive_format_errors"] = 1
    if "MINISWE_STEP_LIMIT" in os.environ:
        step_limit = int(os.environ["MINISWE_STEP_LIMIT"])
        if step_limit < 0:
            raise ValueError("MINISWE_STEP_LIMIT must be nonnegative")
        agent["step_limit"] = step_limit
    if "MINISWE_COST_LIMIT" in os.environ:
        cost_limit = float(os.environ["MINISWE_COST_LIMIT"])
        if cost_limit < 0 or not math.isfinite(cost_limit):
            raise ValueError("MINISWE_COST_LIMIT must be finite and nonnegative")
        agent["cost_limit"] = cost_limit
    config["model"].update(model_class=model_class, cost_tracking="ignore_errors")
    options = config["model"]["model_kwargs"]
    options.update(
        num_retries=0, max_retries=0, timeout=float(os.getenv("MINISWE_REQUEST_TIMEOUT", "600"))
    )
    if os.getenv("MINISWE_THINKING_DISABLED") == "1":
        options["extra_body"] = {"thinking": {"type": "disabled"}}
    if max_tokens := os.getenv("MINISWE_MAX_TOKENS"):
        options["max_tokens"] = int(max_tokens)
    return config


def validate_model(model):
    base = urlsplit(os.environ["OPENAI_API_BASE"])
    if (
        not base.hostname
        or base.username is not None
        or base.password is not None
        or base.query
        or base.fragment
    ):
        raise ValueError("Expected a model API base URL without embedded credentials")
    local_hosts = {"127.0.0.1", "localhost", "::1", "host.docker.internal"}
    if base.scheme != "https" and not (base.scheme == "http" and base.hostname in local_hosts):
        raise ValueError("Plain HTTP is supported only for a local model")
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("Set a protected OPENAI_API_KEY")
    if not model or not model.startswith("openai/") or model == "openai/":
        raise ValueError("Use openai/<model or gateway alias> with the selected chat API")


def main():
    if version("mini-swe-agent") != "2.4.6":
        raise RuntimeError("This DeepSWE Lite runner requires mini-swe-agent 2.4.6")
    if sys.argv[1:] == ["--self-check"]:
        for mode in MODES:
            config = build_configs(mode)
            AgentConfig(**config["agent"])
            get_model_class("openai/compat", config["model"]["model_class"])
        print("MiniSwe 2.4.6 tool/text configuration OK")
        return
    request = json.load(sys.stdin)
    validate_model(request["model"])
    config = build_configs(os.getenv("MINISWE_MODE", "tools"))
    env = ExistingTrialDocker(image=LITE_IMAGE, cwd="/app", **config["environment"])
    config["agent"]["output_path"] = Path(request["trajectory"])
    model = get_model(request["model"], config["model"])
    DefaultAgent(model, env, **config["agent"]).run(request["instruction"])


if __name__ == "__main__":
    main()
