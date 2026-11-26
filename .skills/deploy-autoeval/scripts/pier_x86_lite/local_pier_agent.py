"""Pier 0.3.1 与 DeepSWE Lite 单题的 MiniSwe 控制端适配。"""

import asyncio
import json
import os
import re
import tempfile
import uuid
from importlib.metadata import version
from pathlib import Path

from pier.agents.base import BaseAgent
from pier.agents.installed.mini_swe_agent import convert_and_save_trajectory
from pier.environments.docker.docker import DockerEnvironment
from pier.utils.trajectory_metrics import populate_context_from_final_metrics

# 控制进程仅继承 Docker、模型网关、网络代理及信任链所需的环境。
PROCESS_ENV = [
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "TZ",
    "TMPDIR",
    "XDG_RUNTIME_DIR",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "ALL_PROXY",
    "all_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_CONFIG",
    "DOCKER_TLS",
    "DOCKER_TLS_VERIFY",
    "DOCKER_CERT_PATH",
    "DOCKER_API_VERSION",
    "OPENAI_API_BASE",
    "OPENAI_API_KEY",
    "MINISWE_MODE",
    "MINISWE_STEP_LIMIT",
    "MINISWE_COST_LIMIT",
    "MINISWE_REQUEST_TIMEOUT",
    "MINISWE_MAX_TOKENS",
    "MINISWE_THINKING_DISABLED",
]

INCOMPLETE = {"LimitsExceeded", "TimeExceeded", "RepeatedFormatError"}
VALIDATION_ERRORS = (
    "Unexpected trial container ID",
    "Trial identity or isolation does not match",
    "Unexpected mount in trial environment",
    "Expected a model API base URL",
    "Plain HTTP is supported only for a local model",
    "Set a protected OPENAI_API_KEY",
    "Use openai/<model or gateway alias>",
    "MINISWE_MODE must be tools or text",
    "MINISWE_STEP_LIMIT must be nonnegative",
    "MINISWE_COST_LIMIT must be finite and nonnegative",
)


def write_json(path, value):
    # 同目录原子替换，不跟随样本容器可能留在日志目录的文件链接。
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", dir=path.parent, delete=False, encoding="utf-8"
        ) as out:
            temporary = Path(out.name)
            json.dump(value, out, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]") if secret else value
    if isinstance(value, list):
        return [redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {key: redact(item, secret) for key, item in value.items()}
    return value


def read_trajectory(raw, secret):
    if not raw.is_file():
        return None, "missing-trajectory"
    try:
        value = redact(json.loads(raw.read_bytes()), secret)
    except (UnicodeError, json.JSONDecodeError):
        return None, "invalid-trajectory"

    if not isinstance(value, dict) or not isinstance(value.get("messages"), list):
        return None, "invalid-trajectory"
    return value, None


class ControllerMiniSwe(BaseAgent):
    SUPPORTS_ATIF = True

    @staticmethod
    def name():
        return "mini-swe-agent-controller"

    def version(self):
        return "2.4.6"

    async def setup(self, environment):
        if version("datacurve-pier") != "0.3.1" or not isinstance(environment, DockerEnvironment):
            raise ValueError("Expected Pier 0.3.1 with the local Docker environment")
        if environment.default_user is not None:
            raise ValueError("The pinned trial uses the image's default user")
        venv = Path(os.environ["MINI_VENV"])
        if not venv.is_absolute() or not (venv / "bin/python").is_file():
            raise ValueError("MINI_VENV must point to the installed MiniSwe virtual environment")
        if not os.getenv("OPENAI_API_BASE") or not os.getenv("OPENAI_API_KEY"):
            raise ValueError("Set the target OPENAI_API_BASE and protected OPENAI_API_KEY")

    async def run(self, instruction, environment, context):
        found = await environment._run_docker_compose_command(["ps", "-q", "main"])
        container_id = (found.stdout or "").strip()
        if not re.fullmatch(r"[0-9a-f]{64}", container_id):
            raise RuntimeError("Unable to identify a single live trial container")
        self.logs_dir.mkdir(exist_ok=True, parents=True)
        with tempfile.TemporaryDirectory(prefix="model-agent-") as directory:
            private = Path(directory)
            raw = private / "trajectory.json"
            console = private / "console"
            child_env = {key: os.environ[key] for key in PROCESS_ENV if key in os.environ}
            child_env.update(
                MINISWE_TRIAL_CONTAINER=container_id,
                MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT="1",
                LITELLM_LOCAL_MODEL_COST_MAP="True",
                LITELLM_TELEMETRY="False",
                MSWEA_COST_TRACKING="ignore_errors",
                OPENAI_MAX_RETRIES="0",
                OPENAI_BASE_URL=os.environ["OPENAI_API_BASE"],
                MSWEA_SILENT_STARTUP="1",
                PYTHONDONTWRITEBYTECODE="1",
            )
            payload = {"model": self.model_name, "instruction": instruction, "trajectory": str(raw)}
            with console.open("wb") as log:
                proc = await asyncio.create_subprocess_exec(
                    str(Path(os.environ["MINI_VENV"]) / "bin/python"),
                    str(Path(__file__).with_name("worker.py")),
                    env=child_env,
                    cwd=private,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=log,
                    stderr=log,
                )
                try:
                    await proc.communicate(json.dumps(payload).encode())
                finally:
                    if proc.returncode is None:
                        proc.kill()
                        await proc.wait()
                    self._save_evidence(raw, console, proc.returncode, context)
        status = context.metadata["miniswe"]
        if status["status"] == "failed":
            raise RuntimeError("MiniSwe failed. Check the trial's agent/agent-status.json")

    def _save_evidence(self, raw, console, code, context):
        value, read_error = read_trajectory(raw, os.environ["OPENAI_API_KEY"])
        messages = (value or {}).get("messages", [])
        # MiniSwe 将已收到但不符合工具格式的回复放在 user 消息的 extra.response。
        responses = sum(
            message.get("role") == "assistant"
            or message.get("object") == "response"
            or bool((message.get("extra") or {}).get("response"))
            for message in messages
        )
        info = (value or {}).get("info", {})
        reason = read_error or info.get("exit_status") or "missing-terminal-status"
        status = "failed"
        if code == 0 and responses:
            if reason == "Submitted":
                status = "submitted"
            elif reason in INCOMPLETE:
                status = "incomplete"
        # 仅保留诊断代码，原始提供方异常可能含凭据或请求正文。
        diagnostic = console.read_text(encoding="utf-8", errors="replace")
        evidence = {
            "status": status,
            "exit_reason": reason,
            "worker_exit_code": code,
            "model_query_attempts": info.get("model_stats", {}).get("api_calls"),
            "recorded_responses": responses,
            "api_http_statuses_in_console": sorted(
                set(
                    re.findall(
                        r"(?i)(?:status(?: code)?[ =:]*(?:HTTP[ /0-9.]+ )?|HTTP/[0-9.]+ )(\d{3})\b",
                        diagnostic,
                    )
                )
            ),
            "worker_exception_classes": re.findall(
                r"^(?:[\w.]+\.)?([A-Za-z]\w*(?:Error|Exception|Timeout)):",
                diagnostic,
                re.MULTILINE,
            )[-3:],
            "pre_request_validation": next(
                (key for key in VALIDATION_ERRORS if key in diagnostic), None
            ),
            "thinking_disabled": os.getenv("MINISWE_THINKING_DISABLED") == "1",
            "mode": os.getenv("MINISWE_MODE", "tools"),
            "automatic_retries": 0,
        }
        context.metadata = {"miniswe": evidence}
        status_path = self.logs_dir / "agent-status.json"
        write_json(status_path, evidence)
        if value is None:
            return
        # 转换始终以私有副本为输入，避免读回任务可能更改的挂载目录文件。
        native = raw.parent / "redacted.json"
        write_json(native, value)
        write_json(self.logs_dir / "mini-swe-agent.trajectory.json", value)
        if not responses:
            return
        atif = raw.parent / "atif.json"
        try:
            parsed = convert_and_save_trajectory(native, atif, str(uuid.uuid4()))
            write_json(self.logs_dir / "trajectory.json", json.loads(atif.read_bytes()))
        except (ValueError, TypeError, KeyError, OSError, AttributeError, IndexError):
            evidence["status"] = "failed"
            evidence["evidence_error"] = "trajectory-conversion-failed"
            write_json(status_path, evidence)
            raise RuntimeError("MiniSwe trajectory conversion failed") from None
        context.n_agent_steps = sum(step.source == "agent" for step in parsed.steps)
        if parsed.final_metrics:
            populate_context_from_final_metrics(context, parsed.final_metrics)
