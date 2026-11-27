#!/usr/bin/env bash
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd -P)
manifest="$here/release.json"
read_field() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$manifest" "$1"; }
tag=$(read_field tag)
id=$(read_field image_id)
sha=$(read_field sha256)
archive=${ARCHIVE:-"$PWD/deepswe-e968d1b-issue38.tar.gz"}
engine=$(docker info --format '{{.OSType}}/{{.Architecture}}')
case "$engine" in linux/x86_64|linux/amd64) ;; *) echo "Expected Linux AMD64 execution engine; found $engine" >&2; exit 1;; esac
if [[ ! -f "$archive" ]]; then
    tmp=$(mktemp -d "$(dirname "$archive")/.deepswe.XXXXXXXX")
    trap 'rm -f "$tmp/image"; rmdir "$tmp"' EXIT
    obsutil cp "$(read_field uri)" "$tmp/image"
    printf '%s  %s\n' "$sha" "$tmp/image" | sha256sum -c -
    mv "$tmp/image" "$archive"
fi
printf '%s  %s\n' "$sha" "$archive" | sha256sum -c -
old=$(docker image inspect -f '{{.Id}}' "$tag" 2>/dev/null || true)
[[ -z $old || $old = "$id" ]] || { echo "Release tag already points to another image" >&2; exit 1; }
docker load -i "$archive"
test "$(docker image inspect -f '{{.Id}} {{.Os}}/{{.Architecture}}' "$tag")" = "$id linux/amd64"
printf 'Verified DeepSWE image_id=%s\n' "$id"
