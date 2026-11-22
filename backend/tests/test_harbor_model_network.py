from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def model_network(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "deploy"))
    monkeypatch.setenv("AE_DEEPSWE_MODEL_ORIGIN", "https://model.example")
    import harbor_model_network

    return harbor_model_network


def test_model_origin_is_scoped_to_agent_and_explicit_hosts(model_network):
    def hosts(name, endpoint, config=None):
        return model_network.agent_phase_model_hosts(
            config or {}, name, {"OPENAI_BASE_URL": endpoint}
        )

    assert hosts("mini-swe-agent", "https://model.example/v1") == ["model.example"]
    assert hosts("mini-swe-agent", "https://model.example.untrusted/v1") == []
    assert hosts("mini-swe-agent", "http://model.example") == []
    assert hosts("other-agent", "https://model.example") == []
    assert hosts("mini-swe-agent", "https://model.example", {"extra_allowed_hosts": ["a"]}) == ["a"]


def test_sidecar_resolves_only_a_host_in_the_phase_policy(model_network, monkeypatch):
    calls = []

    def resolve(host, port, family, kind):
        calls.append((host, port))
        return [(family, kind, 6, "", ("192.0.2.1", port))]

    monkeypatch.setattr(model_network.socket, "getaddrinfo", resolve)
    assert model_network.model_host_mapping([SimpleNamespace(allowed_hosts=[])]) == {}
    assert not calls
    policy = SimpleNamespace(allowed_hosts=["model.example"])
    assert model_network.model_host_mapping([policy]) == {"model.example": "192.0.2.1"}
    assert calls == [("model.example", 443)]
