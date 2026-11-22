#!/bin/sh
set -eu

helper="$(dirname "$0")/autoeval-rootless-docker"
probe=autoeval/harbor-kernel-probe:alpine-3.23.4
sidecar=harbor-prebuilt:harbor-docker-egress-control-sidecar--b67f71411fe7d8f5

if [ "$#" -ne 2 ]; then
    exit 2
fi
if [ "$1" != ensure ]; then
    exec "$helper" "$@"
fi

socket=$("$helper" "$@")
seed_image() {
    image=$1
    expected=$2
    [ "$(docker image inspect --format '{{.Id}}' "$image")" = "$expected" ] || return 1
    installed=$(docker --host "unix://$socket" image inspect --format '{{.Id}}' "$image" 2>/dev/null || true)
    if [ "$installed" != "$expected" ]; then
        docker save "$image" | docker --host "unix://$socket" load >&2
        [ "$(docker --host "unix://$socket" image inspect --format '{{.Id}}' "$image")" = "$expected" ]
    fi
}

if ! (set -e
    seed_image "$probe" sha256:3cb067eab609612d81b4d82ff8ad71d73482bb3059a87b642d7e14f0ed659cde || exit 1
    seed_image "$sidecar" sha256:68ad0b68479ee4857f60e2998046a3aa59eaf8db3a57f90ce7f5bd0a6f7aeab6 || exit 1
); then
    "$helper" remove "$2" >&2
    exit 1
fi
printf '%s\n' "$socket"
