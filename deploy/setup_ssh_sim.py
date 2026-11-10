"""Configure only a labeled local OpenSSH simulator. Never enrolls customer hosts."""

import base64
import hashlib
import io
import json
import subprocess

import paramiko

from autoeval.config import get_settings
from autoeval.secrets import FileSecretStore
from autoeval.ssh_executor import load_private_key


def main():
    settings = get_settings()
    executable = settings.docker_executable
    container = "autoeval-ssh-sim"

    def docker(*arguments, payload=None):
        return subprocess.run(
            [executable, *arguments], input=payload, capture_output=True, check=True, timeout=20
        ).stdout

    metadata = json.loads(docker("inspect", container))[0]
    if metadata.get("Config", {}).get("Labels", {}).get("autoeval.role") != "ssh-simulator":
        raise ValueError("Not an AutoEval local SSH simulator")
    store = FileSecretStore(settings.secret_store_path)
    config_path = settings.secret_store_path / "ssh-simulator.json"
    if config_path.exists():
        previous = json.loads(config_path.read_text())
        reference = previous["credential_ref"]
        key = load_private_key(store.get(reference))
    else:
        key = paramiko.RSAKey.generate(3072)
        stream = io.StringIO()
        key.write_private_key(stream)
        reference = store.put(stream.getvalue(), allow_multiline=True)
    docker(
        "exec",
        container,
        "sh",
        "-c",
        "id -u autoeval >/dev/null 2>&1 || useradd -m -d /work -s /bin/sh autoeval",
    )
    docker("exec", container, "usermod", "-p", "*", "autoeval")
    script = """from pathlib import Path
import sys,os,pwd
p=Path('/work/.ssh');p.mkdir(parents=True,exist_ok=True,mode=0o700)
(p/'authorized_keys').write_bytes(sys.stdin.buffer.read())
u=pwd.getpwnam('autoeval')
for q in [Path('/work'),p,p/'authorized_keys']: os.chown(q,u.pw_uid,u.pw_gid)
os.chmod('/work',0o700);os.chmod(p,0o700);os.chmod(p/'authorized_keys',0o600)
Path('/run/sshd').mkdir(exist_ok=True)
"""
    docker(
        "exec",
        "-i",
        container,
        "python",
        "-c",
        script,
        payload=f"{key.get_name()} {key.get_base64()} autoeval-local-simulator\n".encode(),
    )
    host_key = (
        docker("exec", container, "cat", "/etc/ssh/ssh_host_ed25519_key.pub").decode().split()[1]
    )
    fingerprint = "SHA256:" + base64.b64encode(
        hashlib.sha256(base64.b64decode(host_key)).digest()
    ).decode().rstrip("=")
    config = {
        "host": "127.0.0.1",
        "port": 2222,
        "username": "autoeval",
        "workdir": "/work",
        "fingerprint": fingerprint,
        "credential_ref": reference,
        "auth_kind": "private_key",
    }
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    docker(
        "exec",
        "-d",
        container,
        "/usr/sbin/sshd",
        "-D",
        "-e",
        "-o",
        "PasswordAuthentication=no",
        "-o",
        "PermitRootLogin=no",
    )
    print(
        json.dumps(
            {
                "simulator_ready": True,
                "fingerprint": fingerprint,
                "config_file": str(config_path.resolve()),
            }
        )
    )


if __name__ == "__main__":
    main()
