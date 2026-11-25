# ruff: noqa: PLC0414 -- explicit compatibility re-exports
"""Versioned standard inputs and non-executing adaptor configuration compilation."""

import asyncio
import json
import ssl
import subprocess
import uuid
from pathlib import PurePosixPath
from time import monotonic

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import ForeignKey, Index, String, UniqueConstraint, func, or_, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from autoeval.catalog.adaptor_versions import CURRENT_ADAPTOR
from autoeval.catalog.registry import Asset, AssetVersion
from autoeval.catalog.standard_compilation import (
    ACCURACY as ACCURACY,
)
from autoeval.catalog.standard_compilation import (
    ADAPTOR_REVISION as ADAPTOR_REVISION,
)
from autoeval.catalog.standard_compilation import (
    AGENT as AGENT,
)
from autoeval.catalog.standard_compilation import (
    BENCHMARKS as BENCHMARKS,
)
from autoeval.catalog.standard_compilation import (
    COMMON as COMMON,
)
from autoeval.catalog.standard_compilation import (
    ENVIRONMENT as ENVIRONMENT,
)
from autoeval.catalog.standard_compilation import (
    FILES as FILES,
)
from autoeval.catalog.standard_compilation import (
    compile_config as compile_config,
)
from autoeval.catalog.standard_compilation import (
    digest as digest,
)
from autoeval.catalog.standard_compilation import (
    discover as discover,
)
from autoeval.catalog.standard_compilation import (
    leaves as leaves,
)
from autoeval.catalog.standard_compilation import (
    merge as merge,
)
from autoeval.catalog.standard_compilation import (
    read_repository_config,
)
from autoeval.catalog.standard_compilation import (
    reject_secrets as reject_secrets,
)
from autoeval.catalog.standard_compilation import (
    safe_json as safe_json,
)
from autoeval.catalog.standard_compilation import (
    validate_config as validate_config,
)
from autoeval.infrastructure.models import Base, Record
from autoeval.reporting.data_workbench import development
from autoeval.resources.models import SSHResourceBinding, TargetBinding

STANDARD_REPO = "SJTUyh/AutoEval-Standard"


class StandardInputVersion(Record, Base):
    __tablename__ = "standard_input_version"
    repository: Mapped[str] = mapped_column(String(256))
    revision: Mapped[str] = mapped_column(String(64))
    source_model: Mapped[str] = mapped_column(String(256))
    benchmark: Mapped[str] = mapped_column(String(128))
    content_sha256: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        UniqueConstraint("repository", "revision", "source_model", "benchmark"),
        Index("ix_standard_input_source", "source_model", "benchmark", "created_at"),
    )


class StandardInputCompilation(Record, Base):
    __table_args__ = (Index("ix_standard_input_mapping", "model_id", "input_id"),)
    __tablename__ = "standard_input_compilation"
    input_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("standard_input_version.id", ondelete="RESTRICT"))
    model_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("asset.id", ondelete="RESTRICT"))
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    payload: Mapped[dict] = mapped_column(JSONB)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Bundle(Strict):
    repository: str = STANDARD_REPO
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    files: dict[str, str] = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def validate_files(self):
        if self.repository != STANDARD_REPO:
            raise ValueError("Unsupported standard repository")
        if sum(len(raw.encode()) for raw in self.files.values()) > 2_000_000:
            raise ValueError("Bundle exceeds 2 MB")
        for path, raw in self.files.items():
            parts = PurePosixPath(path).parts
            if (
                len(parts) != 3
                or parts[1] not in BENCHMARKS
                or parts[2] not in FILES
                or "\\" in path
                or any(p in {".", ".."} for p in parts)
                or PurePosixPath(path).as_posix() != path
                or len(parts[0]) > 256
            ):
                raise ValueError("Expected model/benchmark/config.json")
            value = safe_json(raw)
            if not isinstance(value, dict):
                raise ValueError("JSON object required")  # noqa: TRY004 -- Pydantic validation
            reject_secrets(value)
        return self


class Confirm(Strict):
    bundle: Bundle
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Sync(Strict):
    ref: str = Field(default="main", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_./-]+$")


class CompileInput(Strict):
    input_policy: str = Field(default="legacy", pattern=r"^(repository|legacy)$")
    adaptor_revision: str = Field(
        default=CURRENT_ADAPTOR,
        pattern="^(955089ab32ef696c231d628f5ad0d9da28f430c4|1fb877ace4a087cb805e9a3d5878dcce6349bc35)$",
    )
    model_id: uuid.UUID | None = None
    target_id: uuid.UUID | None = None
    template_version: str = Field(default="platform.v1", pattern=r"^[a-zA-Z0-9_.-]{1,128}$")
    template: dict = Field(default_factory=dict)
    adjustments: dict = Field(default_factory=dict)
    execution: str = Field(default="docker", pattern=r"^(docker|local)$")
    datasets_dir: str | None = Field(default=None, max_length=1024)
    task_path: str | None = Field(default=None, max_length=1024)
    tool_root: str | None = Field(default=None, max_length=1024)
    resource_ids: list[uuid.UUID] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def no_credentials(self):
        if len(set(self.resource_ids)) != len(self.resource_ids):
            raise ValueError("Execution resources must be unique")
        reject_secrets(self.template)
        reject_secrets(self.adjustments)
        for overlay in (self.template, self.adjustments):
            if set(overlay) - {"tool", "subcommand", "params"} or not isinstance(
                overlay.get("params", {}), dict
            ):
                raise ValueError("Template and adjustments require an object-valued params")
            if len(json.dumps(overlay, allow_nan=False).encode()) > 200_000:
                raise ValueError("Template or adjustments exceed 200 KB")
        for value in (self.datasets_dir, self.task_path, self.tool_root):
            if value is not None and (
                not value.startswith("/") or ".." in PurePosixPath(value).parts or "\n" in value
            ):
                raise ValueError("Execution paths must be absolute POSIX paths")
        return self


router = APIRouter(
    prefix="/api/autoeval/v1/standard-inputs",
    tags=["standard inputs"],
    dependencies=[Depends(development)],
)


def envelope(data, request):
    return {"data": data, "request_id": request.state.request_id}


@router.get("/dataset-registrations")
async def dataset_registrations(request: Request):
    async with request.app.state.sessions() as session:
        rows = (
            await session.execute(
                select(Asset, AssetVersion)
                .join(AssetVersion, AssetVersion.asset_id == Asset.id)
                .where(Asset.kind == "dataset")
                .order_by(Asset.asset_key, AssetVersion.created_at.desc())
            )
        ).all()
        return envelope(
            [
                {
                    "name": asset.name,
                    "key": asset.asset_key,
                    "version": version.version,
                    "metadata": version.metadata_json,
                }
                for asset, version in rows
            ],
            request,
        )


@router.get("/tags")
async def repository_tags(request: Request):
    """Current repository labels only; immutable input identities remain commit-based."""
    state = request.app.state
    if not hasattr(state, "standard_tags_lock"):
        state.standard_tags_lock = asyncio.Lock()
        state.standard_tags_cache = None
    async with state.standard_tags_lock:
        cached = state.standard_tags_cache
        if cached is not None and cached[0] > monotonic():
            return envelope(cached[1], request)
        result = await fetch_repository_tags()
        ttl = 300 if result["status"] == "available" else 15
        state.standard_tags_cache = (monotonic() + ttl, result)
        return envelope(result, request)


async def fetch_repository_tags():
    tags = []
    try:
        async with httpx.AsyncClient(
            timeout=8, follow_redirects=False, verify=ssl.create_default_context()
        ) as client:
            for page in range(1, 11):
                response = await client.get(
                    f"https://api.github.com/repos/{STANDARD_REPO}/tags",
                    params={"per_page": 100, "page": page},
                )
                response.raise_for_status()
                items = response.json()
                for item in items:
                    tags.append({"name": item["name"], "revision": item["commit"]["sha"]})
                if len(items) < 100:
                    return {"status": "available", "tags": tags}
        return {"status": "incomplete", "tags": tags}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                ["git", "ls-remote", "--tags", f"https://github.com/{STANDARD_REPO}.git"],
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
            resolved = {}
            peeled = {}
            for line in completed.stdout.splitlines():
                sha, ref = line.split("\t", 1)
                name = ref.removeprefix("refs/tags/")
                if name.endswith("^{}"):
                    peeled[name[:-3]] = sha
                else:
                    resolved[name] = sha
            resolved.update(peeled)
            return {
                "status": "available",
                "tags": [{"name": name, "revision": sha} for name, sha in sorted(resolved.items())],
            }
        except (OSError, subprocess.SubprocessError, ValueError):
            return {"status": "unavailable", "tags": []}


@router.post("/sync-preview")
async def sync_preview(body: Sync, request: Request):
    try:
        async with httpx.AsyncClient(
            timeout=20, follow_redirects=False, verify=ssl.create_default_context()
        ) as client:
            response = await client.get(
                f"https://api.github.com/repos/{STANDARD_REPO}/commits/{body.ref}"
            )
            response.raise_for_status()
            revision = response.json()["sha"]
            response = await client.get(
                f"https://api.github.com/repos/{STANDARD_REPO}/git/trees/{revision}?recursive=1"
            )
            response.raise_for_status()
            tree = response.json()
            if tree.get("truncated"):
                raise ValueError("Truncated repository tree")
            files = {}
            total = 0
            for node in tree["tree"]:
                parts = node["path"].split("/")
                if len(parts) != 3 or parts[1] not in BENCHMARKS or parts[2] not in FILES:
                    continue
                total += node.get("size", 2_000_001)
                if total > 2_000_000 or len(files) >= 300:
                    raise ValueError("Repository input size exceeds limit")
                response = await client.get(
                    f"https://raw.githubusercontent.com/{STANDARD_REPO}/{revision}/{node['path']}"
                )
                response.raise_for_status()
                files[node["path"]] = response.content.decode("utf-8")
            bundle = Bundle(revision=revision, files=files)
        return envelope(await preview_data(bundle, request), request)
    except httpx.HTTPError as exc:
        message = (
            "标准仓 HTTPS 证书校验失败，请检查系统可信 CA 配置"
            if "CERTIFICATE_VERIFY_FAILED" in str(exc)
            else "标准仓网络请求失败，请检查连接、访问限制及分支或 Tag"
        )
        raise HTTPException(502, message) from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, "标准仓内容校验失败，请检查目录、文件大小及 JSON 格式") from exc


async def preview_data(bundle, request):
    try:
        entries = discover(bundle)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    async with request.app.state.sessions() as session:
        for entry in entries:
            latest = await session.scalar(
                select(StandardInputVersion)
                .where(
                    StandardInputVersion.repository == bundle.repository,
                    StandardInputVersion.source_model == entry["source_model"],
                    StandardInputVersion.benchmark == entry["benchmark"],
                )
                .order_by(StandardInputVersion.created_at.desc(), StandardInputVersion.id.desc())
                .limit(1)
            )
            entry["previous_id"] = str(latest.id) if latest else None
            entry["changed_files"] = [
                name
                for name, value in entry["files"].items()
                if not latest
                or latest.payload["files"].get(name, {}).get("sha256") != value["sha256"]
            ]
            entry["removed_files"] = (
                sorted(set(latest.payload["files"]) - set(entry["files"])) if latest else []
            )
            old_fields = latest.payload["locked_fields"] if latest else {}
            new_fields = entry["locked_fields"]
            entry["field_changes"] = [
                {
                    "field": key,
                    "before": old_fields.get(key),
                    "after": new_fields.get(key),
                    "change": "added"
                    if key not in old_fields
                    else "removed"
                    if key not in new_fields
                    else "modified",
                }
                for key in sorted(set(old_fields) | set(new_fields))
                if key not in old_fields
                or key not in new_fields
                or old_fields[key] != new_fields[key]
            ]
    return {
        "bundle": bundle.model_dump(),
        "sha256": digest(bundle.model_dump()),
        "entries": entries,
        "execution_enabled": False,
        "approval_status": "not_required",
    }


@router.post("/preview")
async def preview(body: Bundle, request: Request):
    return envelope(await preview_data(body, request), request)


@router.post("/import", status_code=201)
async def import_bundle(body: Confirm, request: Request):
    if digest(body.bundle.model_dump()) != body.expected_sha256:
        raise HTTPException(409, "Preview hash differs; preview again")
    try:
        entries = discover(body.bundle)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    result = []
    async with request.app.state.sessions() as session, session.begin():
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": body.bundle.repository}
        )
        for entry in entries:
            identity = {
                "repository": body.bundle.repository,
                "revision": body.bundle.revision,
                "source_model": entry["source_model"],
                "benchmark": entry["benchmark"],
            }
            row = await session.scalar(select(StandardInputVersion).filter_by(**identity))
            sha = digest(entry)
            if row and row.content_sha256 != sha:
                raise HTTPException(409, "Immutable source identity has different content")
            if row is None:
                row = StandardInputVersion(**identity, content_sha256=sha, payload=entry)
                session.add(row)
                await session.flush()
            from autoeval.catalog.standard_baselines import sync_baseline

            await sync_baseline(session, entry, body.bundle.repository, body.bundle.revision)
            result.append(row_data(row))
    return envelope(result, request)


def input_readiness(payload, compilation=None):
    """Repository completeness is independent of target and runtime readiness."""
    missing = []
    startup = (payload.get("files") or {}).get("benchmark_config.json")
    if not startup:
        missing.append("repository_benchmark_config_missing")
    else:
        try:
            read_repository_config(startup)
        except ValueError:
            missing.append("repository_benchmark_config_invalid")
    blockers = (compilation or {}).get("blocking_reasons", [])
    return {
        "standard_config_status": "missing" if missing else "complete",
        "standard_config_missing": missing,
        "service_status": "not_bound"
        if not compilation or "target_missing" in blockers
        else "bound",
        "environment_status": "not_verified",
    }


def directory_model_expression():
    """Prefer the archived directory identity over service aliases."""
    path = StandardInputVersion.payload["files"]["standard_config.json"]["path"].astext
    return func.coalesce(
        func.nullif(func.split_part(path, "/", 1), ""), StandardInputVersion.source_model
    )


def row_data(row):
    data = {
        "id": str(row.id),
        "repository": row.repository,
        "revision": row.revision,
        "source_model": row.source_model,
        "benchmark": row.benchmark,
        "sha256": row.content_sha256,
        "created_at": row.created_at.isoformat(),
        **input_readiness(row.payload),
        **row.payload,
        "execution_enabled": False,
        "approval_status": "not_required",
    }
    path = row.payload.get("files", {}).get("standard_config.json", {}).get("path")
    data["source_model"] = (
        path.split("/", 1)[0] if isinstance(path, str) and "/" in path else row.source_model
    )
    # Legacy/operator inputs may predate presentation metadata. Never mutate their payload.
    if not isinstance(data.get("mapping"), dict):
        mapping = BENCHMARKS.get(row.benchmark)
        data["mapping"] = (
            dict(zip(("dataset", "variant", "subcommand"), mapping)) if mapping else {}
        )
    data.setdefault("files", {})
    data.setdefault("locked_fields", {})
    return data


@router.get("/filters")
async def filter_options(request: Request, include_operator: bool = False):
    async with request.app.state.sessions() as session:
        rows = (
            await session.execute(
                select(
                    StandardInputVersion.revision,
                    directory_model_expression().label("source_model"),
                    StandardInputVersion.benchmark,
                )
                .where(~StandardInputVersion.source_model.startswith("TEST-"))
                .where(
                    True if include_operator else StandardInputVersion.repository == STANDARD_REPO
                )
                .order_by(StandardInputVersion.created_at.desc(), StandardInputVersion.id.desc())
            )
        ).all()
        revisions = list(dict.fromkeys(row.revision for row in rows))
        return envelope(
            {
                "revisions": revisions,
                "latest_revision": revisions[0] if revisions else None,
                "models": sorted({row.source_model for row in rows}),
                "datasets": sorted({row.benchmark for row in rows}),
            },
            request,
        )


@router.get("")
async def versions(
    request: Request,
    offset: int = 0,
    limit: int = 20,
    model_id: uuid.UUID | None = None,
    include_test: bool = False,
    revision: str = "latest",
    source_model: str | None = None,
    dataset: str | None = None,
    include_operator: bool = False,
):
    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(422, "Invalid pagination")
    async with request.app.state.sessions() as session:
        query = select(StandardInputVersion)
        if not include_operator:
            query = query.where(StandardInputVersion.repository == STANDARD_REPO)
        if not include_test:
            query = query.where(~StandardInputVersion.source_model.startswith("TEST-"))
        if revision == "latest":
            latest_revision = await session.scalar(
                query.with_only_columns(StandardInputVersion.revision)
                .order_by(StandardInputVersion.created_at.desc(), StandardInputVersion.id.desc())
                .limit(1)
            )
            query = query.where(StandardInputVersion.revision == latest_revision)
        elif revision != "all":
            query = query.where(StandardInputVersion.revision == revision)
        if source_model:
            query = query.where(func.lower(directory_model_expression()) == source_model.lower())
        if dataset:
            query = query.where(func.lower(StandardInputVersion.benchmark) == dataset.lower())
        if model_id:
            query = query.where(
                StandardInputVersion.id.in_(
                    select(StandardInputCompilation.input_id).where(
                        StandardInputCompilation.model_id == model_id
                    )
                )
            )
        rows = (
            await session.scalars(
                query.order_by(
                    StandardInputVersion.created_at.desc(), StandardInputVersion.id.desc()
                )
                .offset(offset)
                .limit(limit + 1)
            )
        ).all()
        latest = {}
        if rows:
            compiled = (
                await session.scalars(
                    select(StandardInputCompilation)
                    .where(StandardInputCompilation.input_id.in_([row.id for row in rows[:limit]]))
                    .order_by(
                        StandardInputCompilation.created_at.desc(),
                        StandardInputCompilation.id.desc(),
                    )
                )
            ).all()
            for item in compiled:
                latest.setdefault(
                    item.input_id,
                    {
                        "input_ready": item.payload["input_ready"],
                        "template_version": item.payload["template_version"],
                        "blocking_reasons": item.payload.get("blocking_reasons", []),
                    },
                )
        return {
            **envelope(
                [
                    {
                        **row_data(row),
                        "latest_compilation": latest.get(row.id),
                        **input_readiness(row.payload, latest.get(row.id)),
                    }
                    for row in rows[:limit]
                ],
                request,
            ),
            "next_offset": offset + limit if len(rows) > limit else None,
        }


@router.get("/{input_id}")
async def detail(input_id: uuid.UUID, request: Request):
    async with request.app.state.sessions() as session:
        row = await session.get(StandardInputVersion, input_id)
        if row is None:
            raise HTTPException(404, "Standard input not found")
        history = (
            await session.scalars(
                select(StandardInputCompilation)
                .where(StandardInputCompilation.input_id == input_id)
                .order_by(StandardInputCompilation.created_at.desc())
                .limit(20)
            )
        ).all()
        return envelope(
            {**row_data(row), "compilations": [item.payload for item in history]}, request
        )


def autocomplete_template(entry):
    """Build a deterministic input-only template from pinned repository evidence."""
    source = entry["files"].get("benchmark_config.json")
    if not source:
        return {}
    template = read_repository_config(source)
    template["params"] = {
        key: value for key, value in template["params"].items() if key not in ENVIRONMENT
    }
    validate_config(template)
    return template


@router.post("/{input_id}/autocomplete")
async def autocomplete_input(input_id: uuid.UUID, body: CompileInput, request: Request):
    """Preview only: never persist, probe a host, approve, or start execution."""
    async with request.app.state.sessions() as session:
        row = await session.get(StandardInputVersion, input_id)
        if row is None:
            raise HTTPException(404, "Standard input not found")
        model = await session.get(Asset, body.model_id) if body.model_id else None
        if body.model_id and (not model or model.kind != "model"):
            raise HTTPException(422, "Select a registered model")
        if not body.model_id:
            candidates = (
                await session.scalars(
                    select(Asset).where(
                        Asset.kind == "model",
                        or_(
                            func.lower(Asset.asset_key) == row.payload["source_model"].lower(),
                            func.lower(Asset.name) == row.payload["source_model"].lower(),
                        ),
                    )
                )
            ).all()
            if len(candidates) == 1:
                model = candidates[0]
        model_id = model.id if model else None
        target = await session.get(TargetBinding, body.target_id) if body.target_id else None
        if target:
            version = await session.get(AssetVersion, target.model_version_id)
            if not version or version.asset_id != model_id:
                raise HTTPException(422, "Target must belong to selected model")
        elif model_id:
            candidates = (
                await session.scalars(
                    select(TargetBinding)
                    .join(AssetVersion, TargetBinding.model_version_id == AssetVersion.id)
                    .where(AssetVersion.asset_id == model_id)
                )
            ).all()
            if len(candidates) == 1:
                target = candidates[0]
        try:
            template = autocomplete_template(row.payload)
            version = "auto.v1." + digest(template)[:16]
            candidate = body.model_copy(
                update={
                    "model_id": model_id,
                    "target_id": target.id if target else None,
                    "template": template,
                    "template_version": version,
                    "input_policy": "repository",
                }
            )
            preview = compile_config(row.payload, candidate, target)
            preview.update(input_readiness(row.payload, preview))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return envelope(
            {
                "candidate": candidate.model_dump(mode="json"),
                "preview": preview,
                "template_source": "benchmark_config.json"
                if not row.payload["startup_missing"]
                else "repository-startup-missing:" + row.revision,
                "requires_confirmation": True,
                "notes": [
                    "模型名忽略大小写匹配；只有唯一模型与唯一服务可自动选择。",
                    "未绑定的资源路径与Agent参数不推测，请填写并确认。",
                    "预览不保存、不批准、不执行；确认后保存新的不可变编译快照。",
                ],
            },
            request,
        )


@router.post("/{input_id}/compile")
async def compile_input(input_id: uuid.UUID, body: CompileInput, request: Request):
    async with request.app.state.sessions() as session, session.begin():
        row = await session.get(StandardInputVersion, input_id)
        if row is None:
            raise HTTPException(404, "Standard input not found")
        model = await session.get(Asset, body.model_id) if body.model_id else None
        if body.model_id and (not model or model.kind != "model"):
            raise HTTPException(422, "Select a registered model")
        target = await session.get(TargetBinding, body.target_id) if body.target_id else None
        target_version = (
            await session.get(AssetVersion, target.model_version_id) if target else None
        )
        if body.target_id and (not target_version or target_version.asset_id != body.model_id):
            raise HTTPException(422, "Target must belong to selected model")
        if body.resource_ids:
            bound = await session.scalars(
                select(SSHResourceBinding.id).where(SSHResourceBinding.id.in_(body.resource_ids))
            )
            if set(bound) != set(body.resource_ids):
                raise HTTPException(422, "Execution resources must be registered SSH bindings")
        try:
            result = compile_config(row.payload, body, target)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        result.update(
            input_id=str(row.id),
            model_id=str(body.model_id) if body.model_id else None,
            source_revision=row.revision,
        )
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": str(row.id) + body.template_version},
        )
        prior = await session.scalar(
            select(StandardInputCompilation)
            .where(
                StandardInputCompilation.input_id == row.id,
                StandardInputCompilation.payload["template_version"].astext
                == body.template_version,
            )
            .limit(1)
        )
        if prior and prior.payload["template_sha256"] != result["template_sha256"]:
            raise HTTPException(409, "Template version is immutable; choose a new version")
        result.pop("sha256", None)
        result["sha256"] = digest(result)
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": result["sha256"]}
        )
        if not await session.scalar(
            select(StandardInputCompilation.id).where(
                StandardInputCompilation.sha256 == result["sha256"]
            )
        ):
            session.add(
                StandardInputCompilation(
                    input_id=row.id, model_id=body.model_id, sha256=result["sha256"], payload=result
                )
            )
        return envelope(result, request)
