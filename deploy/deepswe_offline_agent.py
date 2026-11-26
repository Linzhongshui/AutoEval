"""Harbor MiniSwe with a hash-locked, offline installer for the DeepSWE runner."""

import hashlib
from dataclasses import replace
from pathlib import Path

from harbor.agents.installed.mini_swe_agent import MiniSweAgent

WHEELHOUSE = Path("/acceptance/deepswe-lite-wheelhouse-20261120")
TRIAL_WHEELHOUSE = "/tmp/autoeval-deepswe-wheelhouse"


class OfflineMiniSweAgent(MiniSweAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.model_name == "deepseek-flash" and self.extra_env.get("OPENAI_BASE_URL"):
            self.model_name = "deepseek/" + self.model_name

    @property
    def model_connection(self):
        access = super().model_connection
        if self.model_name != "deepseek/deepseek-flash" or not self.extra_env.get(
            "OPENAI_BASE_URL"
        ):
            return access
        endpoint = self.extra_env["OPENAI_BASE_URL"]
        credential = self.extra_env.get("OPENAI_API_KEY")
        if not credential or self._max_tokens is None:
            raise ValueError("DeepSWE requires the configured gateway token and output limit")
        return replace(
            access,
            api_key=credential,
            env={
                **access.env,
                "DEEPSEEK_API_BASE": endpoint,
                "DEEPSEEK_API_KEY": credential,
                "MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT": "1",
            },
        )

    async def install(self, environment):
        if not WHEELHOUSE.is_dir():
            return await super().install(environment)
        if self._version and str(self._version) != "2.4.6":
            raise ValueError("Offline wheelhouse only supports MiniSwe 2.4.6")
        manifest = WHEELHOUSE / "sha256sums"
        if hashlib.sha256(manifest.read_bytes()).hexdigest() != (
            "5365624582ff0bd98eb8ccf3b5ef91479df349f8f90173c28b87f1b1919c209e"
        ):
            raise ValueError("DeepSWE offline wheelhouse manifest mismatch")
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
        if not WHEELHOUSE.is_dir():
            return super().get_version_command()
        return (
            '"$HOME/.local/share/autoeval-mini-swe/bin/python" -c '
            "'from importlib.metadata import version; print(version(\"mini-swe-agent\"))'"
        )
