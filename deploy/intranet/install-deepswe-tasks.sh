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

# Compare Git blob contents before copying. A CRLF checkout changes both the
# Linux verifier entrypoint and the embedded patch even when directory diff passes.
(
    cd "$source_dir/abs-module-cache-flags/tests"
    sha256sum -c - <<'CHECKSUMS'
dfecfd863824f3d9780fb1bdb13de5415d831a7c452a41f39202dd29e4454b81  test.sh
1f14443b836ad75b66975d9c8b6e735f675250136661dfc0a370d018ba4a97f9  test.patch
CHECKSUMS
)

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
