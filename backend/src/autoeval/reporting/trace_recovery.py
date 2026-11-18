"""Recover original Harbor trajectories without creating execution attempts or model calls."""

import argparse
import asyncio
import hashlib
import json
import tarfile
import uuid
from pathlib import PurePosixPath

from sqlalchemy import select, text

from autoeval.audit import AuditEvent
from autoeval.catalog.datasets import canonical_manifest, read_manifest, write_manifest
from autoeval.config import get_settings
from autoeval.db import create_database
from autoeval.evaluation.models import ResultArchiveRevision
from autoeval.langfuse_integration import TraceImport, import_configured, intent
from autoeval.reporting.models import CaseExecutionRecord

FILES = {"result.json", "verifier/reward.json", "agent/trajectory.json"}


class NativeTraceBundle:
    def __init__(self, path, run_id):
        self.tar = tarfile.open(path, "r:")  # noqa: SIM115 -- owned by close() in the CLI finally block
        try:
            self._validate(run_id)
        except BaseException:
            self.tar.close()
            raise

    def _validate(self, run_id):
        members = self.tar.getmembers()
        names = [m.name for m in members]
        if len(names) != len(set(names)) or len(names) > 6001:
            raise ValueError("Duplicate or excessive archive members")
        for member in members:
            parts = PurePosixPath(member.name)
            if (
                not member.isfile()
                or parts.is_absolute()
                or ".." in parts.parts
                or member.size > 8 * 1024 * 1024
            ):
                raise ValueError("Unsafe native archive entry")
            if member.name != "manifest.json" and (
                "/".join(parts.parts[1:]) not in FILES or len(parts.parts) < 2
            ):
                raise ValueError("Unexpected native archive file")
        raw = self.tar.extractfile("manifest.json").read()
        self.manifest_sha256 = hashlib.sha256(raw).hexdigest()
        self.manifest = json.loads(raw)
        if (
            self.manifest.get("run_id") != str(run_id)
            or self.manifest.get("schema_version") != "native-traces.v1"
        ):
            raise ValueError("Native archive belongs to another run")
        self.trials = self.manifest["trials"]
        expected = {"manifest.json"}
        seen = set()
        for trial in self.trials:
            name = trial["trial_name"]
            if name in seen or PurePosixPath(name).name != name or name in {".", ".."}:
                raise ValueError("Invalid trial identity")
            seen.add(name)
            if set(trial["files"]) != FILES:
                raise ValueError("Complete native trajectory and score files required")
            expected.update(name + "/" + relative for relative in FILES)
        if expected != set(names):
            raise ValueError("Native file manifest mismatch")

    def read(self, trial):
        files = {}
        for relative, meta in trial["files"].items():
            raw = self.tar.extractfile(trial["trial_name"] + "/" + relative).read()
            if len(raw) != meta["size"] or hashlib.sha256(raw).hexdigest() != meta["sha256"]:
                raise ValueError("Native trace checksum mismatch")
            files[relative] = raw.decode("utf-8")
        native = json.loads(files["result.json"])
        trajectory = json.loads(files["agent/trajectory.json"])
        if (
            native.get("trial_name") != trial["trial_name"]
            or native.get("task_name") != trial["task_name"]
            or native.get("finished_at") != trial["finished_at"]
            or trajectory.get("session_id") != native.get("id")
            or not isinstance(trajectory.get("steps"), list)
            or not trajectory["steps"]
        ):
            raise ValueError("Native trajectory identity mismatch")
        return {"trial_name": trial["trial_name"], "files": files}

    def close(self):
        self.tar.close()


async def recover(args):
    settings = get_settings()
    if not import_configured(settings):
        raise ValueError("Langfuse configuration is incomplete")
    run_id = uuid.UUID(args.run_id)
    engine, sessions = create_database(settings)
    bundle = NativeTraceBundle(args.archive, run_id)
    try:
        async with engine.connect() as lock:
            owned = await lock.scalar(
                text("SELECT pg_try_advisory_lock(hashtext(:key))"),
                {"key": "trace-recovery:" + str(run_id)},
            )
            if not owned:
                raise ValueError("Trace recovery already running")
            async with sessions() as db:
                from autoeval.models import RunSnapshot
                from autoeval.resources.targets import TargetBinding
                from autoeval.secrets import FileSecretStore

                snapshot = await db.scalar(select(RunSnapshot).where(RunSnapshot.run_id == run_id))
                target = await db.get(
                    TargetBinding, uuid.UUID(snapshot.canonical_body["target_id"])
                )
                model_secret = FileSecretStore(settings.secret_store_path).get(
                    target.credential_ref
                )
                rows = (
                    await db.execute(
                        select(TraceImport, CaseExecutionRecord)
                        .join(CaseExecutionRecord, CaseExecutionRecord.id == TraceImport.attempt_id)
                        .where(
                            TraceImport.run_id == run_id,
                            CaseExecutionRecord.dataset_key == "AutomationBench",
                        )
                    )
                ).all()
                revisions = (
                    await db.scalars(
                        select(ResultArchiveRevision).where(
                            ResultArchiveRevision.run_id == run_id,
                            ResultArchiveRevision.dataset_key == "AutomationBench",
                        )
                    )
                ).all()
                if len(revisions) != 1:
                    raise ValueError("An unambiguous verified score recovery is required")
                recovered = await asyncio.to_thread(read_manifest, settings, revisions[0])
                scores = {c["case_id"]: c for c in recovered["cases"]}
                by_sample = {case.sample_id: (row, case) for row, case in rows}
                if (
                    len(by_sample) != len(rows)
                    or len(rows) != len(bundle.trials)
                    or len(scores) != len(rows)
                ):
                    raise ValueError("Native traces do not match existing attempts exactly")
                work = []
                seen = set()
                # Verify every native file and every retained successful trace before any write.
                for trial in bundle.trials:
                    sample = trial["task_name"].removeprefix("automationbench/")
                    if sample in seen or sample not in by_sample or sample not in scores:
                        raise ValueError("Unexpected native sample identity")
                    seen.add(sample)
                    row, case = by_sample[sample]
                    artifact = bundle.read(trial)
                    if model_secret and any(
                        model_secret in value for value in artifact["files"].values()
                    ):
                        raise ValueError("Credential found in native artifact; recovery stopped")
                    scored = scores[sample]
                    if (
                        case.attempt_no != scored["attempt"]
                        or case.tool_metadata.get("tool_finished_at") != trial["finished_at"]
                    ):
                        raise ValueError("Trace attempt identity differs from original evidence")
                    for relative in ("result.json", "verifier/reward.json"):
                        if (
                            artifact["files"][relative]
                            != scored["harbor_artifact"]["files"][relative]
                        ):
                            raise ValueError("Native trace and recovered scoring evidence conflict")
                    if row.status == "succeeded":
                        existing = await asyncio.to_thread(read_manifest, settings, row)
                        if any(
                            existing.get("files", {}).get(k) != v
                            for k, v in artifact["files"].items()
                        ):
                            raise ValueError("Existing successful trace differs from native source")
                    elif row.status not in {"missing", "pending"}:
                        raise ValueError(
                            "Trace has an unresolved or failed import; explicit inspection required"
                        )
                    work.append((row.id, trial))
            print(
                json.dumps(
                    {
                        "phase": "verified",
                        "trials": len(work),
                        "manifest_sha256": bundle.manifest_sha256,
                        "dry_run": args.dry_run,
                    }
                ),
                flush=True,
            )
            if args.dry_run:
                return
            for start in range(0, len(work), args.batch_size):
                batch = work[start : start + args.batch_size]
                waiting = []
                for identifier, trial in batch:
                    async with sessions() as db, db.begin():
                        row = await db.get(TraceImport, identifier, with_for_update=True)
                        if row.status == "succeeded":
                            continue
                        if row.status == "missing":
                            artifact = bundle.read(trial)
                            raw = canonical_manifest(artifact)
                            digest = hashlib.sha256(raw).hexdigest()
                            key = f"harbor-traces/{run_id}/{row.attempt_id}/{digest}.json"
                            old = {
                                "object_key": row.object_key,
                                "sha256": row.sha256,
                                "status": row.status,
                                "retry_no": row.retry_no,
                            }
                            await asyncio.to_thread(write_manifest, settings, key, raw)
                            from types import SimpleNamespace

                            await asyncio.to_thread(
                                read_manifest,
                                settings,
                                SimpleNamespace(object_key=key, sha256=digest),
                            )
                            row.object_key = key
                            row.sha256 = digest
                            row.retry_no += 1
                            row.status = "pending"
                            row.error_code = None
                            db.add(
                                AuditEvent(
                                    actor="local-operator",
                                    action="trace_evidence_recovered",
                                    resource_type="langfuse_trace_import",
                                    resource_id=str(row.id),
                                    run_id=run_id,
                                    outcome="pending",
                                    request_id="trace-recovery-20261118",
                                    details={
                                        "previous": old,
                                        "object_key": key,
                                        "sha256": digest,
                                        "source_manifest_sha256": bundle.manifest_sha256,
                                        "source_files": trial["files"],
                                        "attempt_id": str(row.attempt_id),
                                        "method": "native-trace-recovery.v1",
                                        "reason": "Recover original omitted trajectory; no new model execution",
                                    },
                                )
                            )
                            intent(db, row)
                        elif row.status != "pending":
                            raise ValueError("Import state changed unexpectedly")
                        waiting.append(identifier)
                deadline = asyncio.get_running_loop().time() + args.batch_timeout
                while waiting:
                    async with sessions() as db:
                        states = (
                            await db.execute(
                                select(TraceImport.id, TraceImport.status).where(
                                    TraceImport.id.in_(waiting)
                                )
                            )
                        ).all()
                    if any(state == "failed" for _, state in states):
                        raise ValueError("Trace import failed; stopped without automatic resend")
                    waiting = [identifier for identifier, state in states if state != "succeeded"]
                    if not waiting:
                        break
                    if asyncio.get_running_loop().time() > deadline:
                        raise TimeoutError(
                            "Trace import not confirmed; stopped without automatic resend"
                        )
                    await asyncio.sleep(3)
                print(
                    json.dumps(
                        {
                            "phase": "imported",
                            "processed": min(start + args.batch_size, len(work)),
                            "total": len(work),
                        }
                    ),
                    flush=True,
                )
            print(
                json.dumps({"phase": "complete", "total": len(work), "model_calls": 0}), flush=True
            )
    finally:
        bundle.close()
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("archive")
    parser.add_argument("--batch-size", type=int, choices=range(1, 17), default=8)
    parser.add_argument("--batch-timeout", type=int, default=300)
    parser.add_argument("--dry-run", action="store_true")
    asyncio.run(recover(parser.parse_args()))
