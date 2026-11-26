"""Harbor MiniSwe with a hash-locked, offline installer for the DeepSWE runner."""

from dataclasses import replace
from pathlib import Path

from harbor.agents.installed.mini_swe_agent import MiniSweAgent

WHEELHOUSE = Path("/acceptance/deepswe-lite-wheelhouse-20261120")
TRIAL_WHEELHOUSE = "/tmp/autoeval-deepswe-wheelhouse"


class OfflineMiniSweAgent(MiniSweAgent):
    @property
    def model_connection(self):
        access = super().model_connection
        environment = {**access.env, "MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT": "1"}
        if self.model_name and self.model_name.startswith("deepseek/"):
            if not access.configured_base_url or not access.api_key:
                raise ValueError("DeepSWE requires an explicit model gateway and credential")
            if self._max_tokens is None:
                raise ValueError("DeepSWE requires an explicit completion token limit")
            environment.update(
                DEEPSEEK_API_BASE=access.configured_base_url,
                DEEPSEEK_API_KEY=access.api_key,
            )
        return replace(access, env=environment)

    async def install(self, environment):
        if not (WHEELHOUSE / "requirements.lock").is_file():
            raise ValueError("DeepSWE offline wheelhouse is missing")
        await self.exec_as_agent(
            environment,
            command=f"mkdir -m 700 -p {TRIAL_WHEELHOUSE}",
        )
        await environment.upload_dir(WHEELHOUSE, TRIAL_WHEELHOUSE)
        await self.exec_as_agent(
            environment,
            command=f"""set -eu
cd {TRIAL_WHEELHOUSE}
sha256sum --quiet -c sha256sums
python3 -c 'import sys; assert sys.version_info[:2] == (3, 12)'
venv="$HOME/.local/share/autoeval-mini-swe"
python3 -m venv "$venv"
"$venv/bin/python" -m pip --disable-pip-version-check install \\
    --no-index --find-links . --require-hashes -r requirements.lock
mkdir -p "$HOME/.local/bin"
ln -s "$venv/bin/mini-swe-agent" "$HOME/.local/bin/mini-swe-agent"
LITELLM_LOCAL_MODEL_COST_MAP=True "$venv/bin/mini-swe-agent" --help >/dev/null
""",
        )

    def get_version_command(self):
        return (
            '"$HOME/.local/share/autoeval-mini-swe/bin/python" -c '
            "'from importlib.metadata import version; print(version(\"mini-swe-agent\"))'"
        )
