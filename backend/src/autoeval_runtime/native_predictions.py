"""Bounded observations of this job's native predictions, never score inference."""

import hashlib
import json
from pathlib import Path


def records(content):
    decoder = json.JSONDecoder(strict=False)
    offset = 0
    while offset < len(content):
        while offset < len(content) and content[offset].isspace():
            offset += 1
        if offset == len(content):
            return
        try:
            value, offset = decoder.raw_decode(content, offset)
        except ValueError:
            return  # The writer may still be appending its final record.
        if isinstance(value, dict) and "data_abbr" in value:
            yield value
        elif isinstance(value, dict):
            yield from (v for v in value.values() if isinstance(v, dict))
        elif isinstance(value, list):
            yield from (v for v in value if isinstance(v, dict))


def collect(output, contract):
    root = Path(output).resolve()
    files = []
    budget = 12 * 1024 * 1024
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if (
            path.suffix not in {".jsonl", ".json"}
            or "predictions" not in relative.parts
            or contract["model_abbr"] not in relative.parts
        ):
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("Unsafe native prediction path")
        if not path.is_file():
            continue
        raw = path.read_bytes()
        budget -= len(raw)
        if budget < 0:
            raise ValueError("Native prediction evidence exceeds budget")
        files.append(
            {
                "path": str(relative.as_posix()),
                "content": raw.decode("utf-8"),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return files


def selected(files, contract):
    allowed = set(contract["case_ids"])
    found = {}
    for file in files:
        if hashlib.sha256(file["content"].encode()).hexdigest() != file["sha256"]:
            raise ValueError("Native prediction checksum mismatch")
        for row in records(file["content"]):
            key = str(row.get("id"))
            mapping = contract.get("slice_index_to_tool_id")
            if mapping is not None:
                key = mapping.get(key)
            if row.get("data_abbr") != contract["dataset_abbr"] or key not in allowed:
                continue
            if type(row.get("success")) is not bool or (
                not isinstance(row.get("prediction"), str) and row.get("success") is not False
            ):
                continue
            previous = found.get(key)
            if previous and any(
                previous[0].get(k) != row.get(k) for k in ("uuid", "prediction", "success")
            ):
                raise ValueError("Conflicting native predictions for one case")
            found[key] = (row, file)
    return found
