"""Persistent native requests on a pinned SSH host; disconnects never imply retry."""

import asyncio
import hashlib
import json
import re
import stat
import uuid
from pathlib import Path

from autoeval.ssh_executor import SSHConnection, SSHExecutor


class SSHNativeTransport:
    def __init__(
        self, connection: SSHConnection, tool_root: str, bridge_sha256: str, lock_sha256: str
    ):
        self.control = SSHExecutor(connection)
        self.root = self.control.root
        # Apply the same canonical directory rules as the owned execution root.
        SSHConnection.absolute_directory(tool_root)
        if not re.fullmatch(r"[0-9a-f]{64}", bridge_sha256):
            raise ValueError("Approved native bridge checksum required")
        if not re.fullmatch(r"[0-9a-f]{64}", lock_sha256):
            raise ValueError("Approved source lock checksum required")
        self.lock_sha256 = lock_sha256
        self.tool_root, self.bridge_sha256 = tool_root, bridge_sha256
        self.runtime = Path(__file__).with_name("native_request_runtime.py")
        self.digest = hashlib.sha256(self.runtime.read_bytes()).hexdigest()
        self.remote_runtime = f"{self.root}/runtime/{self.digest}.py"
        self.control.runtime = self.runtime
        self.control.digest = self.digest
        self.control.remote_runtime = self.remote_runtime

    def _native_command(self, action, key):
        return [
            "env",
            f"AE_NATIVE_JOB_ROOT={self.root}/jobs",
            f"AE_NATIVE_TOOL_ROOT={self.tool_root}",
            f"AE_NATIVE_BRIDGE_SHA256={self.bridge_sha256}",
            f"AE_NATIVE_LOCK_SHA256={self.lock_sha256}",
            "python3",
            self.remote_runtime,
            action,
            str(uuid.UUID(key)),
        ]

    def native_operation(self, action, key, payload=None):
        with self.control.connect() as client:
            self.control.prepare(client)
            raw = self.control.command(
                client,
                self._native_command(action, key),
                json.dumps(payload).encode() if payload is not None else None,
            )
            return json.loads(raw)

    async def submit_request(self, payload, submission_key):
        if payload.get("operation") != "infer_gpqa_smoke":
            raise ValueError("Native operation is not enabled")
        return await asyncio.to_thread(self.native_operation, "submit", submission_key, payload)

    async def lookup_request(self, submission_key):
        return await asyncio.to_thread(self.native_operation, "status", submission_key)

    def request_digest(self, payload):
        safe = {k: v for k, v in payload.items() if k != "api_key"}
        safe.update(
            tool_root=self.tool_root, bridge_sha256=self.bridge_sha256, lock_sha256=self.lock_sha256
        )
        return hashlib.sha256(json.dumps(safe, sort_keys=True).encode()).hexdigest()

    async def collect_request(self, submission_key, expected_payload=None):
        # Independently retrieve the durable bytes over SFTP, then check the
        # terminal marker checksum. No inference is invoked while collecting.
        def collect():
            with self.control.connect() as client:
                self.control.prepare(client)
                observed = json.loads(
                    self.control.command(client, self._native_command("status", submission_key))
                )
                if observed["state"] != "succeeded":
                    return observed
                if expected_payload is not None and observed.get(
                    "request_sha256"
                ) != self.request_digest(expected_payload):
                    raise ValueError("Native result belongs to a different request")
                path = f"{self.root}/jobs/{uuid.UUID(submission_key)}/result.json"
                with client.open_sftp() as sftp:
                    sftp.get_channel().settimeout(15)
                    if not stat.S_ISREG(sftp.lstat(path).st_mode):
                        raise ValueError("Invalid native evidence file")
                    with sftp.open(path, "rb") as stream:
                        raw = stream.read(16 * 1024 * 1024 + 1)
                if (
                    len(raw) > 16 * 1024 * 1024
                    or hashlib.sha256(raw).hexdigest() != observed["result_sha256"]
                ):
                    raise ValueError("Native evidence checksum mismatch")
                return {**observed, "result": json.loads(raw)}

        return await asyncio.to_thread(collect)

    async def request(self, payload, submission_key):
        await self.submit_request(payload, submission_key)
        for _ in range(240):
            observed = await self.lookup_request(submission_key)
            if observed["state"] == "succeeded":
                return (await self.collect_request(submission_key, payload))["result"]
            if observed["state"] != "running":
                raise RuntimeError(
                    "Native request outcome is unconfirmed; lookup instead of resubmission"
                )
            await asyncio.sleep(0.5)
        raise TimeoutError("Native request still requires reconciliation")
