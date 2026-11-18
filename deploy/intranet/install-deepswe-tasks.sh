#!/bin/sh
set -eu

if [ "$#" -ne 2 ]; then
    echo "Usage: sh install-deepswe-tasks.sh TASKS_DIRECTORY HARBOR_CONTAINER" >&2
    exit 2
fi

source_dir=$(cd "$1" && pwd -P)
container=$2
target=/data/deep-swe/tasks

test "$(find "$source_dir" -mindepth 1 -maxdepth 1 -type d | wc -l)" -eq 113
test -f "$source_dir/abs-module-cache-flags/task.toml"

if docker exec "$container" test -e "$target"; then
    echo "Task directory already exists. Verifying against the supplied source."
else
    docker exec "$container" mkdir -p /data/deep-swe
    docker cp "$source_dir" "$container:$target"
fi

scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
docker cp "$container:$target" "$scratch/tasks"
diff -qr --no-dereference "$source_dir" "$scratch/tasks"
echo "Verified 113 DeepSWE tasks in $container:$target"
