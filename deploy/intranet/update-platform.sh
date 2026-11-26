#!/usr/bin/env bash
# Linux / Bash, Docker Compose v2. See docs/platform-update.md.
set -Eeuo pipefail
umask 077
rev=${REV:-8912940d0bfcef9b0913af73a0175ab2bfdc7981}
die() { echo "$*" >&2; exit 1; }
: "${REL:?absolute platform release directory required}"
[[ $REL = /* && $rev =~ ^[0-9a-f]{40}$ ]] || die "Use an absolute REL and full REV"
case ${1:-} in
build)
  repo=$(git rev-parse --show-toplevel)
  mkdir -m 700 "$REL"
  src=$(mktemp -d)
  git -C "$repo" archive "$rev" | tar -x -C "$src"
  cd "$src/frontend"
  npm ci
  npm run build
  tar czf "$REL/frontend-dist.tar.gz" dist
  cd "$src/backend"
  uv lock --check
  mkdir wheels
  uv export --frozen --no-dev --no-emit-project --no-hashes -o "$src/runtime.txt" --format requirements-txt
  python3.12 -m pip wheel --no-deps -r "$src/runtime.txt" -w wheels
  uv build --wheel --out-dir wheels .
  (cd wheels && sha256sum *.whl > SHA256SUMS)
  cd "$src"
  tag="autoeval/platform-backend:${rev:0:12}-$(uname -m)"
  docker build --label "org.opencontainers.image.revision=$rev" -t "$tag" -f deploy/intranet/backend.offline.Dockerfile .
  docker run --rm "$tag" alembic heads
  docker image inspect -f '{{.Id}}' "$tag" > "$REL/image-id"
  docker save "$tag" | gzip -1 > "$REL/platform.tar.gz"
  echo "$rev" > "$REL/source-revision"
  (cd "$REL" && sha256sum image-id source-revision platform.tar.gz frontend-dist.tar.gz > SHA256SUMS && sha256sum SHA256SUMS)
  ;;
check|apply)
  cd "$REL"
  : "${SUMS_SHA256:?trusted digest of SHA256SUMS required}" "${API_CONTAINER:?existing API container required}"
  echo "$SUMS_SHA256  SHA256SUMS" | sha256sum -c -
  sha256sum -c SHA256SUMS
  test "$(cat source-revision)" = "$rev" || die "Release revision mismatch"
  image=$(cat image-id)
  docker load -i platform.tar.gz
  test "$(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")" = "$rev"
  case "$(uname -m)" in x86_64) arch=amd64;; aarch64|arm64) arch=arm64;; *) die "Unsupported architecture";; esac
  test "$(docker image inspect -f '{{.Os}}/{{.Architecture}}' "$image")" = "linux/$arch"
  label() { docker inspect -f "{{index .Config.Labels \"com.docker.compose.$1\"}}" "$API_CONTAINER"; }
  project=$(label project); wd=$(label project.working_dir); files=$(label project.config_files)
  test "$(label service)" = api && test -n "$project" && test -d "$wd" || die "Verify API Compose labels"
  exec 9>"$wd/.platform-update.lock"
  flock -n 9 || die "Another platform update is active"
  old=(docker compose --project-directory "$wd" -p "$project")
  IFS=, read -ra paths <<< "$files"
  override="$REL/platform.override.json"
  for f in "${paths[@]}"; do test -r "$f"; if [[ $f != "$override" ]]; then old+=(-f "$f"); fi; done
  oldimage=$(docker inspect -f '{{.Image}}' "$API_CONTAINER")
  apps=(api dispatcher workflow planning planning-execution monitored result reconciler)
  # Include active optional roles that run the same backend image.
  for id in $(docker ps -q --filter "label=com.docker.compose.project=$project"); do
    s=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.service"}}' "$id")
    if [[ $(docker inspect -f '{{.Image}}' "$id") = "$oldimage" && " ${apps[*]} " != *" $s "* ]]; then apps+=("$s"); fi
  done
  for s in ${EXTRA_SERVICES:-}; do apps+=("$s"); done
  services=$("${old[@]}" config --services)
  for s in "${apps[@]}" gateway postgres; do grep -Fxq "$s" <<< "$services" || die "Missing service $s"; done
  assets=$(mktemp -d "$REL/web.XXXXXXXX")
  tar xzf frontend-dist.tar.gz -C "$assets"
  test -s "$assets/dist/index.html"
  chmod -R a+rX "$assets/dist"
  python3 - "$override.next" "$image" "$assets/dist" "${apps[@]}" <<'PY'
import json, sys
from pathlib import Path
out, image, dist, *apps = sys.argv[1:]
services = {s: {"image": image} for s in apps}
services["gateway"] = {"volumes": [f"{dist}:/usr/share/nginx/html:ro"]}
Path(out).write_text(json.dumps({"services": services}))
PY
  new=("${old[@]}" -f "$override.next")
  "${new[@]}" config --quiet
  "${new[@]}" run --rm --no-deps gateway nginx -t
  run=("${new[@]}" run --rm -T --no-deps api)
  head=$("${run[@]}" alembic heads)
  [[ $head =~ ^([[:alnum:]_]+)' (head)'$ ]] || die "Expected exactly one migration head: $head"
  target=${BASH_REMATCH[1]}
  "${run[@]}" alembic current
  printf 'Target %s, migration %s, services %s\n' "$rev" "$target" "${apps[*]}"
  [[ $1 = apply ]] || exit 0
  : "${BACKUP_DIR:?new absolute backup directory required}"
  [[ $BACKUP_DIR = /* ]] || die "Use an absolute backup directory"
  mkdir -m 700 "$BACKUP_DIR"
  "${old[@]}" stop gateway "${apps[@]}"
  "${old[@]}" exec -T postgres pg_dump -U "${DB_USER:-autoeval}" -d "${DB_NAME:-autoeval}" -Fc > "$BACKUP_DIR/business.dump"
  "${old[@]}" exec -T postgres pg_restore -l < "$BACKUP_DIR/business.dump" > "$BACKUP_DIR/contents.txt"
  grep -q 'TABLE DATA' "$BACKUP_DIR/contents.txt"
  (cd "$BACKUP_DIR" && sha256sum business.dump > SHA256SUMS)
  "${run[@]}" alembic upgrade head
  current=$("${run[@]}" alembic current)
  grep -Fxq "$target (head)" <<< "$current"
  mv "$override.next" "$override"
  new=("${old[@]}" -f "$override")
  "${new[@]}" up -d --wait --wait-timeout 180 --no-deps --pull never --force-recreate "${apps[@]}"
  for s in "${apps[@]}"; do
    ids=$("${new[@]}" ps -q "$s"); test -n "$ids"
    for id in $ids; do test "$(docker inspect -f '{{.Image}}' "$id")" = "$image"; done
  done
  "${new[@]}" up -d --wait --no-deps --pull never --force-recreate gateway
  echo "Service management override: $override"
  ;;
*) die "Usage: bash update-platform.sh build|check|apply";;
esac
