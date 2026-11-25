"""R08 admin endpoints: user administration, config management and audit trails."""

import os
import uuid as uuid_lib
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import delete, select

from autoeval.entrypoints.api import create_app
from autoeval.identity.models import PlatformUser, UserSession
from autoeval.infrastructure.audit import AuditEvent
from autoeval.infrastructure.config import Settings
from autoeval.infrastructure.db import create_database
from autoeval.infrastructure.platform_config import (
    PlatformConfig,
    load_config_overlay,
)

DATABASE_URL = "postgresql+asyncpg://autoeval:autoeval-dev-pw@127.0.0.1:5432/autoeval"
INFRA_ONLY = pytest.mark.skipif(
    os.getenv("AE_INFRA_TEST") != "1", reason="Requires real PostgreSQL"
)


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def _make_app(settings: Settings):
    app = create_app(settings)
    engine, sessions = create_database(settings)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessions = sessions
    return app


async def test_admin_endpoints_require_session_without_cookie():
    settings = _settings(auth_mode="oauth", oauth_enabled_providers=[])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_make_app(settings)), base_url="http://test"
    ) as client:
        users = await client.get("/api/autoeval/v1/admin/users")
        config = await client.get("/api/autoeval/v1/admin/config")
        patch = await client.patch(
            f"/api/autoeval/v1/admin/users/{uuid_lib.uuid4()}",
            json={"role": "admin"},
        )
    assert users.status_code == 401
    assert config.status_code == 401
    assert patch.status_code == 401


@INFRA_ONLY
async def test_admin_users_regular_forbidden_live():
    settings = _settings(auth_mode="oauth", oauth_enabled_providers=[], database_url=DATABASE_URL)
    app = _make_app(settings)
    engine, sessions = create_database(settings)
    user, session_id = await _make_user(sessions, "regular")
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_session": str(session_id)},
        ) as client:
            users = await client.get("/api/autoeval/v1/admin/users")
            config = await client.get("/api/autoeval/v1/admin/config")
        assert users.status_code == 403
        assert config.status_code == 403
    finally:
        await _cleanup_user(sessions, user.id)
        await engine.dispose()


@INFRA_ONLY
async def test_admin_users_list_search_and_pagination_live():
    settings = _settings(auth_mode="oauth", oauth_enabled_providers=[], database_url=DATABASE_URL)
    app = _make_app(settings)
    engine, sessions = create_database(settings)
    admin, admin_session = await _make_user(sessions, "admin")
    marker = f"needle-{uuid_lib.uuid4().hex[:6]}"
    needle, _ = await _make_user(sessions, "regular", login=marker)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_session": str(admin_session)},
        ) as client:
            all_rows = await client.get("/api/autoeval/v1/admin/users?offset=0&limit=100")
            assert all_rows.status_code == 200
            logins = {row["login"] for row in all_rows.json()["data"]}
            assert admin.login in logins and marker in logins
            assert all_rows.json()["total"] >= 2
            hit = await client.get(f"/api/autoeval/v1/admin/users?limit=100&q={marker}")
            assert hit.status_code == 200
            assert [row["login"] for row in hit.json()["data"]] == [marker]
            assert hit.json()["total"] == 1
            bad_page = await client.get("/api/autoeval/v1/admin/users?limit=0")
            assert bad_page.status_code == 422
    finally:
        await _cleanup_user(sessions, admin.id)
        await _cleanup_user(sessions, needle.id)
        await engine.dispose()


@INFRA_ONLY
async def test_admin_role_update_and_last_admin_protection_live():
    settings = _settings(auth_mode="oauth", oauth_enabled_providers=[], database_url=DATABASE_URL)
    app = _make_app(settings)
    engine, sessions = create_database(settings)
    admin_a, session_a = await _make_user(sessions, "admin", login=f"op-{uuid_lib.uuid4().hex[:6]}")
    admin_b, _ = await _make_user(sessions, "admin")
    regular, _ = await _make_user(sessions, "regular")
    # 开发库中可能存在真实管理员：临时降级其余管理员，保证"最后一位"场景可复现
    displaced = await _demote_admins_except(sessions, [admin_a.id, admin_b.id])
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_session": str(session_a)},
        ) as client:
            # 先降到只剩 admin_a 一位有效管理员
            demoted = await client.patch(
                f"/api/autoeval/v1/admin/users/{admin_b.id}", json={"role": "regular"}
            )
            assert demoted.status_code == 200
            assert demoted.json()["data"]["role"] == "regular"

            # 目标不存在与空更新的错误码（此时 admin_a 仍是管理员）
            missing = await client.patch(
                f"/api/autoeval/v1/admin/users/{uuid_lib.uuid4()}", json={"role": "admin"}
            )
            assert missing.status_code == 404
            empty = await client.patch(f"/api/autoeval/v1/admin/users/{regular.id}", json={})
            assert empty.status_code == 422

            # 此时只剩 admin_a：降级、停用都必须拒绝
            last_demote = await client.patch(
                f"/api/autoeval/v1/admin/users/{admin_a.id}", json={"role": "regular"}
            )
            assert last_demote.status_code == 409
            assert "最后一个有效管理员" in last_demote.json()["error"]["message"]
            last_suspend = await client.patch(
                f"/api/autoeval/v1/admin/users/{admin_a.id}", json={"suspended": True}
            )
            assert last_suspend.status_code == 409
            async with sessions() as session:
                role_still = (
                    await session.execute(
                        select(PlatformUser.role).where(PlatformUser.id == admin_a.id)
                    )
                ).scalar_one()
            assert role_still == "admin"

            # 出现第二位管理员后，原保护解除：提升 regular 再降级 admin_a 均可执行
            promoted = await client.patch(
                f"/api/autoeval/v1/admin/users/{regular.id}", json={"role": "admin"}
            )
            assert promoted.status_code == 200
            assert promoted.json()["data"]["role"] == "admin"
            again = await client.patch(
                f"/api/autoeval/v1/admin/users/{admin_a.id}", json={"role": "regular"}
            )
            assert again.status_code == 200
            assert again.json()["data"]["role"] == "regular"
            # 降级立即生效：原管理员会话再访问管理接口必须 403（角色按请求实时校验）
            stale_admin = await client.get("/api/autoeval/v1/admin/users")
            assert stale_admin.status_code == 403
        # 审计事件必须记录操作人与变更内容
        async with sessions() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditEvent).where(
                            AuditEvent.resource_type == "platform_user",
                            AuditEvent.resource_id == str(regular.id),
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert audit_rows, "角色变更必须写入 audit_event"
        assert audit_rows[0].actor == f"github:{admin_a.login}"
        assert audit_rows[0].details["changes"]["role"]["to"] == "admin"
    finally:
        await _restore_admin_roles(sessions, displaced)
        for uid in (admin_a.id, admin_b.id, regular.id):
            await _cleanup_user(sessions, uid)
        await engine.dispose()


@INFRA_ONLY
async def test_admin_suspend_revokes_sessions_and_restore_live():
    settings = _settings(auth_mode="oauth", oauth_enabled_providers=[], database_url=DATABASE_URL)
    app = _make_app(settings)
    engine, sessions = create_database(settings)
    admin, admin_session = await _make_user(sessions, "admin")
    regular, regular_session = await _make_user(sessions, "regular")
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_session": str(admin_session)},
        ) as client:
            suspended = await client.patch(
                f"/api/autoeval/v1/admin/users/{regular.id}", json={"suspended": True}
            )
            assert suspended.status_code == 200
            assert suspended.json()["data"]["suspended_at"] is not None
        # 停用即吊销会话：旧 Cookie 立刻失效
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_session": str(regular_session)},
        ) as victim:
            me = await victim.get("/api/autoeval/v1/auth/me")
        assert me.status_code == 401
        # 恢复后 suspended_at 清空
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_session": str(admin_session)},
        ) as client:
            restored = await client.patch(
                f"/api/autoeval/v1/admin/users/{regular.id}", json={"suspended": False}
            )
            assert restored.status_code == 200
            assert restored.json()["data"]["suspended_at"] is None
    finally:
        await _cleanup_user(sessions, admin.id)
        await _cleanup_user(sessions, regular.id)
        await engine.dispose()


@INFRA_ONLY
async def test_admin_config_read_write_and_startup_overlay_live():
    settings = _settings(auth_mode="oauth", oauth_enabled_providers=[], database_url=DATABASE_URL)
    app = _make_app(settings)
    engine, sessions = create_database(settings)
    admin, admin_session = await _make_user(sessions, "admin")
    manifest_ids = [str(uuid_lib.uuid4()), str(uuid_lib.uuid4())]
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_session": str(admin_session)},
        ) as client:
            initial = await client.get("/api/autoeval/v1/admin/config")
            assert initial.status_code == 200
            assert initial.json()["data"]["enforce_task_budget"] is False

            saved = await client.put(
                "/api/autoeval/v1/admin/config",
                json={
                    "updates": {
                        "enforce_task_budget": True,
                        "archived_manifest_ids": manifest_ids,
                        "langfuse_browser_url": "http://langfuse.example",
                    }
                },
            )
            assert saved.status_code == 200
            body = saved.json()["data"]
            assert body["enforce_task_budget"] is True
            assert body["archived_manifest_ids"] == manifest_ids
            assert body["langfuse_browser_url"] == "http://langfuse.example"
            # 运行时生效：settings 实例被直接更新（预算中间件在同一对象上读取）
            assert settings.enforce_task_budget is True
            assert [str(u) for u in settings.archived_manifest_ids] == manifest_ids

            bad_key = await client.put(
                "/api/autoeval/v1/admin/config",
                json={"updates": {"s3_bucket": "hacked"}},
            )
            assert bad_key.status_code == 422
            bad_type = await client.put(
                "/api/autoeval/v1/admin/config",
                json={"updates": {"enforce_task_budget": "yes"}},
            )
            assert bad_type.status_code == 422
            bad_uuid = await client.put(
                "/api/autoeval/v1/admin/config",
                json={"updates": {"archived_manifest_ids": ["not-a-uuid"]}},
            )
            assert bad_uuid.status_code == 422
        # 模拟重启：新进程用全新 Settings 启动时从库里重新叠加
        fresh = _settings(auth_mode="oauth", oauth_enabled_providers=[], database_url=DATABASE_URL)
        await load_config_overlay(sessions, fresh)
        assert fresh.enforce_task_budget is True
        assert [str(u) for u in fresh.archived_manifest_ids] == manifest_ids
        # 审计写入（audit_event 不可变，按本次操作人过滤避开历史运行残留）
        async with sessions() as session:
            audit_rows = (
                (
                    await session.execute(
                        select(AuditEvent).where(AuditEvent.resource_type == "platform_config")
                    )
                )
                .scalars()
                .all()
            )
        ours = [row for row in audit_rows if row.actor == f"github:{admin.login}"]
        assert ours, "配置更新必须写入 audit_event"
        assert ours[0].details["updates"]["enforce_task_budget"] is True
    finally:
        async with sessions() as session:
            await session.execute(delete(PlatformConfig))
            await session.commit()
        await _cleanup_user(sessions, admin.id)
        await engine.dispose()


@INFRA_ONLY
async def test_production_maintenance_endpoints_stay_guarded_live():
    """正式环境（oauth）下维护接口不被测试/本地放行：匿名 401、普通用户 403、管理员可执行。"""
    settings = _settings(
        environment="production",
        auth_mode="oauth",
        oauth_enabled_providers=[],
        github_client_id="gid",
        github_client_secret="gsec",
        oauth_redirect_base="https://api.example.com",
        frontend_origin="https://app.example.com",
        database_url=DATABASE_URL,
    )
    app = _make_app(settings)
    engine, sessions = create_database(settings)
    regular, regular_session = await _make_user(sessions, "regular")
    admin, admin_session = await _make_user(sessions, "admin")
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as anon:
            assert (await anon.get("/api/autoeval/v1/admin/users")).status_code == 401
            assert (await anon.get("/api/autoeval/v1/admin/config")).status_code == 401
            assert (await anon.get("/api/autoeval/v1/audit-events")).status_code == 401
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_session": str(regular_session)},
        ) as regular_client:
            assert (await regular_client.get("/api/autoeval/v1/admin/users")).status_code == 403
            assert (await regular_client.get("/api/autoeval/v1/admin/config")).status_code == 403
            assert (await regular_client.get("/api/autoeval/v1/audit-events")).status_code == 403
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_session": str(admin_session)},
        ) as admin_client:
            assert (await admin_client.get("/api/autoeval/v1/admin/users")).status_code == 200
            assert (await admin_client.get("/api/autoeval/v1/admin/config")).status_code == 200
            assert (await admin_client.get("/api/autoeval/v1/audit-events")).status_code == 200
    finally:
        await _cleanup_user(sessions, regular.id)
        await _cleanup_user(sessions, admin.id)
        await engine.dispose()


async def _make_user(sessions, role: str, login: str | None = None):
    session_id = uuid_lib.uuid4()
    async with sessions() as session:
        user = PlatformUser(
            provider="github",
            provider_uid=f"g-{uuid_lib.uuid4().hex[:10]}",
            login=login or f"u-{uuid_lib.uuid4().hex[:8]}",
            display_name="Admin Tester",
            role=role,
        )
        session.add(user)
        await session.flush()
        session.add(
            UserSession(
                id=session_id,
                user_id=user.id,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        await session.commit()
        return user, session_id


async def _cleanup_user(sessions, user_id):
    async with sessions() as session:
        await session.execute(delete(UserSession).where(UserSession.user_id == user_id))
        await session.execute(delete(PlatformUser).where(PlatformUser.id == user_id))
        await session.commit()


async def _demote_admins_except(sessions, keep_ids):
    """临时把其余有效管理员降为普通用户，返回被降级的管理员 id 列表。"""
    async with sessions() as session:
        rows = (
            (
                await session.execute(
                    select(PlatformUser).where(
                        PlatformUser.role == "admin",
                        PlatformUser.suspended_at.is_(None),
                        PlatformUser.id.notin_(keep_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            row.role = "regular"
        await session.commit()
        return [row.id for row in rows]


async def _restore_admin_roles(sessions, user_ids):
    async with sessions() as session:
        rows = (
            (await session.execute(select(PlatformUser).where(PlatformUser.id.in_(user_ids))))
            .scalars()
            .all()
        )
        for row in rows:
            row.role = "admin"
        await session.commit()
