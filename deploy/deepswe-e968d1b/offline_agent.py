"""Mini-SWE integration for the pinned e968d1b offline execution image."""

from collections.abc import Mapping
from pathlib import Path

from harbor.agents.installed.mini_swe_agent import MiniSweAgent


def plain_yaml(value):
    if isinstance(value, Mapping):
        return {key: plain_yaml(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain_yaml(item) for item in value]
    return value


class OfflineMiniSweAgent(MiniSweAgent):
    def __init__(self, *, config=None, model_name=None, extra_env=None, **kwargs):
        env = extra_env or {}
        if model_name and "/" not in model_name and (
            env.get("OPENAI_BASE_URL") or env.get("OPENAI_API_BASE")
        ):
            model_name = "openai/" + model_name
        super().__init__(
            config=plain_yaml(config), model_name=model_name, extra_env=extra_env, **kwargs
        )

    def get_version_command(self):
        return """export PATH="$HOME/.local/bin:$PATH"
cli=$(command -v mini-swe-agent) && "$(dirname "$(readlink -f "$cli")")/python" \\
-c 'from importlib.metadata import version; print(version("mini-swe-agent"))'"""

    async def install(self, environment):
        if self._version and str(self._version) != "2.4.6":
            raise ValueError("DeepSWE offline release requires Mini-SWE 2.4.6")
        # Harbor starts a new shell for each exec; run() looks in ~/.local/bin.
        probe = await self.exec_as_agent(environment, command=r"""set -eu
export PATH="$HOME/.local/bin:/opt/miniswe/bin:$PATH"
cli=$(command -v mini-swe-agent || true)
if [ -n "$cli" ]; then
    cli=$(readlink -f "$cli")
    py="$(dirname "$cli")/python"
    "$py" -c 'from importlib.metadata import version; assert version("mini-swe-agent") == "2.4.6"'
    LITELLM_LOCAL_MODEL_COST_MAP=True "$cli" --help >/dev/null
    mkdir -p "$HOME/.local/bin"
    dest="$HOME/.local/bin/mini-swe-agent"
    if [ "$(readlink -f "$dest")" != "$cli" ]; then ln -sf "$cli" "$dest"; fi
    echo mini-swe-ready
fi""")
        if (probe.stdout or "").strip().endswith("mini-swe-ready"):
            return
        wheels = "/tmp/autoeval-miniswe-wheels"
        await environment.upload_dir(Path("/opt/autoeval/miniswe-wheels"), wheels)
        await self.exec_as_agent(environment, command=f"""set -eu
cd {wheels}
sha256sum --quiet -c sha256sums
python3 -c 'import sys; assert sys.version_info[:2] == (3, 12)'
venv="$HOME/.local/share/autoeval-mini-swe"
python3 -m venv "$venv"
"$venv/bin/python" -m pip install --disable-pip-version-check --no-index \\
    --find-links . --require-hashes -r requirements.lock
mkdir -p "$HOME/.local/bin"
ln -sf "$venv/bin/mini-swe-agent" "$HOME/.local/bin/mini-swe-agent"
LITELLM_LOCAL_MODEL_COST_MAP=True "$venv/bin/mini-swe-agent" --help >/dev/null""")
