"""Acceptance-only HTTP budget guard; leaves official agent/scorer source unchanged."""

import functools
import json
import os
import threading
from pathlib import Path


def guarded_send(original, *, limit, max_tokens, model, effort, audit_path):
    counter = 0
    lock = threading.Lock()

    def audit(record):
        path = Path(audit_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record) + "\n")

    @functools.wraps(original)
    async def send(client, request, *args, **kwargs):
        nonlocal counter
        if request.url.host != "api.deepseek.com" or not request.url.path.endswith(
            "/chat/completions"
        ):
            return await original(client, request, *args, **kwargs)
        import httpx

        body = json.loads(request.content)
        with lock:
            valid = (
                body.get("model") == model
                and body.get("max_tokens") == max_tokens
                and body.get("reasoning_effort") == effort
                and (body.get("thinking") or {}).get("type") == "enabled"
            )
            if not valid or counter >= limit:
                audit(
                    {
                        "event": "blocked",
                        "reason": "configuration" if not valid else "request_budget",
                    }
                )
                return httpx.Response(
                    400,
                    request=request,
                    json={
                        "error": {
                            "message": "Acceptance request budget or configuration rejected",
                            "type": "invalid_request_error",
                        }
                    },
                )
            counter += 1
            number = counter
            audit(
                {
                    "event": "request",
                    "number": number,
                    "model": model,
                    "max_tokens": max_tokens,
                    "reasoning_effort": effort,
                }
            )
        try:
            response = await original(client, request, *args, **kwargs)
            audit({"event": "response", "number": number, "status": response.status_code})
            return response
        except Exception:
            audit({"event": "transport_failure", "number": number})
            raise

    return send


if os.getenv("AE_ACCEPTANCE_MAX_REQUESTS"):
    import httpx

    httpx.AsyncClient.send = guarded_send(
        httpx.AsyncClient.send,
        limit=int(os.environ["AE_ACCEPTANCE_MAX_REQUESTS"]),
        max_tokens=int(os.environ["AE_ACCEPTANCE_MAX_OUTPUT_TOKENS"]),
        model=os.environ["AE_ACCEPTANCE_MODEL"],
        effort=os.environ["AE_ACCEPTANCE_EFFORT"],
        audit_path="/logs/agent/budget-audit.jsonl",
    )
