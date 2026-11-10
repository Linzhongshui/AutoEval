"""Backup and restore into isolated PostgreSQL/S3 scratch targets."""

import hashlib
import json
import os
import uuid

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from autoeval.backup import create_backup, restore_backup
from autoeval.config import get_settings
from autoeval.datasets import storage

pytestmark = pytest.mark.skipif(
    not os.environ.get("AE_INFRA_TEST") or not os.environ.get("AE_DOCKER_TEST"),
    reason="Live PostgreSQL, Docker and S3 required",
)


async def create_scratch_database(source_url, name):
    engine = create_async_engine(
        make_url(source_url).set(database="postgres").render_as_string(hide_password=False), isolation_level="AUTOCOMMIT"
    )
    try:
        async with engine.connect() as connection:
            await connection.execute(text(f"CREATE DATABASE {name}"))
    finally:
        await engine.dispose()


async def drop_scratch_database(source_url, name):
    engine = create_async_engine(
        make_url(source_url).set(database="postgres").render_as_string(hide_password=False), isolation_level="AUTOCOMMIT"
    )
    try:
        async with engine.connect() as connection:
            await connection.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
    finally:
        await engine.dispose()


async def test_backup_verifies_tampering_then_restores_only_scratch(tmp_path):
    settings = get_settings()
    suffix = uuid.uuid4().hex
    database = "autoeval_scratch_" + suffix
    bucket = "autoeval-scratch-" + suffix
    source_key = "integration/backup-" + suffix
    source_body = b"immutable-backup-evidence"
    source_url = settings.database_url.get_secret_value()
    target_url = make_url(source_url).set(database=database).render_as_string(hide_password=False)
    target = settings.model_copy(
        update={"database_url": SecretStr(target_url), "s3_bucket": bucket}
    )
    client = storage(settings)
    await create_scratch_database(source_url, database)
    client.create_bucket(Bucket=bucket)
    client.put_object(Bucket=settings.s3_bucket, Key=source_key, Body=source_body)
    try:
        summary = await create_backup(
            settings, tmp_path / "backup", "autoeval-demo-postgres-1"
        )
        manifest_path = tmp_path / "backup" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        async with create_async_engine(source_url).connect() as connection:
            source_version = (await connection.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
        assert manifest["alembic_version"] == source_version
        backed_up = next(item for item in manifest["objects"] if item["key"] == source_key)
        assert backed_up["size"] == len(source_body)
        assert backed_up["sha256"] == hashlib.sha256(source_body).hexdigest()
        assert hashlib.sha256((tmp_path / "backup" / "database.sql").read_bytes()).hexdigest() == manifest["database_dump"]["sha256"]
        assert summary["object_count"] >= 1

        object_path = tmp_path / "backup" / backed_up["path"]
        original = object_path.read_bytes()
        object_path.write_bytes(b"tampered")
        with pytest.raises(ValueError, match="integrity"):
            await restore_backup(target, manifest_path, "autoeval-demo-postgres-1")
        async with create_async_engine(target_url).connect() as connection:
            tables = (await connection.execute(text("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"))).scalar_one()
        assert tables == 0
        assert client.list_objects_v2(Bucket=bucket).get("KeyCount", 0) == 0

        object_path.write_bytes(original)
        restored = await restore_backup(target, manifest_path, "autoeval-demo-postgres-1")
        assert restored["alembic_version"] == source_version
        response = client.get_object(Bucket=bucket, Key=source_key)
        try:
            assert response["Body"].read() == source_body
        finally:
            response["Body"].close()
        async with create_async_engine(target_url).connect() as connection:
            actions = (await connection.execute(text("SELECT action FROM audit_event WHERE action = 'backup.restore'"))).scalars().all()
        assert actions == ["backup.restore"]
    finally:
        client.delete_object(Bucket=settings.s3_bucket, Key=source_key)
        response = client.list_objects_v2(Bucket=bucket)
        for item in response.get("Contents", []):
            client.delete_object(Bucket=bucket, Key=item["Key"])
        client.delete_bucket(Bucket=bucket)
        client.close()
        await drop_scratch_database(source_url, database)
