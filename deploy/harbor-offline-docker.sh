#!/bin/sh
# Mount ahead of the runner's Docker CLI together with its pinned offline base archive.
set -eu
cli=/usr/local/bin/docker
tag=harbor-automationbench:e45f2f2ac0d7e2215205fa44
expected=sha256:086c2b1898ad38faa5420a29046e8430c285e2fae35bdea3977b5fc5b6afa779

prepare_base() {
    shift
    project_dir=
    build=false
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --project-directory) shift; project_dir=$1 ;;
            build) build=true ;;
        esac
        shift
    done
    [ "$build" = true ] && [ -r "$project_dir/Dockerfile" ] || return 0
    awk -v tag="$tag" 'toupper($1)=="FROM" && $2==tag {found=1} END{exit !found}' "$project_dir/Dockerfile" || return 0
    [ "${DOCKER_HOST:-}" = unix:///tmp/autoeval-docker.sock ] || return 1
    if [ "$("$cli" image inspect --format '{{.Id}}' "$tag" 2>/dev/null || true)" != "$expected" ]; then
        "$cli" load --input /opt/autoeval-cache/automationbench-base.tar >&2
        [ "$("$cli" image inspect --format '{{.Id}}' "$tag")" = "$expected" ]
    fi
}

if [ "${1:-}" = compose ]; then
    prepare_base "$@"
fi
exec "$cli" "$@"
