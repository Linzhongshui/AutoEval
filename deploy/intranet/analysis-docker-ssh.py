#!/usr/local/bin/python
"""Narrow Docker CLI bridge for a separately registered analysis executor over SSH.

The protected analysis-executor.json supplies container_id and ssh_resource_id.
Only the pinned resource's registered host, fingerprint and credential are used.
"""

import asyncio
import json
import shlex
import sys
import uuid

from autoeval.config import get_settings
from autoeval.db import create_database
from autoeval.ssh_executor import SSHExecutor
from autoeval.ssh_resources import SSHResourceBinding, connection_for


async def connection(settings, identifier):
    engine, sessions = create_database(settings)
    try:
        async with sessions() as session:
            resource = await session.get(SSHResourceBinding, uuid.UUID(identifier))
            if resource is None:
                raise ValueError("Pinned analysis SSH resource missing")
            return connection_for(resource, settings)
    finally:
        await engine.dispose()


def main():
    settings = get_settings()
    binding = json.loads((settings.secret_store_path / "analysis-executor.json").read_text())
    container = binding["container_id"]
    args = sys.argv[1:]
    allowed = args == ["inspect", "--type", "container", container] or args == [
        "exec",
        "-i",
        container,
        "python",
        "-m",
        "autoeval.analysis_runtime",
    ]
    if not allowed:
        raise SystemExit(2)
    control = SSHExecutor(asyncio.run(connection(settings, binding["ssh_resource_id"])))
    with control.connect() as client:
        stdin, stdout, stderr = client.exec_command(shlex.join(["docker", *args]), timeout=185)
        if args[0] == "exec":
            stdin.write(sys.stdin.buffer.read(16 * 1024 * 1024 + 1))
        stdin.channel.shutdown_write()
        sys.stdout.buffer.write(stdout.read())
        sys.stderr.buffer.write(stderr.read())
        raise SystemExit(stdout.channel.recv_exit_status())


if __name__ == "__main__":
    main()
