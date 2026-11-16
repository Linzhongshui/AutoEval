"""Create a standard-input bundle from an offline checkout without executing its code."""

import argparse
import json
from pathlib import Path

from autoeval.standard_inputs import BENCHMARKS, FILES, Bundle, digest, discover


def read_directory(root: Path, revision: str):
    root = root.resolve(strict=True)
    files = {}
    for model in sorted(root.iterdir()):
        if not model.is_dir() or model.is_symlink() or model.name.startswith("."):
            continue
        for benchmark in BENCHMARKS:
            for filename in sorted(FILES):
                path = model / benchmark / filename
                if not path.exists():
                    continue
                if path.is_symlink() or not path.resolve().is_relative_to(root):
                    raise ValueError("Source symlinks are not supported")
                if path.stat().st_size > 2_000_000:
                    raise ValueError("File too large")
                files[path.relative_to(root).as_posix()] = path.read_bytes().decode("utf-8")
    bundle = Bundle(revision=revision, files=files)
    discover(bundle)
    return bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    bundle = read_directory(args.directory, args.revision)
    args.output.write_text(
        json.dumps(bundle.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"sha256": digest(bundle.model_dump()), "files": len(bundle.files)}))


if __name__ == "__main__":
    main()
