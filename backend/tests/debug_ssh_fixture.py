"""Loopback SSH test endpoint. Only Docker inspect/exec on this test's container."""

import base64
import hashlib
import secrets
import shlex
import socketserver
import subprocess
import threading
import uuid
from contextlib import contextmanager

import paramiko

from autoeval.resources.ssh_executor import SSHConnection


@contextmanager
def docker_ssh_fixture(allowed):
    password = secrets.token_urlsafe()
    host_key = paramiko.RSAKey.generate(2048)

    class Interface(paramiko.ServerInterface):
        def __init__(self):
            self.ready = threading.Event()

        def check_auth_password(self, username, candidate):
            if username == "fixture" and secrets.compare_digest(candidate, password):
                return paramiko.AUTH_SUCCESSFUL
            return paramiko.AUTH_FAILED

        def check_channel_request(self, kind, chanid):
            return (
                paramiko.OPEN_SUCCEEDED
                if kind == "session"
                else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
            )

        def check_channel_exec_request(self, channel, command):
            args = shlex.split(command.decode())
            if args[:2] == ["docker", "inspect"]:
                ok = args[2:-1] in ([], ["--type", "container"]) and args[-1] in allowed
            elif args[:2] == ["docker", "exec"]:
                offset = 3 if args[2:3] == ["-i"] else 2
                ok = args[offset] in allowed
            else:
                ok = False
            if ok:
                self.args = args
                self.ready.set()
            return ok

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            with paramiko.Transport(self.request) as wire:
                wire.add_server_key(host_key)
                session = Interface()
                wire.start_server(server=session)
                channel = wire.accept(10)
                if channel is None or not session.ready.wait(10):
                    return
                with channel:
                    result = subprocess.run(
                        session.args,
                        input=channel.makefile("rb").read(),
                        capture_output=True,
                        timeout=30,
                        check=False,
                    )
                    channel.sendall(result.stdout)
                    channel.sendall_stderr(result.stderr)
                    channel.send_exit_status(result.returncode)
                    channel.shutdown_write()

    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            digest = hashlib.sha256(host_key.asbytes()).digest()
            yield SSHConnection(
                host="127.0.0.1",
                port=server.server_address[1],
                username="fixture",
                workdir="/tmp/fixture",
                owner_id=uuid.uuid4(),
                credential=password,
                auth_kind="password",
                fingerprint="SHA256:" + base64.b64encode(digest).decode().rstrip("="),
            )
        finally:
            server.shutdown()
            thread.join()
