#!/usr/bin/env bash
set -euo pipefail
revision=6ca5ef9b8fedc78e8106d202a5c6a84e6f24f940
target="${1:?Usage: setup.sh /absolute/new/harborstack-directory}"
if [ -e "$target" ]; then echo "Target already exists" >&2; exit 1; fi
git clone https://github.com/llauren48/harbor-otel-stack "$target"
cd "$target"
git checkout --detach "$revision"
uv sync --frozen
uv run harborstack doctor
uv run harborstack init
