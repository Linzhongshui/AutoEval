import uuid

import pytest
from fastapi import HTTPException

from autoeval.evaluation.evaluation_tasks import SubmitTask
from autoeval.evaluation.resource_allocation import allocate_resource, resource_for_task
from autoeval.planning.routes import PlanInput


def test_assignment_uses_only_selected_compatible_resource():
    assert allocate_resource(['gpqa', 'agent'], ['agent']) == 'agent'
    assert allocate_resource(['agent', 'gpqa'], ['gpqa']) == 'gpqa'
    with pytest.raises(HTTPException):
        allocate_resource(['gpqa'], ['agent'])
    with pytest.raises(HTTPException):
        allocate_resource(['gpqa', 'agent'], None)
    assert allocate_resource(['legacy'], None) == 'legacy'


def test_capacity_uses_assigned_resource_and_preserves_historical_contract():
    a = {'cpu_cores': 2, 'node_id': 'a'}
    b = {'cpu_cores': 16, 'node_id': 'b'}
    snapshot = {**a, 'task_resources': {'GPQA': a, 'AutomationBench': b}}
    assert resource_for_task(snapshot, 'GPQA') == a
    assert resource_for_task(snapshot, 'AutomationBench') == b
    assert resource_for_task(a, 'legacy') == a


def test_public_submit_and_preflight_preserve_same_pool():
    resources = [uuid.uuid4(), uuid.uuid4()]
    body = {'resource_id': resources[0], 'resource_kind': 'customer_ssh', 'resource_ids': resources, 'target_id': uuid.uuid4(), 'tasks': [{'task_id':'GPQA','dataset':'GPQA','compilation_id':uuid.uuid4(),'manifest_id':uuid.uuid4()}]}
    submit = SubmitTask(**body)
    preflight = PlanInput(**submit.model_dump())
    assert preflight.resource_ids == resources
    body.pop('resource_ids')
    assert 'resource_ids' not in SubmitTask(**body).model_dump()
    assert 'resource_ids' not in PlanInput(**body).model_dump()
