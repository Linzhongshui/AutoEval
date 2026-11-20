"""Relay OpenAI SSE live; withhold DONE until usage has been committed."""

import asyncio
import json

import httpx
from sqlalchemy.exc import SQLAlchemyError

from autoeval.billing.ledger import finish_request


async def relay_stream(
    sessions, reservation, rates, base, key, body, timeout, include_usage, accounting_failed
):
    usage = None
    done_frame = None
    error_code = "stream_outcome_unknown"
    try:
        async with (
            httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client,
            client.stream(
                "POST",
                base.rstrip("/") + "/chat/completions",
                headers={"Authorization": "Bearer " + key},
                json=body,
            ) as response,
        ):
            if response.status_code != 200:
                error_code = "upstream_http_" + str(response.status_code)
                raise httpx.RequestError(error_code)
            frame = []
            async for line in response.aiter_lines():
                if line:
                    frame.append(line)
                    if sum(len(x) for x in frame) > 12 * 1024 * 1024:
                        raise ValueError("stream_frame_too_large")
                    continue
                if not frame:
                    continue
                wire = ("\n".join(frame) + "\n\n").encode()
                data = "\n".join(x[5:].lstrip() for x in frame if x.startswith("data:"))
                frame = []
                if data == "[DONE]":
                    done_frame = wire
                    continue
                event = json.loads(data) if data else {}
                if event.get("usage"):
                    usage = event["usage"]
                if not include_usage and event.get("usage") and event.get("choices") == []:
                    continue
                yield wire
        if done_frame is None:
            raise ValueError("stream_completion_marker_missing")
        async with sessions() as db, db.begin():
            state = await finish_request(db, reservation, usage, rates)
        if state != "settled":
            raise ValueError("stream_usage_unknown_budget_blocked")
        yield done_frame
    except BaseException:

        async def retain():
            try:
                async with sessions() as db, db.begin():
                    await finish_request(db, reservation, {"error_code": error_code}, rates)
            except (SQLAlchemyError, TimeoutError, OSError, ValueError):
                accounting_failed()

        await asyncio.shield(retain())
        raise
