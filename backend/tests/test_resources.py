import json
import subprocess

import pytest

from autoeval.resources import RegisterExecutor, inspect_executor


def test_inspect_does_not_return_secret_environment(monkeypatch):
    metadata = [
        {
            "Id": "container",
            "Image": "image",
            "State": {"Running": True},
            "Config": {"Labels": {"autoeval.role": "executor"}, "Env": ["KEY=placeholder"]},
        }
    ]
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 0, stdout=json.dumps(metadata).encode()
        ),
    )
    result = inspect_executor("docker", "container")
    assert result == {"container_id": "container", "image_id": "image", "running": True}


def test_unmanaged_container_is_rejected(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, stdout=b'[{"Config":{}}]'),
    )
    with pytest.raises(ValueError):
        inspect_executor("docker", "other")


def test_cli_options_cannot_be_injected():
    with pytest.raises(ValueError):
        RegisterExecutor(binding_key="safe", container_name="--privileged")
