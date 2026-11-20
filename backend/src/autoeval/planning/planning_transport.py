"""Controlled executor extension; legacy diagnostic transports keep their contract."""

import ast
import asyncio
import base64
import errno
import hashlib
import importlib.metadata
import json
import shlex
import stat
import uuid
from pathlib import Path, PurePosixPath

from autoeval.resources import ResourceBinding
from autoeval.resources.docker_executor import DockerExecutor
from autoeval.resources.models import SSHResourceBinding
from autoeval.resources.ssh_executor import SSHExecutor
from autoeval.resources.ssh_resources import connection_for
from autoeval_runtime.planning_runtime import validate_spec

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
RUNTIME = PACKAGE_ROOT.parent / "autoeval_runtime" / "planning_runtime.py"


def runtime_files():
    """Ship exact calculation and validation source without importing the API in containers."""
    source = (PACKAGE_ROOT / "catalog" / "standard_compilation.py").read_text(encoding="utf-8")
    names = {"COMMON", "ACCURACY", "AGENT", "digest", "leaves", "validate_config", "reject_secrets"}
    pieces = []
    for node in ast.parse(source).body:
        name = getattr(node, "name", None)
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        if name in names:
            pieces.append(ast.get_source_segment(source, node))
    contract = "import hashlib\nimport json\n" + "\n\n".join(pieces)
    engine = (
        Path(__file__)
        .with_name("planning_engine.py")
        .read_text(encoding="utf-8")
        .replace("from autoeval.catalog.standard_inputs import", "from planning_contract import")
    )
    return {
        "planning_runtime.py": RUNTIME.read_bytes(),
        "planner-package.json": (
            RUNTIME.parents[2] / "tool-locks" / "planner-package.json"
        ).read_bytes(),
        "planning_calculation.py": engine.encode(),
        "planning_contract.py": contract.encode(),
        "native_predictions.py": RUNTIME.with_name("native_predictions.py").read_bytes(),
        "aisbench_native.py": RUNTIME.with_name("aisbench_native.py").read_bytes(),
        "sample_dispatch.py": RUNTIME.with_name("sample_dispatch.py").read_bytes(),
    }


async def read_container_progress(adapter, job):
    key = str(uuid.UUID(job.submission_key))
    root = (
        await adapter.job_root(key)
        if isinstance(adapter, PlanningRemoteContainer)
        else "/work/autoeval-jobs"
    )
    script = "import pathlib,sys,json;p=pathlib.Path(sys.argv[1]);assert not p.is_symlink();print(p.read_text() if p.is_file() else '{}')"
    raw = await asyncio.to_thread(
        adapter.command,
        [
            "exec",
            adapter.container_id,
            "python3",
            "-c",
            script,
            root + "/" + key + "/progress.json",
        ],
    )
    value = json.loads(raw)
    if value.get("stage") == "tool_running" and not value.get("source"):
        script = """import json,sys
from pathlib import Path
from datetime import datetime,timezone
root=Path(sys.argv[1]);done=set()
spec=json.loads((root/'spec.json').read_text())
if spec.get('compilation',{}).get('config',{}).get('subcommand')!='harbor_agent':
 print((root/'progress.json').read_text());raise SystemExit(0)
for p in (root/'output').rglob('result.json'):
 if p.is_symlink() or not p.resolve().is_relative_to(root.resolve()) or p.stat().st_size>2097152:continue
 try:d=json.loads(p.read_text())
 except (ValueError,OSError,UnicodeError):continue
 if isinstance(d,dict) and 'agent_execution' in d and 'verifier_result' in d and d.get('finished_at'):done.add(str(p.parent))
print(json.dumps({'job_id':root.name,'source':'harbor_result_files','finish_count':len(done),'observed_at':datetime.now(timezone.utc).isoformat(),'snapshot_kind':'live'}))
"""
        extra = await asyncio.to_thread(
            adapter.command,
            ["exec", adapter.container_id, "python3", "-c", script, root + "/" + key],
        )
        value = json.loads(extra)
    if value and value.get("job_id") != key:
        raise ValueError("Progress belongs to another job")
    return value


class PlanningRemoteContainer(DockerExecutor):
    """Docker lifecycle runs over pinned SSH; no host Planner execution or SFTP ambiguity."""

    def __init__(self, connection, container_id, image_id, runtime_root=None):
        super().__init__("docker", container_id, image_id)
        self.control = SSHExecutor(connection)
        self.files = {"job_runtime.py": self.runtime.read_bytes(), **runtime_files()}
        from autoeval_runtime.planning_runtime import PLANNER_REVISION, installed_revision

        if installed_revision("autoeval-task-planner") == PLANNER_REVISION:
            distribution = importlib.metadata.distribution("autoeval-task-planner")
            for item in distribution.files:
                name = str(item).replace("\\", "/")
                if ".." in Path(name).parts or "__pycache__" in name or name.endswith(".pyc"):
                    continue
                if name.startswith("autoeval_planner/") or ".dist-info/" in name:
                    self.files["deps/" + name] = distribution.locate_file(item).read_bytes()
        sha = hashlib.sha256(b"".join(self.files[k] for k in sorted(self.files))).hexdigest()
        root = runtime_root or "/tmp/autoeval-planning-runtime"
        path = PurePosixPath(root)
        if not path.is_absolute() or ".." in path.parts or str(path) == "/":
            raise ValueError("Planning runtime root must be an absolute directory")
        self.remote_dir = str(path / sha)

    def container_environment(self, job_root):
        return [
            "env",
            "AE_JOB_ROOT=" + job_root,
            "sh",
            "-c",
            'export PYTHONPATH="$1${PYTHONPATH:+:$PYTHONPATH}"; shift; exec "$@"',
            "autoeval-runtime",
            self.remote_dir + "/deps",
        ]

    def command(self, arguments, payload=None):
        with self.control.connect() as client:
            if arguments[0] == "exec":
                index = arguments.index(self.container_id) + 1
                if arguments[index] == "python":
                    arguments = [*arguments[:index], "python3", *arguments[index + 1 :]]
                arguments = [
                    *arguments[:index],
                    *self.container_environment(self.remote_dir + "/jobs"),
                    *arguments[index:],
                ]
            return self.control.command(client, ["docker", *arguments], payload)

    async def validate(self, spec):
        if spec.get("kind") != "framework_smoke":
            validate_spec(spec)
        raw = await asyncio.to_thread(self.command, ["inspect", self.container_id])
        row = json.loads(raw)[0]
        if (
            row["Id"] != self.container_id
            or row["Image"] != self.image_id
            or not row["State"]["Running"]
        ):
            raise ValueError("Pinned planning container changed or stopped")

    async def install_runtime(self):
        script = "import pathlib,sys,json,base64,hashlib; root=pathlib.Path(sys.argv[1]); files=json.load(sys.stdin); root.mkdir(parents=True,exist_ok=True);\nfor name,encoded in files.items():\n p=root/name; assert p.resolve().is_relative_to(root.resolve()) and not p.is_symlink(); data=base64.b64decode(encoded); p.parent.mkdir(parents=True,exist_ok=True); assert not p.exists() or p.read_bytes()==data; p.write_bytes(data); p.chmod(0o600)\nprint(json.dumps({name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in files}))"
        payload = json.dumps(
            {k: base64.b64encode(v).decode() for k, v in self.files.items()}
        ).encode()
        actual = json.loads(
            await asyncio.to_thread(
                self.command,
                ["exec", "-i", self.container_id, "python3", "-c", script, self.remote_dir],
                payload,
            )
        )
        if actual != {k: hashlib.sha256(v).hexdigest() for k, v in self.files.items()}:
            raise ValueError("Runtime readback mismatch")

    async def job_root(self, submission_key):
        key = str(uuid.UUID(submission_key))
        runtime_root = str(PurePosixPath(self.remote_dir).parent)
        script = """import json, pathlib, re, sys
root = pathlib.Path(sys.argv[1])
found = []
if root.is_dir():
    for bucket in root.iterdir():
        if not re.fullmatch(r'[a-f0-9]{64}', bucket.name) or bucket.is_symlink():
            continue
        jobs = bucket / 'jobs'
        job = jobs / sys.argv[2]
        if jobs.is_symlink() or job.is_symlink():
            raise ValueError('Unsafe job path')
        if job.is_dir():
            found.append(str(jobs))
print(json.dumps(found))
"""
        raw = await asyncio.to_thread(
            self.command,
            ["exec", self.container_id, "python3", "-c", script, runtime_root, key],
        )
        found = json.loads(raw)
        if len(found) > 1:
            raise ValueError("Job exists in multiple pinned runtime versions")
        return found[0] if found else self.remote_dir + "/jobs"

    async def _invoke(self, action, key, payload=None):
        key = str(uuid.UUID(key))
        await self.validate({"kind": "framework_smoke", "duration_seconds": 0})
        if action in {"cancel", "cleanup"}:
            await self.install_runtime()
        root = await self.job_root(key)
        raw = await asyncio.to_thread(
            self.command,
            [
                "exec",
                "-i",
                self.container_id,
                "env",
                f"AE_JOB_ROOT={root}",
                "python3",
                self.remote_dir + "/job_runtime.py",
                action,
                key,
            ],
            json.dumps(payload).encode() if payload is not None else None,
        )
        return json.loads(raw)

    async def progress(self, job):
        return await read_container_progress(self, job)

    async def collect_log(self, job):
        """Read only this owned job's tool log before its files are cleaned."""
        key = str(uuid.UUID(job.submission_key))
        root = await self.job_root(key)
        script = (
            "import pathlib,sys,json;p=pathlib.Path(sys.argv[1]);"
            "assert not p.is_symlink();p=p if p.is_file() else p.with_name('output.log');assert not p.is_symlink();raw=p.read_bytes() if p.is_file() else b'';"
            "print(json.dumps({'content':raw[-2097152:].decode('utf-8',errors='replace'),"
            "'truncated':len(raw)>2097152}))"
        )
        raw = await asyncio.to_thread(
            self.command,
            [
                "exec",
                self.container_id,
                "python3",
                "-c",
                script,
                root + "/" + key + "/tool.log",
            ],
        )
        return json.loads(raw)

    async def collect(self, job):
        """Stage large results in a host file before transfer instead of capped stdout."""
        key = str(uuid.UUID(job.submission_key))
        root = await self.job_root(key)
        path = f"/tmp/autoeval-collect-{key}-{uuid.uuid4().hex}.json"
        command = (
            "umask 077; set -C; "
            + shlex.join(
                [
                    "docker",
                    "exec",
                    self.container_id,
                    *self.container_environment(root),
                    "python3",
                    self.remote_dir + "/job_runtime.py",
                    "collect",
                    key,
                ]
            )
            + " > "
            + shlex.quote(path)
        )

        def read():
            with self.control.connect() as client:
                try:
                    self.control.command(client, ["sh", "-c", command])
                    with client.open_sftp() as sftp:
                        entry = sftp.lstat(path)
                        if not stat.S_ISREG(entry.st_mode):
                            raise ValueError("Result must be a regular file")
                        with sftp.open(path, "rb") as stream:
                            raw = stream.read(16 * 1024 * 1024 + 1)
                    if len(raw) > 16 * 1024 * 1024:
                        raise ValueError("Result too large")
                    return json.loads(raw)
                finally:
                    try:
                        with client.open_sftp() as sftp:
                            sftp.remove(path)
                    except OSError:
                        pass

        return await asyncio.to_thread(read)

    async def preflight(self, tasks=None):
        await self.validate({"kind": "framework_smoke", "duration_seconds": 0})
        await self.install_runtime()
        return json.loads(
            await asyncio.to_thread(
                self.command,
                [
                    "exec",
                    "-i",
                    self.container_id,
                    "python3",
                    self.remote_dir + "/planning_runtime.py",
                    "preflight",
                ],
                json.dumps(tasks).encode(),
            )
        )


class PlanningDocker(DockerExecutor):
    def __init__(self, executable, container_id, image_id):
        super().__init__(executable, container_id, image_id)
        self.remote_dir = (
            "/work/autoeval-runtime/"
            + hashlib.sha256(self.runtime.read_bytes() + RUNTIME.read_bytes()).hexdigest()
        )

    def command(self, arguments, payload=None):
        import subprocess

        # Structured results are bounded independently from the diagnostic transport.
        result = subprocess.run(
            [self.executable, *arguments],
            input=payload,
            capture_output=True,
            timeout=30,
            check=True,
        )
        if len(result.stdout) > 16 * 1024 * 1024:
            raise ValueError("Controlled response too large")
        return result.stdout

    async def validate(self, spec):
        if spec.get("kind") != "framework_smoke":
            validate_spec(spec)
        await super().validate({"kind": "framework_smoke", "duration_seconds": 0})

    async def install_runtime(self):
        await super().install_runtime()
        for name, data in runtime_files().items():
            await asyncio.to_thread(
                self.command,
                [
                    "exec",
                    "-i",
                    self.container_id,
                    "python",
                    "-c",
                    "import pathlib,sys;p=pathlib.Path(sys.argv[1]);p.write_bytes(sys.stdin.buffer.read());p.chmod(0o600)",
                    self.remote_dir + "/" + name,
                ],
                data,
            )

    async def progress(self, job):
        return await read_container_progress(self, job)

    async def preflight(self, tasks=None):
        await self.validate({"kind": "framework_smoke", "duration_seconds": 0})
        await self.install_runtime()
        return json.loads(
            await asyncio.to_thread(
                self.command,
                [
                    "exec",
                    "-i",
                    self.container_id,
                    "python",
                    self.remote_dir + "/planning_runtime.py",
                    "preflight",
                ],
                json.dumps(tasks).encode(),
            )
        )


class PlanningSSH(SSHExecutor):
    def __init__(self, connection):
        super().__init__(connection)
        combined = hashlib.sha256(self.runtime.read_bytes() + RUNTIME.read_bytes()).hexdigest()
        self.remote_runtime = f"{self.root}/runtime/{combined}/job_runtime.py"

    def prepare(self, client):
        # Parent installs the legacy runtime with checksum validation in its own namespace.
        controlled = self.remote_runtime
        self.remote_runtime = f"{self.root}/runtime/{self.digest}.py"
        try:
            super().prepare(client)
        finally:
            self.remote_runtime = controlled
        folder = str(Path(controlled).parent).replace("\\", "/")
        self.command(
            client,
            [
                "python3",
                "-c",
                "import pathlib,sys; p=pathlib.Path(sys.argv[1]); assert not p.is_symlink(); p.mkdir(mode=0o700,exist_ok=True)",
                folder,
            ],
        )
        with client.open_sftp() as sftp:
            for source in (self.runtime, RUNTIME):
                remote = folder + "/" + source.name
                try:
                    entry = sftp.lstat(remote)
                except FileNotFoundError:
                    with sftp.open(remote, "wx") as stream:
                        stream.write(source.read_bytes())
                    sftp.chmod(remote, 0o600)
                else:
                    if not stat.S_ISREG(entry.st_mode):
                        raise ValueError("Runtime must be a regular file")
                    with sftp.open(remote, "rb") as stream:
                        if stream.read(len(source.read_bytes()) + 1) != source.read_bytes():
                            raise ValueError("Controlled runtime checksum mismatch")

    async def validate(self, spec):
        validate_spec(spec)

    async def preflight(self, tasks=None):
        def check():
            with self.connect() as client:
                self.prepare(client)
                path = self.remote_runtime.rsplit("/", 1)[0] + "/planning_runtime.py"
                return json.loads(
                    self.command(
                        client,
                        ["python3", path, "preflight"],
                        json.dumps(tasks).encode(),
                    )
                )

        return await asyncio.to_thread(check)

    async def collect(self, job):
        # General results can be larger than the 1 MB diagnostic result limit.
        def collect():
            with self.connect() as client:
                self.prepare(client)
                state = json.loads(
                    self.command(
                        client,
                        [
                            "env",
                            f"AE_JOB_ROOT={self.root}/jobs",
                            "python3",
                            self.remote_runtime,
                            "collect_dispatch",
                            job.submission_key,
                        ],
                    )
                )
                if state["state"] in {"succeeded", "failed", "cancelled"}:
                    path = f"{self.root}/jobs/{job.submission_key}/result.json"
                    with client.open_sftp() as sftp:
                        try:
                            entry = sftp.lstat(path)
                        except OSError as exc:
                            if exc.errno != errno.ENOENT or state["state"] == "succeeded":
                                raise
                            return state
                        if not stat.S_ISREG(entry.st_mode):
                            raise ValueError("Result must be a regular file")
                        with sftp.open(path, "rb") as stream:
                            raw = stream.read(16 * 1024 * 1024 + 1)
                        if len(raw) > 16 * 1024 * 1024:
                            raise ValueError("Result too large")
                        state["result"] = json.loads(raw)
                return state

        return await asyncio.to_thread(collect)


async def transport(session, settings, inputs):
    if inputs["resource_kind"] == "customer_ssh":
        row = await session.get(SSHResourceBinding, inputs["resource_id"])
        if row is None:
            raise ValueError("SSH binding missing")
        import os

        config_path = (
            os.environ.get("AE_PLANNING_CONTAINER_CONFIG") or settings.planning_container_config
        )
        if not config_path:
            raise ValueError("Explicit remote planning container binding required")
        bindings = json.loads(Path(config_path).read_text(encoding="utf-8"))
        binding = bindings.get(str(row.id))
        if not binding:
            raise ValueError("Selected SSH resource has no pinned planning container")
        return PlanningRemoteContainer(
            connection_for(row, settings),
            binding["container_id"],
            binding["image_id"],
            binding.get("runtime_root"),
        )
    row = await session.get(ResourceBinding, inputs["resource_id"])
    if row is None:
        raise ValueError("Docker binding missing")
    return PlanningDocker(settings.docker_executable, row.container_id, row.image_id)
