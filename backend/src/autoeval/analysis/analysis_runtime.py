"""Single OpenAI-compatible analysis request, isolated from benchmark execution."""

import json
import sys

import httpx

from autoeval.resources.targets import validate_url


def analyze(payload, *, transport=None):
    if payload.get('budget_proxy'):
        import ipaddress
        from urllib.parse import urlsplit
        parsed = urlsplit(payload['base_url'])
        address = ipaddress.ip_address(parsed.hostname)
        if (parsed.scheme != 'http' or not address.is_private or parsed.username
                or parsed.password or parsed.query or parsed.fragment
                or not parsed.path.startswith('/runs/') or not parsed.path.endswith('/v1')):
            raise ValueError('Invalid private budget proxy')
        base = payload['base_url'].rstrip('/')
    else:
        base = validate_url(payload["base_url"], payload["allowed_hosts"])
    maximum = payload["max_tokens"]
    if type(maximum) is not int or not 1 <= maximum <= 4096:
        raise ValueError("Analysis output budget exceeded")
    prompt = payload["prompt"]
    if not isinstance(prompt, str) or not prompt or len(prompt.encode()) > 12 * 1024 * 1024:
        raise ValueError("Invalid analysis prompt")
    # No retries or redirects, including transport failures with an unknown outcome.
    with httpx.Client(timeout=180, follow_redirects=False, transport=transport,
                      trust_env=not payload.get('budget_proxy', False)) as client:
        response = client.post(
            base + "/chat/completions",
            headers={"Authorization": "Bearer " + payload["api_key"]},
            json={
                "model": payload["model"],
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": maximum,
                "temperature": 0,
                "thinking": {"type": "disabled"},
            },
        )
        if response.status_code != 200:
            return {
                "state": "failed",
                "error_code": "ANALYSIS_UPSTREAM_ERROR",
                "response": None,
                "finish_reason": None,
                "usage": None,
            }
        body = response.json()
    choices = body.get("choices", [])
    if len(choices) != 1 or not isinstance(choices[0].get("message", {}).get("content"), str):
        raise ValueError("Invalid analysis completion")
    content = choices[0]["message"]["content"]
    usage = body.get("usage") or {}
    return {
        "state": "succeeded" if content else "failed",
        "response": content,
        "finish_reason": choices[0].get("finish_reason"),
        "error_code": None if content else "ANALYSIS_EMPTY_RESPONSE",
        "usage": {
            "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
        },
    }


if __name__ == "__main__":
    try:
        request = json.loads(sys.stdin.buffer.read(16 * 1024 * 1024 + 1))
        result = analyze(request)
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        # Never print upstream bodies, request arguments or secrets to executor logs.
        result = {
            "state": "unresolved",
            "error_code": "ANALYSIS_REQUEST_UNRESOLVED",
            "response": None,
            "usage": None,
            "finish_reason": None,
        }
    print(json.dumps(result))
