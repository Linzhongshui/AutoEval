#!/bin/sh
# Mount ahead of the runner's Docker CLI together with its pinned offline base archive.
set -eu
cli=/usr/local/bin/docker
tag=harbor-automationbench:e45f2f2ac0d7e2215205fa44
expected=sha256:086c2b1898ad38faa5420a29046e8430c285e2fae35bdea3977b5fc5b6afa779

load_pinned_image() {
    [ "${DOCKER_HOST:-}" = unix:///tmp/autoeval-docker.sock ] || return 1
    if [ "$("$cli" image inspect --format '{{.Id}}' "$1" 2>/dev/null || true)" != "$2" ]; then
        "$cli" load --input "$3" >&2
        [ "$("$cli" image inspect --format '{{.Id}}' "$1")" = "$2" ]
    fi
}

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
    load_pinned_image "$tag" "$expected" /opt/autoeval-cache/automationbench-base.tar
}

deepswe=public.ecr.aws/d3j8x8q7/swe-bench-202605:kh75679ajj3b8dtd7se3h7z0a1833y6r-v1.1
archive=/opt/autoeval-cache/deepswe-85f743fa1c3b.tar
if [ "${1:-}" = inspect ] && [ "${2:-}" = --format ] && [ "${3:-}" = '{{.Os}}' ] \
    && [ "${4:-}" = "$deepswe" ] && [ -r "$archive" ]; then
    load_pinned_image "$deepswe" sha256:85f743fa1c3b772abbac100056350657e771a10196c31512f68fc4dc114c19cd "$archive"
elif [ "${1:-}" = compose ]; then
    prepare_base "$@"
fi
exec "$cli" "$@"
