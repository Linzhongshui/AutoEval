"""Fixed SSH host-side probe; only its outcome is sent back to the platform."""

import http.client
import json
import sys
from urllib.parse import urlsplit


def check(base_url, model, key):
    url = urlsplit(base_url)
    conn = http.client.HTTPSConnection(url.hostname, url.port, timeout=8)
    try:
        conn.request(
            "GET", url.path.rstrip("/") + "/models", headers={"Authorization": "Bearer " + key}
        )
        response = conn.getresponse()
        if response.status != 200:
            return "upstream_error", {"http_status": response.status}
        raw = response.read(1048577)
        if len(raw) > 1048576:
            return "invalid_response", {"reason": "response_too_large"}
        models = json.loads(raw)["data"]
        if not isinstance(models, list) or not all(
            isinstance(item, dict) and isinstance(item.get("id"), str) for item in models
        ):
            return "invalid_response", {"reason": "invalid_model_list"}
        return ("matched" if any(item["id"] == model for item in models) else "model_not_found"), {}
    except (OSError, http.client.HTTPException):
        return "connection_error", {}
    except (ValueError, KeyError, TypeError):
        return "invalid_response", {"reason": "invalid_model_list"}
    finally:
        conn.close()


if __name__ == "__main__":
    print(json.dumps(check(*json.load(sys.stdin))))
