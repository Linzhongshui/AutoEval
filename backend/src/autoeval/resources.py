"""Local Docker executor registration. No arbitrary commands or daemon mutation API."""

import asyncio
import json
import subprocess
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column

from autoeval.models import Base, Record


class ResourceProvider(Record, Base):
    __tablename__ = "resource_provider"
    name: Mapped[str] = mapped_column(String(128), unique=True)
    kind: Mapped[str] = mapped_column(String(32))


class ResourceBinding(Record, Base):
    __tablename__ = "resource_binding_version"
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resource_provider.id", ondelete="RESTRICT")
    )
    binding_key: Mapped[str] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(Integer)
    container_id: Mapped[str] = mapped_column(String(64))
    image_id: Mapped[str] = mapped_column(String(128))
    __table_args__ = (UniqueConstraint("binding_key", "version"),)


def inspect_executor(executable: str, container: str) -> dict:
    result = subprocess.run(
        [executable, "inspect", "--type", "container", container],
        capture_output=True,
        timeout=10,
        check=True,
    )
    metadata = json.loads(result.stdout)[0]
    if metadata.get("Config", {}).get("Labels", {}).get("autoeval.role") != "executor":
        raise ValueError("Container is not an AutoEval executor")
    # Persist only safe identity fields, never Config.Env or credential-bearing command lines.
    return {
        "container_id": metadata["Id"],
        "image_id": metadata["Image"],
        "running": bool(metadata.get("State", {}).get("Running")),
    }


class RegisterExecutor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    binding_key: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,128}$")
    container_name: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")


router = APIRouter(prefix="/api/autoeval/v1/resources", tags=["resources"])


@router.post("/docker-bindings", status_code=201)
async def register_executor(body: RegisterExecutor, request: Request):
    try:
        observation = await asyncio.to_thread(
            inspect_executor, request.app.state.settings.docker_executable, body.container_name
        )
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
        raise HTTPException(422, "Executor missing, unmanaged, or Docker unavailable") from exc
    if not observation["running"]:
        raise HTTPException(409, "Executor container is not running")
    try:
        async with request.app.state.sessions() as session, session.begin():
            provider = await session.scalar(
                select(ResourceProvider).where(ResourceProvider.name == "local-docker")
            )
            if provider is None:
                provider = ResourceProvider(name="local-docker", kind="docker_local")
                session.add(provider)
                await session.flush()
            binding = ResourceBinding(
                provider_id=provider.id,
                binding_key=body.binding_key,
                version=1,
                container_id=observation["container_id"],
                image_id=observation["image_id"],
            )
            session.add(binding)
            await session.flush()
            data = {"id": str(binding.id), **observation, "tools_validated": False}
    except IntegrityError as exc:
        raise HTTPException(409, "Binding exists; existing revision preserved") from exc
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Resource database unavailable") from exc
    return {"data": data, "request_id": request.state.request_id}


@router.get("")
async def list_resources(request: Request, offset: int = 0, limit: int = 200):
    if offset < 0 or not 1 <= limit <= 200:
        raise HTTPException(422, "Invalid pagination")
    try:
        async with request.app.state.sessions() as session:
            rows = (
                await session.scalars(
                    select(ResourceBinding)
                    .order_by(ResourceBinding.created_at.desc(), ResourceBinding.id.desc())
                    .offset(offset)
                    .limit(limit + 1)
                )
            ).all()
            data = [
                {
                    "id": str(row.id),
                    "binding_key": row.binding_key,
                    "version": row.version,
                    "container_id": row.container_id,
                    "image_id": row.image_id,
                    "tools_validated": False,
                }
                for row in rows[:limit]
            ]
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Resource database unavailable") from exc
    return {
        "data": data,
        "next_offset": offset + limit if len(rows) > limit else None,
        "request_id": request.state.request_id,
    }


@router.post("/{binding_id}/validate")
async def validate_resource(binding_id: uuid.UUID, request: Request):
    try:
        async with request.app.state.sessions() as session:
            binding = await session.get(ResourceBinding, binding_id)
            if binding is None:
                raise HTTPException(404, "Resource binding not found")
            expected_image = binding.image_id
            container_id = binding.container_id
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Resource database unavailable") from exc
    try:
        current = await asyncio.to_thread(
            inspect_executor, request.app.state.settings.docker_executable, container_id
        )
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
        raise HTTPException(409, "Executor unavailable or no longer managed") from exc
    valid = current["running"] and current["image_id"] == expected_image
    return {
        "data": {"environment_ready": valid, "tools_validated": False, "evaluation_ready": False},
        "request_id": request.state.request_id,
    }
