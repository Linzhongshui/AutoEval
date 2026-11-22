"""Model endpoint routing for Harbor phase-scoped network policies."""

import os
import socket
from urllib.parse import urlsplit


def agent_phase_model_hosts(model_cfg, agent_name, env):
    """Use the deployment-approved origin only for MiniSwe's model-call phase."""
    hosts = list(model_cfg.get("extra_allowed_hosts") or [])
    if hosts or agent_name != "mini-swe-agent":
        return hosts
    origin = os.environ.get("AE_DEEPSWE_MODEL_ORIGIN")
    if not origin:
        return hosts
    endpoint = urlsplit(env.get("OPENAI_BASE_URL") or "")
    if (
        endpoint.scheme == "https"
        and endpoint.hostname
        and endpoint.username is None
        and f"https://{endpoint.netloc}" == origin
    ):
        return [endpoint.hostname]
    return hosts


def model_host_mapping(phase_policies):
    """Resolve an approved host in the runner for the sidecar's shared hosts file."""
    origin = os.environ.get("AE_DEEPSWE_MODEL_ORIGIN", "")
    host = urlsplit(origin).hostname
    if not host or not any(host in policy.allowed_hosts for policy in phase_policies):
        return {}
    addresses = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
    return {host: addresses[0][4][0]}
