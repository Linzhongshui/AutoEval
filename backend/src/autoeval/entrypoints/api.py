import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from time import perf_counter
from uuid import uuid4

import boto3
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from temporalio.client import Client

from autoeval.analysis import analysis_is_configured
from autoeval.analysis import router as analysis_router
from autoeval.catalog.configuration import router as configuration_router
from autoeval.catalog.datasets import router as datasets_router
from autoeval.catalog.profiles import router as profiles_router
from autoeval.catalog.registry import router as registry_router
from autoeval.catalog.standard_inputs import router as standard_inputs_router
from autoeval.evaluation.evaluation_tasks import router as evaluation_tasks_router
from autoeval.evaluation.evaluations import router as evaluations_router
from autoeval.evaluation.fixture_pipeline import router as fixture_pipeline_router
from autoeval.evaluation.monitored_execution import router as monitored_router
from autoeval.evaluation.runs import router as runs_router
from autoeval.evaluation.task_monitor import router as task_monitor_router
from autoeval.identity import cleanup_expired_identity_rows
from autoeval.identity import router as identity_router
from autoeval.identity.admin import router as admin_router
from autoeval.identity.guards import require_admin, require_user
from autoeval.infrastructure.audit import router as audit_router
from autoeval.infrastructure.config import Settings, get_settings
from autoeval.infrastructure.db import create_database
from autoeval.infrastructure.platform_config import load_config_overlay
from autoeval.planning.routes import router as planning_router
from autoeval.reporting.badcase_export import router as badcase_export_router
from autoeval.reporting.badcases import router as badcase_router
from autoeval.reporting.case_history import router as case_history_router
from autoeval.reporting.data_workbench import router as data_workbench_router
from autoeval.reporting.langfuse_integration import router as langfuse_router
from autoeval.reporting.leaderboards import router as leaderboard_router
from autoeval.reporting.reports import router as reports_router
from autoeval.reporting.unified_outputs import router as unified_outputs_router
from autoeval.resources.docker_bindings import router as resources_router
from autoeval.resources.ssh_resources import router as ssh_resources_router
from autoeval.resources.targets import router as targets_router

request_log = logging.getLogger("autoeval.request")

IDENTITY_CLEANUP_INTERVAL_SECONDS = 3600


async def _identity_cleanup_loop(app: FastAPI) -> None:
    """每小时清理一次过期的 OAuth state 与用户会话行。"""
    while True:
        await asyncio.sleep(IDENTITY_CLEANUP_INTERVAL_SECONDS)
        await cleanup_expired_identity_rows(app.state.sessions)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app):
        app.state.settings = settings
        app.state.engine, app.state.sessions = create_database(settings)
        # 管理员保存的平台配置在启动时叠加到运行时设置（预算开关、归档清单、Langfuse 链接）
        await load_config_overlay(app.state.sessions, settings)
        # 过期登录 state 与会话行：启动即清理一次，此后每小时一轮
        await cleanup_expired_identity_rows(app.state.sessions)
        cleanup_task = asyncio.create_task(_identity_cleanup_loop(app))
        try:
            yield
        finally:
            cleanup_task.cancel()
            with suppress(asyncio.CancelledError):
                await cleanup_task
        await app.state.engine.dispose()

    app = FastAPI(title="AutoEval Backend", version="0.1.0", lifespan=lifespan)
    # 业务入口统一鉴权：user_auth = 需有效会话（本地模式自动放行），
    # admin_auth = 额外要求管理员角色（审计查询、平台级 Langfuse 配置）。
    user_guard = [Depends(require_user)]
    admin_guard = [Depends(require_user), Depends(require_admin)]
    app.include_router(identity_router)
    # 管理接口在路由内自带 require_admin 依赖（需要 Principal 记录审计 actor）
    app.include_router(admin_router)
    app.include_router(data_workbench_router, dependencies=user_guard)
    app.include_router(standard_inputs_router, dependencies=user_guard)
    app.include_router(unified_outputs_router, dependencies=user_guard)
    app.include_router(fixture_pipeline_router, dependencies=user_guard)
    app.include_router(task_monitor_router, dependencies=user_guard)
    app.include_router(monitored_router, dependencies=user_guard)
    app.include_router(planning_router, dependencies=user_guard)
    app.include_router(evaluation_tasks_router, dependencies=user_guard)
    app.include_router(configuration_router, dependencies=user_guard)
    app.include_router(case_history_router, dependencies=user_guard)
    app.include_router(langfuse_router, dependencies=admin_guard)
    app.include_router(datasets_router, dependencies=user_guard)
    app.include_router(profiles_router, dependencies=user_guard)
    app.include_router(registry_router, dependencies=user_guard)
    app.include_router(targets_router, dependencies=user_guard)
    app.include_router(ssh_resources_router, dependencies=user_guard)
    app.include_router(resources_router, dependencies=user_guard)
    app.include_router(runs_router, dependencies=user_guard)
    app.include_router(evaluations_router, dependencies=user_guard)
    app.include_router(leaderboard_router, dependencies=user_guard)
    app.include_router(analysis_router, dependencies=user_guard)
    app.include_router(audit_router, dependencies=admin_guard)
    app.include_router(reports_router, dependencies=user_guard)
    app.include_router(badcase_router, dependencies=user_guard)
    app.include_router(badcase_export_router, dependencies=user_guard)

    @app.middleware("http")
    async def budget_entrypoints(request: Request, call_next):
        if (
            settings.enforce_task_budget
            and settings.billing_execution_config
            and request.method == "POST"
            and request.url.path.rstrip("/")
            in {
                "/api/autoeval/v1/runs",
                "/api/autoeval/v1/aisbench-monitored/runs",
                "/api/autoeval/v1/planning/probes",
            }
        ):
            return JSONResponse(
                {
                    "detail": "Active budget requires the unified evaluation-tasks flow; direct execution and paid probes are disabled"
                },
                status_code=409,
            )
        return await call_next(request)

    @app.middleware("http")
    async def correlation(request: Request, call_next):
        started = perf_counter()
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Server-Timing"] = f"app;dur={(perf_counter() - started) * 1000:.1f}"
        validation_ms = getattr(request.state, "report_validation_ms", None)
        if validation_ms is not None:
            response.headers["Server-Timing"] += f", report_validation;dur={validation_ms:.1f}"
        # One line per request; credentials, prompts and model payloads never appear here.
        request_log.info(
            "request_id=%s method=%s path=%s status=%s",
            request.state.request_id,
            request.method,
            request.url.path,
            response.status_code,
        )
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {"code": "HTTP_ERROR", "message": str(exc.detail)},
                "request_id": request.state.request_id,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(
            status_code=422,
            content={
                "error": {"code": "VALIDATION_ERROR", "message": "Invalid request"},
                "request_id": request.state.request_id,
            },
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        return JSONResponse(
            status_code=500,
            content={
                "error": {"code": "INTERNAL_ERROR", "message": "Internal server error"},
                "request_id": getattr(request.state, "request_id", "unknown"),
            },
        )

    @app.get("/health/live")
    async def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    async def ready(request: Request):
        async def database():
            async with request.app.state.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

        async def temporal():
            client = await Client.connect(
                settings.temporal_address, namespace=settings.temporal_namespace
            )
            await client.service_client.check_health()

        def storage():
            from botocore.config import Config

            client = boto3.client(
                "s3",
                endpoint_url=settings.s3_endpoint,
                aws_access_key_id=settings.s3_access_key.get_secret_value(),
                aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
                config=Config(connect_timeout=2, read_timeout=2, retries={"max_attempts": 0}),
            )
            try:
                client.head_bucket(Bucket=settings.s3_bucket)
            finally:
                client.close()

        async def check(coro):
            try:
                await asyncio.wait_for(coro, settings.dependency_timeout_seconds)
                return "ready"
            except Exception:  # noqa: BLE001 -- readiness isolates third-party dependency failures
                return "unavailable"

        results = await asyncio.gather(
            check(database()), check(temporal()), check(asyncio.to_thread(storage))
        )
        checks = dict(zip(("database", "temporal", "storage"), results))
        return JSONResponse(
            status_code=200 if all(x == "ready" for x in results) else 503,
            content={"checks": checks},
        )

    @app.get("/api/autoeval/v1/system/capabilities")
    async def capabilities(request: Request):
        return {
            "data": {
                "workspace_mode": "single",
                "subject": "local-operator",
                "foundation": True,
                "evaluation_enabled": False,
                "gpqa_exploration_enabled": True,
                "planning_enabled": True,
                "planning_datasets": ["GPQA", "MMMU-Pro", "DeepSWE"],
                "planned_execution_requires_resource_preflight": True,
                "analysis_enabled": analysis_is_configured(settings),
                "data_workbench_enabled": settings.environment in {"development", "test"},
                "aurora_enabled": False,
                "customer_ssh_enabled": True,
                "customer_ssh_scope": "gpqa_lite_exploration",
            },
            "request_id": request.state.request_id,
        }

    return app


app = create_app()
