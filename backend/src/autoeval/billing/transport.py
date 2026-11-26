"""Server-only routing to the private budget proxy; never part of public snapshots."""

import copy
import ipaddress
import json
from pathlib import Path
from urllib.parse import urlsplit


def authorized_scope(config, snapshot):
    expected = config.get("expected_scope")
    if not expected:
        return True
    concurrency = config.get("expected_concurrency", 24)
    subset = config.get("expected_subset_scope", "full")
    tasks = snapshot.get("inputs", {}).get("tasks", [])
    return (
        type(concurrency) is int
        and concurrency >= 1
        and subset in {"lite", "full"}
        and len(tasks) == len(expected)
        and {task["dataset"]: len(task.get("samples", [])) for task in tasks} == expected
        and all(
            task.get("concurrency") == concurrency and task.get("subset_scope") == subset
            for task in tasks
        )
        and snapshot.get("execution_origin") == "real"
    )


def execution_route(settings, run_id, target_id, dataset, section="evaluation", *, ignore_budget=False):
    if ignore_budget:
        return None
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
    if result["config"]["subcommand"] == "llm_accuracy":
        # AISBench appends v1/chat/completions to this URL itself.
        params["url"] = route["base_url"].removesuffix("/v1")
    else:
        upstream = urlsplit(params.get("api_base") or "").hostname
        gateway = urlsplit(route["base_url"]).hostname
        hosts = [host for host in params.get("extra_allowed_hosts", []) if host.lower() != upstream]
        if gateway and gateway not in {host.lower() for host in hosts}:
            hosts.append(gateway)
        params["extra_allowed_hosts"] = hosts
        params["api_base"] = route["base_url"]
    if any(key in params for key in ("host_ip", "host_port", "model_overrides")):
        raise ValueError("Alternate model routing must be removed for budgeted execution")
    return result


def budget_ignored(snapshot):
    return ((snapshot.get('model_budget') or {}).get('mode') == 'ignored'
            and (snapshot.get('inputs') or {}).get('ignore_budget') is True)
