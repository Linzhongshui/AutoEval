"""Server-only routing to the private budget proxy; never part of public snapshots."""

import copy
import ipaddress
import json
from pathlib import Path
from urllib.parse import urlsplit


def execution_route(settings, run_id, target_id, dataset, section="evaluation"):
    path = getattr(settings, "billing_execution_config", None)
    if not path:
        return None
    config = json.loads(Path(path).read_text())
    grant = next(
        (
            g
            for g in config["grants"]
            if g["target_id"] == str(target_id)
            and g["dataset"] == dataset
            and g["section"] == section
        ),
        None,
    )
    if grant is None:
        raise ValueError("Budget grant missing; direct model fallback forbidden")
    base = config["private_base_url"].rstrip("/")
    parsed = urlsplit(base)
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path
    ):
        raise ValueError("Invalid private gateway address")
    if not ipaddress.ip_address(parsed.hostname).is_private:
        raise ValueError("Budget gateway must use a private IP")
    return {"base_url": base + "/runs/" + str(run_id) + "/v1", "api_key": grant["execution_token"]}


def route_compilation(compilation, route):
    result = copy.deepcopy(compilation)
    params = result["config"]["params"]
    field = "url" if result["config"]["subcommand"] == "llm_accuracy" else "api_base"
    params[field] = route["base_url"]
    if any(key in params for key in ("host_ip", "host_port", "model_overrides")):
        raise ValueError("Alternate model routing must be removed for budgeted execution")
    return result
