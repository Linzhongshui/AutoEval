"""Render release-local Compose files using the image IDs in a verified offline bundle."""
import argparse
import json
import re
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def render(release, uid, gid, roles):
    images = read(release / "images.json")
    for name in ("python", "nginx", "postgres", "storage", "temporal", "backend"):
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", images[name]):
            raise ValueError(f"Invalid Docker image ID for {name}")

    base = read(release / "compose.json")
    workers = read(release / "compose.workers.json")
    services = base["services"]
    for service, image in {
        "gateway": "nginx", "postgres": "postgres", "temporal-db": "postgres",
        "temporal": "temporal", "storage": "storage", "network-anchor": "python",
    }.items():
        services[service]["image"] = images[image]

    for role in roles:
        workers["services"][role] = {
            **workers["services"]["workflow"],
            "command": ["python", "-m", "autoeval.entrypoints.worker", role],
        }
    for spec in [services["api"], *workers["services"].values()]:
        spec["image"] = images["backend"]
        spec["user"] = f"{uid}:{gid}"
    services["network-anchor"]["user"] = f"{uid}:{gid}"

    outputs = {"release.json": base, "workers.json": workers}
    for filename, spec in outputs.items():
        target = release / filename
        if target.exists() and read(target) != spec:
            raise ValueError(f"Conflicting {target}; use a new release directory")
    for filename, spec in outputs.items():
        target = release / filename
        if not target.exists():
            with target.open("x", encoding="utf-8") as stream:
                json.dump(spec, stream, indent=2)
                stream.write("\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", type=Path)
    parser.add_argument("--uid", required=True, type=int)
    parser.add_argument("--gid", required=True, type=int)
    parser.add_argument("--role", action="append", choices=["result", "langfuse", "io", "gpqa"],
                        default=[])
    args = parser.parse_args()
    render(args.release, args.uid, args.gid, args.role)
