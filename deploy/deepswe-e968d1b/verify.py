"""Run inside the built image with --network none. Never executes a model request."""

import asyncio
import logging
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import yaml
from ais_bench.benchmark.runners import harbor_monitor, harbor_runner
from ais_bench.benchmark.utils.logging.logger import AISLogger
from harbor.agents.factory import AgentFactory, AgentName
from mmengine.config import ConfigDict


class OfflineEnvironment:
    default_user = None

    def __init__(self):
        self.uploads = 0
        self.invocations = []

    async def upload_dir(self, source, target):
        self.uploads += 1
        shutil.copytree(source, target, dirs_exist_ok=True)

    async def exec(self, command, **kwargs):
        if "mini-swe-agent --yolo" in command:
            self.invocations.append((command, kwargs["env"]))
            return SimpleNamespace(return_code=0, stdout="", stderr="")
        result = await asyncio.to_thread(
            subprocess.run,
            ["bash", "-c", command],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise RuntimeError(result.stderr[-2000:])
        return SimpleNamespace(
            return_code=0, stdout=result.stdout, stderr=result.stderr
        )


async def check_agent():
    endpoint = {
        "OPENAI_BASE_URL": "http://example.invalid/v1",
        "OPENAI_API_KEY": "test",
    }
    config = ConfigDict(
        agent={"step_limit": 500}, model={"model_kwargs": {"temperature": 1.0}}
    )

    def create(model, env):
        return AgentFactory.create_agent_from_name(
            AgentName.MINI_SWE_AGENT,
            Path("/tmp"),
            model_name=model,
            extra_env=env,
            config=config,
        )

    assert create("anthropic/test", endpoint).model_name == "anthropic/test"
    assert create("openai/test", endpoint).model_name == "openai/test"
    assert create("test", {}).model_name == "test"
    agent = create("deepseek-flash", endpoint)
    assert yaml.safe_load(agent._config_yaml) == config
    env = OfflineEnvironment()
    await agent.install(env)
    assert env.uploads == 1
    await agent.install(env)
    assert env.uploads == 1
    assert (await env.exec(agent.get_version_command())).stdout.strip() == "2.4.6"
    await agent.run("smoke", env, Mock())
    [(command, model_env)] = env.invocations
    assert "--model=openai/deepseek-flash " in command
    assert model_env["OPENAI_BASE_URL"] == endpoint["OPENAI_BASE_URL"]
    assert agent.model_connection.api_key == endpoint["OPENAI_API_KEY"]


def check_error_log():
    monitor_module = harbor_monitor
    logger = AISLogger()
    fake = SimpleNamespace(
        logger=logger,
        refresh_interval=1,
        monitor_port=0,
        task_cfg={"type": "test"},
        _task_job_dir=lambda _: None,
    )
    with (
        patch.object(monitor_module, "HarborMonitor"),
        patch.object(monitor_module, "HarborMonitorServer") as server,
        patch.object(harbor_runner, "task_abbr_from_cfg", return_value="smoke"),
        patch.object(
            harbor_runner.TASKS, "build", side_effect=ValueError("original failure")
        ),
        patch.object(logger.logger, "error", wraps=logger.logger.error) as emitted,
    ):
        server.return_value.start.return_value = 0
        assert harbor_runner.HarborRunner._launch_inline(
            fake, {"work_dir": "/tmp"}
        ) == ("smoke", 1)
        assert emitted.call_args.kwargs["exc_info"] is True


if __name__ == "__main__":
    os.environ["HOME"] = "/tmp/issue38-agent-home"
    Path(os.environ["HOME"]).mkdir()
    logging.disable(logging.INFO)
    asyncio.run(check_agent())
    check_error_log()
    print(
        "Offline install/reuse, Harbor configuration, command construction and error logging passed"
    )
