"""Standalone POSIX reader for a single executor mount. Inputs arrive on stdin."""

import codecs
import errno
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import uuid
from contextlib import ExitStack
from pathlib import Path

ROOT = "/var/lib/autoeval/artifacts"
MARKER = ".autoeval-storage-id"
OUTPUT_ROOTS = ("output", "outputs")
PUBLIC = {
    *OUTPUT_ROOTS,
    "sample-dispatch",
    "tool.log",
    "output.log",
    "result.json",
    "progress.json",
}
LIMIT = 64 * 1024
PROTECTED = re.compile(
    r"credential|private[-_]?(?:config|key)|secret|password|\.pem$|\.key$|^config(?:\.|$)",
    re.IGNORECASE,
)
AUTH = re.compile(
    r"""(?i)(["']?(?:api[-_]?key|access[-_]?token|password|authorization|secret|token)["']?\s*[:=]\s*)(?:(?:Bearer|Basic)\s+)?(?:"[^"\n]*"|'[^'\n]*'|[^,\s}]+)"""
)


def storage_id(root, initialize):
    path = Path(root)
    if path.is_symlink() or path.resolve() != path:
        raise ValueError("Unsafe mount")
    if initialize:
        # Linking a fully written candidate is atomic across competing preflights.
        with tempfile.NamedTemporaryFile(dir=root) as f:
            f.write(str(uuid.uuid4()).encode())
            f.flush()
            try:
                os.link(f.name, path / MARKER)
            except FileExistsError:
                pass
    fd = os.open(path / MARKER, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("Invalid mount marker")
        return str(uuid.UUID(f.read(37).decode()))


def permitted(name):
    return (
        name
        and not name.startswith(".")
        and not PROTECTED.search(name)
        and not any(ord(c) < 32 or c in "/\\" for c in name)
    )


def text_preview(content, start, end, size):
    if "PRIVATE KEY-----" in content:
        return {"state": "protected"}
    content = AUTH.sub(r"\1[REDACTED]", content)
    content = re.sub(r"(?i)\b(Bearer|Basic)\s+[-A-Za-z0-9._~+/=]+", r"\1 [REDACTED]", content)
    return {"state": "text", "content": content, "start": start, "end": end, "size": size}


def masked_slice(raw, start, end, fingerprint):
    """Mask literal credentials even across a preview boundary or after key rotation."""
    length = fingerprint["length"]
    visible = []
    cursor = start
    prefix = min(length, 32)
    for pos in range(max(0, start - length + 1), min(end, len(raw) - length + 1)):
        if pos + length <= cursor:
            continue
        if hashlib.sha256(raw[pos : pos + prefix]).hexdigest() != fingerprint["prefix"]:
            continue
        if hashlib.sha256(raw[pos : pos + length]).hexdigest() == fingerprint["digest"]:
            visible.extend([raw[cursor : max(pos, cursor)], b"[REDACTED]"])
            cursor = min(end, pos + length)
    visible.append(raw[cursor:end])
    return b"".join(visible)


def output_files(job, offset, fingerprint):
    """List leaf entries under the tool work directories without following links."""
    entries = []
    seen = 0

    def scan_error(error):
        if error.errno not in {errno.ENOENT, errno.ENOTDIR}:
            raise error

    def walk_output(root):
        try:
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=job)
        except (FileNotFoundError, NotADirectoryError):
            return
        try:
            yield from os.fwalk(".", dir_fd=fd, follow_symlinks=False, onerror=scan_error)
        finally:
            os.close(fd)

    for root in OUTPUT_ROOTS:
        for directory, dirs, files, parent in walk_output(root):
            dirs.sort()
            # fwalk also categorizes links to directories as directories. List the
            # link itself, without descending into the target.
            for name in sorted(files + dirs):
                try:
                    meta = os.stat(name, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if stat.S_ISDIR(meta.st_mode):
                    continue
                if seen < offset:
                    seen += 1
                    continue
                if len(entries) == 100:
                    return {"state": "directory", "entries": entries, "more": True}
                path = os.path.normpath(os.path.join(root, directory, name))
                raw = os.fsencode(path)
                safe = masked_slice(raw, 0, len(raw), fingerprint)
                display = safe.decode("utf-8", errors="backslashreplace")
                display = "".join(c if c.isprintable() else ascii(c)[1:-1] for c in display)
                entries.append(
                    {
                        "name": display,
                        "directory": False,
                        "size": meta.st_size,
                        "mtime": meta.st_mtime,
                        "metadata_only": (
                            safe != raw
                            or display != path
                            or len(path) > 2048
                            or not stat.S_ISREG(meta.st_mode)
                            or meta.st_nlink != 1
                            or not all(permitted(part) for part in path.split("/"))
                        ),
                    }
                )
    return {"state": "directory", "entries": entries, "more": False}


def browse(root, request):
    try:
        actual = storage_id(root, False)
    except (FileNotFoundError, ValueError):
        return {"state": "wrong_storage"}
    if actual != request["store"]:
        return {"state": "wrong_storage"}
    parts = request["path"].split("/") if request["path"] else []
    if (parts and parts[0] not in PUBLIC) or any(not permitted(p) for p in parts):
        return {"state": "forbidden"}
    key = str(uuid.UUID(request["job"]))
    with ExitStack() as stack:

        def opened(path, parent=None, directory=False):
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            fd = os.open(path, flags | (os.O_DIRECTORY if directory else 0), dir_fd=parent)
            stack.callback(os.close, fd)
            return fd

        parent = opened(root, directory=True)
        try:
            job = opened(key, parent, directory=True)
        except FileNotFoundError:
            return {
                "state": "removed" if (Path(root) / (".submitted-" + key)).is_file() else "pending"
            }
        try:
            fingerprint = json.loads(os.read(opened(".redaction.json", job), 1024))
            if not 1 <= fingerprint["length"] <= 4 * 65536:
                return {"state": "protected"}
        except FileNotFoundError:
            return {"state": "pending"}
        if request.get("view") == "outputs":
            return output_files(job, request.get("offset", 0), fingerprint)
        fd = job
        for i, name in enumerate(parts):
            fd = opened(name, fd, directory=i < len(parts) - 1)
        info = os.fstat(fd)
        if stat.S_ISDIR(info.st_mode):
            entries = []
            with os.scandir(fd) as items:
                for item in items:
                    if not permitted(item.name) or (not parts and item.name not in PUBLIC):
                        continue
                    try:
                        meta = item.stat(follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    directory = stat.S_ISDIR(meta.st_mode)
                    if not directory and not (stat.S_ISREG(meta.st_mode) and meta.st_nlink == 1):
                        continue
                    filename = os.fsencode(item.name)
                    if masked_slice(filename, 0, len(filename), fingerprint) != filename:
                        continue
                    entries.append(
                        {
                            "name": item.name,
                            "directory": directory,
                            "size": meta.st_size,
                            "mtime": meta.st_mtime,
                        }
                    )
            entries.sort(key=lambda e: (not e["directory"], e["name"]))
            start = request.get("offset", 0)
            return {
                "state": "directory",
                "entries": entries[start : start + 100],
                "more": len(entries) > start + 100,
            }
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            return {"state": "forbidden"}
        tail = parts[-1].lower().endswith(".log")
        start = max(0, info.st_size - LIMIT) if tail else 0
        end = min(start + LIMIT, info.st_size)
        overlap = fingerprint["length"] - 1
        read_from = max(0, start - overlap)
        os.lseek(fd, read_from, os.SEEK_SET)
        raw = os.read(fd, end - read_from + overlap)
        end = min(end, read_from + len(raw))
        if end < start:
            return {"state": "missing_file"}
        # For logs, start at a complete line when one fits in the preview.
        if start:
            newline = raw.find(b"\n", start - read_from, end - read_from)
            if newline != -1:
                start = read_from + newline + 1
        visible = masked_slice(raw, start - read_from, end - read_from, fingerprint)
        if any(byte < 32 and byte not in b"\t\r\n" for byte in visible):
            return {"state": "binary", "size": info.st_size}
        # An arbitrarily named native output can be plain text. Decode only the
        # preview, allowing an incomplete UTF-8 character at a truncated boundary.
        if start:
            for _ in range(3):
                if not visible or not 0x80 <= visible[0] <= 0xBF:
                    break
                visible = visible[1:]
                start += 1
        try:
            decoder = codecs.getincrementaldecoder("utf-8")()
            content = decoder.decode(visible, final=end == info.st_size)
            end -= len(decoder.getstate()[0])
        except UnicodeError:
            return {"state": "binary", "size": info.st_size}
        return text_preview(content, start, end, info.st_size)


if __name__ == "__main__":
    request = json.load(sys.stdin)
    try:
        if request.get("initialize") or request.get("verify"):
            result = {"store": storage_id(ROOT, bool(request.get("initialize")))}
        else:
            result = browse(ROOT, request)
    except FileNotFoundError:
        result = {"state": "missing_file"}
    except OSError as exc:
        state = (
            "forbidden"
            if exc.errno in (errno.ELOOP, errno.ENOTDIR, errno.EACCES)
            else "unavailable"
        )
        result = {"state": state}
    except (ValueError, KeyError, TypeError):
        result = {"state": "unavailable"}
    print(json.dumps(result))
