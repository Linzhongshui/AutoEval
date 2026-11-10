"""Local development SecretStore. Not a production vault or encryption service."""

import os
import re
import uuid
from pathlib import Path


class FileSecretStore:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def put(self, secret: str) -> str:
        if not secret or len(secret) > 65536 or "\n" in secret or "\r" in secret:
            raise ValueError("Invalid secret")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        reference = uuid.uuid4().hex
        path = self.root / reference
        # Exclusive creation; no user-supplied filename or overwrite.
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(secret)
        return reference

    def get(self, reference: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{32}", reference):
            raise ValueError("Invalid credential reference")
        path = self.root / reference
        if path.is_symlink() or path.resolve().parent != self.root:
            raise ValueError("Credential reference escapes secret root")
        return path.read_text(encoding="utf-8")
