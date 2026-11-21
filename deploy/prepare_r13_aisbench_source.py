"""Prepare a disposable AISBench checkout against the exact recorded file hashes."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

LOCK = Path(__file__).resolve().parents[1] / "backend" / "tool-locks" / "aisbench.json"


def prepare(checkout: Path) -> tuple[int, int]:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    revision = subprocess.check_output(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != lock["revision"]:
        raise ValueError("AISBench checkout does not match the locked revision")

    updates = []
    for name, expected in lock["files"].items():
        path = checkout / name
        if not path.is_file() or not path.resolve().is_relative_to(checkout):
            raise ValueError(f"Missing or invalid locked file: {name}")
        if any(parent.is_symlink() for parent in (path, *path.parents) if parent != checkout):
            raise ValueError(f"Symlink in locked path: {name}")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() == expected:
            continue
        crlf = raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        if hashlib.sha256(crlf).hexdigest() != expected:
            raise ValueError(f"Unexpected content in locked file: {name}")
        updates.append((path, crlf))

    for path, value in updates:
        path.write_bytes(value)
    return len(lock["files"]), len(updates)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path, help="Disposable checkout of the locked commit")
    args = parser.parse_args()
    checked, changed = prepare(args.checkout.resolve(strict=True))
    print(f"Verified {checked} AISBench files; reconstructed {changed} exact CRLF files.")
