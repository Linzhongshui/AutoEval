#!/usr/bin/env bash
set -euo pipefail
revision=a62c1be62888e2cb5c89f92aa2dc00731f4f5ed1
target="${1:?Usage: setup.sh /absolute/new/harborstack-directory}"
if [ -e "$target" ]; then echo "Target already exists" >&2; exit 1; fi
git clone https://github.com/llauren48/harbor-otel-stack "$target"
cd "$target"
git checkout --detach "$revision"
uv sync --frozen
uv run harborstack doctor
uv run harborstack init
