"""R08 acceptance: report visibility across entrances and review governance.

权限矩阵约定：普通用户对报告/榜单只读（列表、详情、按任务三个入口一致可见）；
审核（approve）与撤销（revoke/withdraw）等治理操作仅管理员可执行，无权调用
必须返回 403 且审核状态保持原值。
"""

import os
import uuid as uuid_lib
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import delete, select

from autoeval.entrypoints.api import create_app
from autoeval.evaluation.models import EvaluationReport
from autoeval.identity.models import PlatformUser, UserSession
from autoeval.infrastructure.config import Settings
from autoeval.infrastructure.db import create_database
from autoeval.infrastructure.models import EvaluationRun

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


async def _make_user(sessions, role: str):
    session_id = uuid_lib.uuid4()
    async with sessions() as session:
        user = PlatformUser(
            provider="github",
            provider_uid=f"g-{uuid_lib.uuid4().hex[:10]}",
            login=f"u-{uuid_lib.uuid4().hex[:8]}",
            display_name="Report Tester",
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


@INFRA_ONLY
async def test_report_visibility_consistent_across_entrances_live():
    """普通账号从报告列表、报告详情、按任务查询三个入口读取同一份报告，结果一致；
    匿名访问三个入口均返回 401。"""
    settings = _settings(auth_mode="oauth", oauth_enabled_providers=[], database_url=DATABASE_URL)
    app = _make_app(settings)
    engine, sessions = create_database(settings)
    regular, regular_session = await _make_user(sessions, "regular")
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as anon:
            assert (await anon.get("/api/autoeval/v1/reports")).status_code == 401
            assert (
                await anon.get(f"/api/autoeval/v1/reports/{uuid_lib.uuid4()}")
            ).status_code == 401
            assert (await anon.get(f"/api/autoeval/v1/runs/{uuid_lib.uuid4()}")).status_code == 401
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_session": str(regular_session)},
        ) as client:
            listing = await client.get("/api/autoeval/v1/reports?limit=5&offset=0")
            assert listing.status_code == 200
            rows = listing.json()["data"]
            if not rows:
                pytest.skip("开发库暂无归档报告，跳过三入口一致性核对")
            picked = rows[0]
            detail = await client.get(f"/api/autoeval/v1/reports/{picked['id']}")
            assert detail.status_code == 200
            detail_body = detail.json()["data"]
            # 列表与详情对同一报告的关键字段一致
            assert detail_body["id"] == picked["id"]
            assert detail_body["run_id"] == picked["run_id"]
            assert detail_body["review_status"] == picked["review_status"]
            assert detail_body["remote_model"] == picked["remote_model"]
            # 按任务查询入口：任务列表可读，任务详情指向同一 run
            runs = await client.get("/api/autoeval/v1/runs?limit=5&offset=0")
            assert runs.status_code == 200
            run_detail = await client.get(f"/api/autoeval/v1/runs/{picked['run_id']}")
            assert run_detail.status_code == 200
            assert run_detail.json()["data"]["id"] == picked["run_id"]
    finally:
        await _cleanup_user(sessions, regular.id)
        await engine.dispose()


@INFRA_ONLY
async def test_report_review_requires_admin_and_keeps_state_live():
    """普通用户审核报告 → 403 且状态不变；管理员获准审核与撤销均生效。"""
    settings = _settings(auth_mode="oauth", oauth_enabled_providers=[], database_url=DATABASE_URL)
    app = _make_app(settings)
    engine, sessions = create_database(settings)
    regular, regular_session = await _make_user(sessions, "regular")
    admin, admin_session = await _make_user(sessions, "admin")
    try:
        async with sessions() as session:
            candidate = (
                await session.execute(
                    select(EvaluationReport, EvaluationRun)
                    .join(EvaluationRun, EvaluationRun.id == EvaluationReport.run_id)
                    .where(
                        EvaluationReport.review_status == "pending",
                        EvaluationReport.execution_origin == "real",
                        EvaluationReport.validity == "complete",
                        EvaluationRun.state == "completed",
                    )
                    .order_by(EvaluationReport.created_at.desc())
                    .limit(1)
                )
            ).first()
        if candidate is None:
            pytest.skip("开发库暂无待审核的真实完整报告")
        report, _ = candidate
        # 普通用户无权审核：403，状态保持 pending
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_session": str(regular_session)},
        ) as client:
            denied = await client.post(
                f"/api/autoeval/v1/reports/{report.id}/review",
                json={"decision": "approve", "note": None},
            )
        assert denied.status_code == 403
        async with sessions() as session:
            still = (
                await session.execute(
                    select(EvaluationReport.review_status).where(EvaluationReport.id == report.id)
                )
            ).scalar_one()
        assert still == "pending"
        # 管理员获准操作生效：审核通过后撤销
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_session": str(admin_session)},
        ) as client:
            approved = await client.post(
                f"/api/autoeval/v1/reports/{report.id}/review",
                json={"decision": "approve", "note": "评审验收通过"},
            )
        if approved.status_code == 409 and "verified" in str(approved.json()):
            pytest.skip("该报告证据未通过完整性校验，管理员审核无法在当前环境生效")
        assert approved.status_code == 200
        assert approved.json()["data"]["review_status"] == "approved"
        assert approved.json()["data"]["reviewed_by"] == f"github:{admin.login}"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_session": str(admin_session)},
        ) as client:
            revoked = await client.post(
                f"/api/autoeval/v1/reports/{report.id}/review",
                json={"decision": "revoke", "note": "评审验收撤销"},
            )
        assert revoked.status_code == 200
        assert revoked.json()["data"]["review_status"] == "revoked"
    finally:
        await _cleanup_user(sessions, regular.id)
        await _cleanup_user(sessions, admin.id)
        await engine.dispose()


@INFRA_ONLY
async def test_workbench_governance_requires_admin_live():
    """榜单条目录入/编辑/审核为治理操作：普通用户 403，管理员进入业务逻辑。"""
    settings = _settings(auth_mode="oauth", oauth_enabled_providers=[], database_url=DATABASE_URL)
    app = _make_app(settings)
    engine, sessions = create_database(settings)
    regular, regular_session = await _make_user(sessions, "regular")
    admin, admin_session = await _make_user(sessions, "admin")
    random_entry = uuid_lib.uuid4()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_session": str(regular_session)},
        ) as client:
            denied_review = await client.post(
                f"/api/autoeval/v1/data-workbench/entries/{random_entry}/review",
                json={"action": "approve", "expected_revision": 1, "reason": "尝试审核"},
            )
            denied_create = await client.post(
                "/api/autoeval/v1/data-workbench/entries",
                json={
                    "source_key": f"official:{uuid_lib.uuid4().hex[:8]}",
                    "source_type": "official",
                    "model_name": "m",
                    "dataset": "GPQA",
                    "metric": "accuracy",
                    "value": 0.5,
                    "scope": "full",
                    "direction": "higher_is_better",
                    "unit": "%",
                    "conditions": {},
                    "source_sha256": "",
                    "source_version": "",
                },
            )
        assert denied_review.status_code == 403
        assert denied_create.status_code == 403
        # 管理员守卫通过后进入业务逻辑（随机 id → 404），而非被角色守卫拦截
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies={"ae_session": str(admin_session)},
        ) as client:
            admin_result = await client.post(
                f"/api/autoeval/v1/data-workbench/entries/{random_entry}/review",
                json={"action": "approve", "expected_revision": 1, "reason": "尝试审核"},
            )
        assert admin_result.status_code == 404
    finally:
        await _cleanup_user(sessions, regular.id)
        await _cleanup_user(sessions, admin.id)
        await engine.dispose()
