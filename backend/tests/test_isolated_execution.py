from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from autoeval.evaluation.evaluation_tasks import SubmitTask
from autoeval.planning.planning_transport import IsolatedPlanningContainer, execution_template


@pytest.mark.parametrize(
    ("subcommand", "tool"),
    [
        ("llm_accuracy", "aisbench"),
        ("harbor_agent", "harbor"),
        ("peir", "peir"),
        ("agentx", "agentx"),
    ],
)
def test_template_requires_selected_node_to_offer_exact_tool_revision(tmp_path, subcommand, tool):
    import json

    node = str(uuid4())
    image = "sha256:" + "1" * 64
    file = tmp_path / "nodes.json"
    file.write_text(json.dumps({
        node: {"executors": {tool: {"revision": "fixed", "image_id": image, "private_docker": True}}},
    }))
    settings = SimpleNamespace(planning_container_config=str(file))
    task = {"compilation": {"config": {"subcommand": subcommand}}, "tool": {"revision": "fixed"}}
    assert execution_template(settings, node, task)["image_id"] == image
    assert execution_template(settings, uuid4(), task) is None
    task["tool"]["revision"] = "different"
    assert execution_template(settings, node, task) is None


def test_container_identity_must_match_owner_even_when_name_and_image_match():
    import json

    owner = str(uuid4())
    adapter = object.__new__(IsolatedPlanningContainer)
    adapter.owner = owner
    adapter.name = "autoeval-task-" + owner
    adapter.image_id = "sha256:" + "1" * 64
    row = {
        "Name": "/" + adapter.name,
        "Image": adapter.image_id,
        "Config": {"Labels": {"autoeval.dataset_execution": str(uuid4())}},
    }
    adapter.control = SimpleNamespace(command=lambda _, argv: (
        b"container-id" if argv[1] == "ps" else json.dumps([row]).encode()
    ))
    with pytest.raises(ValueError, match="ownership mismatch"):
        adapter._find(None)


def test_submission_rejects_local_resource_kind():
    with pytest.raises(ValidationError) as exc:
        SubmitTask.model_validate({"resource_kind": "docker_local"})
    assert any(error["loc"] == ("resource_kind",) for error in exc.value.errors())
