"""Private OpenAI proxy: credentials stay here, budget commits precede network I/O."""

import asyncio
import hashlib
import json
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import select

from autoeval.billing import BudgetAccount, ModelPrice, TargetBilling
from autoeval.billing_ledger import BudgetBlocked, finish_request, recover_inflight, reserve_request
from autoeval.config import get_settings
from autoeval.db import create_database
from autoeval.models import EvaluationRun
from autoeval.secrets import FileSecretStore
from autoeval.targets import TargetBinding, validate_url


async def forward_once(request, client, url, key, body):
    call = asyncio.create_task(
        client.post(url, headers={"Authorization": "Bearer " + key}, json=body)
    )

    async def disconnected():
        while not await request.is_disconnected():
            await asyncio.sleep(0.2)

    watch = asyncio.create_task(disconnected())
    try:
        done, _ = await asyncio.wait({call, watch}, return_when=asyncio.FIRST_COMPLETED)
        if call in done:
            return await call
        raise httpx.RequestError("client_disconnected_upstream_outcome_unknown")
    finally:
        for pending in (call, watch):
            if not pending.done():
                pending.cancel()
        await asyncio.gather(call, watch, return_exceptions=True)


def create_gateway(config_path):
    """Config is a private file: hashed scoped tokens, IDs, deadline, max token bounds."""
    settings = get_settings()
    engine, sessions = create_database(settings)

    @asynccontextmanager
    async def lifespan(app):
        config = json.loads(Path(config_path).read_text())
        async with sessions() as db, db.begin():
            await recover_inflight(db, uuid.UUID(config["budget_id"]))
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    app.state.accounting_failed = False

    @app.exception_handler(Exception)
    async def accounting_failure(request, exc):
        app.state.accounting_failed = True
        return JSONResponse({"detail": "budget_proxy_requires_recovery"}, status_code=503)

    @app.get("/health/live")
    async def live():
        return {"state": "ready"}

    @app.get("/health/ready")
    async def ready():
        from sqlalchemy import text

        async with sessions() as db:
            await db.execute(text("SELECT 1"))
        return {"state": "ready"}

    @app.post("/runs/{run_id}/v1/chat/completions")
    async def completion(run_id: uuid.UUID, request: Request):
        if app.state.accounting_failed:
            raise HTTPException(503, "budget_proxy_requires_recovery")
        config = json.loads(Path(config_path).read_text())
        authorization = request.headers.get("Authorization", "")
        token = authorization.removeprefix("Bearer ")
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        grant = next(
            (g for g in config["grants"] if secrets.compare_digest(g["token_sha256"], token_hash)),
            None,
        )
        if grant is None or not authorization.startswith("Bearer "):
            raise HTTPException(401, "invalid_execution_token")
        if datetime.now(UTC) >= datetime.fromisoformat(config["deadline"]):
            raise HTTPException(403, "execution_deadline_exceeded")
        raw = await request.body()
        if len(raw) > 12 * 1024 * 1024:
            raise HTTPException(413, "request_too_large")
        body = json.loads(raw)
        maximum = body.get("max_completion_tokens", body.get("max_tokens"))
        if (
            type(maximum) is not int
            or not 1 <= maximum <= grant["max_output_tokens"]
            or body.get("n", 1) != 1
            or not isinstance(body.get("messages"), list)
        ):
            raise HTTPException(422, "explicit_single_completion_bound_required")
        if any(t.get("type", "function") != "function" for t in body.get("tools", [])):
            raise HTTPException(422, "unpriced_builtin_tool_disabled")
        async with sessions() as db:
            run = await db.get(EvaluationRun, run_id)
            if run is None or run.cancel_requested_at is not None:
                raise HTTPException(403, "run_not_executable")
            if grant["section"] == "evaluation" and run.state in (
                "completed",
                "failed",
                "cancelled",
            ):
                raise HTTPException(403, "run_not_executable")
            if grant["section"] == "analysis":
                from autoeval.analysis import ReportAnalysis

                job = await db.scalar(
                    select(ReportAnalysis).where(
                        ReportAnalysis.run_id == run_id, ReportAnalysis.state == "running"
                    )
                )
                if run.state != "completed" or job is None:
                    raise HTTPException(403, "analysis_not_executable")
            from autoeval.models import RunSnapshot
            from autoeval.standard_inputs import digest

            snapshot = await db.scalar(select(RunSnapshot).where(RunSnapshot.run_id == run_id))
            if snapshot is None or digest(snapshot.canonical_body) != snapshot.sha256:
                raise HTTPException(403, "snapshot_integrity_failed")
            inputs = snapshot.canonical_body.get("inputs", {})
            expected = config.get("expected_scope")
            if expected:
                tasks = inputs.get("tasks", [])
                if (
                    {t["dataset"]: len(t.get("samples", [])) for t in tasks} != expected
                    or any(
                        t.get("concurrency") != 24 or t.get("subset_scope") != "full" for t in tasks
                    )
                    or snapshot.canonical_body.get("execution_origin") != "real"
                ):
                    raise HTTPException(403, "authorized_full_scope_mismatch")
            if grant["section"] == "evaluation" and (
                inputs.get("target_id") != grant["target_id"]
                or grant["dataset"] not in {t["dataset"] for t in inputs.get("tasks", [])}
            ):
                raise HTTPException(403, "run_grant_mismatch")
            target = await db.get(TargetBinding, uuid.UUID(grant["target_id"]))
            binding = await db.scalar(
                select(TargetBilling).where(TargetBilling.target_id == target.id)
            )
            price = await db.get(ModelPrice, binding.price_id)
            if (
                body.get("model") != target.remote_model
                or str(binding.budget_id) != config["budget_id"]
            ):
                raise HTTPException(403, "model_or_budget_mismatch")
            rates, base, credential_ref = (
                {**price.rates, "price_id": str(price.id), "source_sha256": price.source_sha256},
                validate_url(target.base_url, settings.allowed_model_hosts),
                target.credential_ref,
            )
        request_key = hashlib.sha256(
            json.dumps(
                [str(run_id), grant["section"], grant["dataset"], body],
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        while True:
            if await request.is_disconnected():
                raise HTTPException(499, "client_disconnected_before_reservation")
            if datetime.now(UTC) >= datetime.fromisoformat(config["deadline"]):
                raise HTTPException(403, "execution_deadline_exceeded")
            try:
                async with sessions() as db, db.begin():
                    reservation = await reserve_request(
                        db,
                        budget_id=uuid.UUID(config["budget_id"]),
                        run_id=run_id,
                        request_key=request_key,
                        section=grant["section"],
                        dataset=grant["dataset"],
                        input_bound=grant["max_input_tokens"],
                        output_bound=maximum,
                        rates=rates,
                        concurrency=grant["concurrency"],
                    )
                break
            except BudgetBlocked as exc:
                if str(exc) == "concurrency_full":
                    await asyncio.sleep(0.2)
                    continue
                if str(exc) == "budget_exhausted":
                    async with sessions() as db:
                        account = await db.get(BudgetAccount, uuid.UUID(config["budget_id"]))
                        waiting = account and account.state == "active" and account.reserved > 0
                    if waiting:
                        await asyncio.sleep(0.2)
                        continue
                raise HTTPException(402, str(exc)) from None
        usage = None
        try:
            key = FileSecretStore(settings.secret_store_path).get(credential_ref)
            caller_usage = bool(body.get("stream_options", {}).get("include_usage"))
            if body.get("stream"):
                body["stream_options"] = {**body.get("stream_options", {}), "include_usage": True}
            remaining = (
                datetime.fromisoformat(config["deadline"]) - datetime.now(UTC)
            ).total_seconds()
            timeout = min(max(remaining, 0.1), grant.get("request_timeout_seconds", 86400))
            if body.get("stream"):
                from autoeval.billing_stream import relay_stream

                return StreamingResponse(
                    relay_stream(
                        sessions,
                        reservation,
                        rates,
                        base,
                        key,
                        body,
                        httpx.Timeout(timeout, connect=10),
                        caller_usage,
                        lambda: setattr(app.state, "accounting_failed", True),
                    ),
                    media_type="text/event-stream",
                )
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout, connect=10), follow_redirects=False
            ) as client:
                # Deliberately no retry; buffer SSE to capture final usage before returning.
                upstream = await forward_once(
                    request, client, base.rstrip("/") + "/chat/completions", key, body
                )
            if upstream.status_code != 200:
                usage = {"error_code": "upstream_http_" + str(upstream.status_code)}
            if upstream.status_code == 200:
                if body.get("stream"):
                    for line in upstream.text.splitlines():
                        if line.startswith("data: ") and line != "data: [DONE]":
                            event = json.loads(line[6:])
                            if event.get("usage"):
                                usage = event["usage"]
                else:
                    usage = upstream.json().get("usage")
        except asyncio.CancelledError:

            async def retain_unknown():
                async with sessions() as db, db.begin():
                    await finish_request(db, reservation, None, rates)

            await asyncio.shield(retain_unknown())
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError, OSError):
            async with sessions() as db, db.begin():
                await finish_request(db, reservation, None, rates)
            raise HTTPException(502, "upstream_outcome_unknown_budget_blocked") from None
        async with sessions() as db, db.begin():
            state = await finish_request(db, reservation, usage, rates)
        if state != "settled":
            raise HTTPException(502, "usage_unknown_budget_blocked")
        return Response(
            upstream.content,
            status_code=upstream.status_code,
            media_type="text/event-stream" if body.get("stream") else "application/json",
        )

    app.state.engine = engine
    return app


if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run(
        create_gateway(os.environ["AE_BILLING_EXECUTION_CONFIG"]),
        host="0.0.0.0",
        port=18080,
        access_log=False,
    )
