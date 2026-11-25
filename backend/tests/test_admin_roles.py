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
async def test_role_changes_require_superadmin_live():
    """角色变更收归超管：管理员不能提拔/降级任何人、不能停用管理员；
    超管可任免三角色；最后一位有效超管受保护；降级即时生效（旧会话 403）。"""
    settings = _settings(auth_mode="oauth", oauth_enabled_providers=[], database_url=DATABASE_URL)
    app = _make_app(settings)
    engine, sessions = create_database(settings)
    superadmin, sup_session = await _make_user(
        sessions, "superadmin", login=f"sa-{uuid_lib.uuid4().hex[:6]}"
    )
    admin_a, admin_a_session = await _make_user(
        sessions, "admin", login=f"op-{uuid_lib.uuid4().hex[:6]}"
    )
    admin_b, admin_b_session = await _make_user(sessions, "admin")
    regular, _ = await _make_user(sessions, "regular")
    # 开发库中已有真实超管：临时降为 admin，保证"最后一位超管"场景可复现
    displaced = await _demote_superadmins_except(sessions, [superadmin.id])
    try:
        # —— 管理员矩阵：不可改角色、不可停用管理员，可停用/恢复普通用户 ——
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_session": str(admin_a_session)},
        ) as client:
            denied_promote = await client.patch(
                f"/api/autoeval/v1/admin/users/{regular.id}", json={"role": "admin"}
            )
            assert denied_promote.status_code == 403
            denied_demote = await client.patch(
                f"/api/autoeval/v1/admin/users/{admin_b.id}", json={"role": "regular"}
            )
            assert denied_demote.status_code == 403
            denied_super = await client.patch(
                f"/api/autoeval/v1/admin/users/{admin_b.id}", json={"role": "superadmin"}
            )
            assert denied_super.status_code == 403
            denied_suspend = await client.patch(
                f"/api/autoeval/v1/admin/users/{admin_b.id}", json={"suspended": True}
            )
            assert denied_suspend.status_code == 403
            # 管理员保留的权力：停用/恢复普通用户
            ok_suspend = await client.patch(
                f"/api/autoeval/v1/admin/users/{regular.id}", json={"suspended": True}
            )
            assert ok_suspend.status_code == 200
            assert ok_suspend.json()["data"]["suspended_at"] is not None
            ok_restore = await client.patch(
                f"/api/autoeval/v1/admin/users/{regular.id}", json={"suspended": False}
            )
            assert ok_restore.status_code == 200
            assert ok_restore.json()["data"]["suspended_at"] is None
            # 目标不存在与空更新的错误码
            missing = await client.patch(
                f"/api/autoeval/v1/admin/users/{uuid_lib.uuid4()}", json={"role": "admin"}
            )
            assert missing.status_code == 404
            empty = await client.patch(f"/api/autoeval/v1/admin/users/{regular.id}", json={})
            assert empty.status_code == 422
        # 角色全部未被改动
        async with sessions() as session:
            roles = dict(
                (
                    await session.execute(
                        select(PlatformUser.id, PlatformUser.role).where(
                            PlatformUser.id.in_([regular.id, admin_b.id])
                        )
                    )
                ).all()
            )
        assert roles[admin_b.id] == "admin" and roles[regular.id] == "regular"

        # —— 超管矩阵：任免三角色 + 降级即时生效 + 最后超管保护 ——
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_session": str(sup_session)},
        ) as client:
            promoted = await client.patch(
                f"/api/autoeval/v1/admin/users/{regular.id}", json={"role": "admin"}
            )
            assert promoted.status_code == 200
            assert promoted.json()["data"]["role"] == "admin"
            appointed = await client.patch(
                f"/api/autoeval/v1/admin/users/{admin_b.id}", json={"role": "superadmin"}
            )
            assert appointed.status_code == 200
            assert appointed.json()["data"]["role"] == "superadmin"
            # 仍有一位超管时，可降级另一位超管
            demoted_b = await client.patch(
                f"/api/autoeval/v1/admin/users/{admin_b.id}", json={"role": "regular"}
            )
            assert demoted_b.status_code == 200
            assert demoted_b.json()["data"]["role"] == "regular"
            # 只剩自己一位有效超管：降级 / 停用自己都必须 409
            last_demote = await client.patch(
                f"/api/autoeval/v1/admin/users/{superadmin.id}", json={"role": "admin"}
            )
            assert last_demote.status_code == 409
            assert "最后一个有效超级管理员" in last_demote.json()["error"]["message"]
            last_suspend = await client.patch(
                f"/api/autoeval/v1/admin/users/{superadmin.id}", json={"suspended": True}
            )
            assert last_suspend.status_code == 409
        # 被降级管理员的旧会话立即 403（角色按请求实时校验）
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_session": str(admin_b_session)},
        ) as stale:
            assert (await stale.get("/api/autoeval/v1/admin/users")).status_code == 403
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
        assert audit_rows, "操作必须写入 audit_event"
        role_rows = [
            row
            for row in audit_rows
            if "role" in row.details.get("changes", {})
        ]
        assert role_rows, "角色变更必须写入 audit_event"
        assert role_rows[0].actor == f"github:{superadmin.login}"
        assert role_rows[0].details["changes"]["role"]["to"] == "admin"
    finally:
        await _restore_superadmins(sessions, displaced)
        for uid in (superadmin.id, admin_a.id, admin_b.id, regular.id):
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


async def _demote_superadmins_except(sessions, keep_ids):
    """临时把其余有效超管降为管理员（直改数据库，绕过接口守卫），
    返回被降级的超管 id 列表，便于复现"最后一位超管"场景。"""
    async with sessions() as session:
        rows = (
            (
                await session.execute(
                    select(PlatformUser).where(
                        PlatformUser.role == "superadmin",
                        PlatformUser.suspended_at.is_(None),
                        PlatformUser.id.notin_(keep_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            row.role = "admin"
        await session.commit()
        return [row.id for row in rows]


async def _restore_superadmins(sessions, user_ids):
    async with sessions() as session:
        rows = (
            (await session.execute(select(PlatformUser).where(PlatformUser.id.in_(user_ids))))
            .scalars()
            .all()
        )
        for row in rows:
            row.role = "superadmin"
        await session.commit()
