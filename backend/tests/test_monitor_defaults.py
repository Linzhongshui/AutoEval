import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from autoeval import planning_observations
from autoeval.evaluation.resource_allocation import execution_compilation
from autoeval.task_monitor import normalize


def test_runtime_metadata_is_not_sent_and_snapshot_is_not_mutated():
    original = {'runtime_config':{'resource_ids':['a'],'manifest_ids':['b'],'datasets_dir':'/data','execution':'local'},'config':{'params':{}}}
    compiled = execution_compilation(original)
    assert compiled['runtime_config'] == {'datasets_dir':'/data','execution':'local'}
    assert original['runtime_config']['resource_ids'] == ['a']


@pytest.mark.asyncio
async def test_every_dataset_can_archive_terminal_state_without_native_counts(monkeypatch):
    child = SimpleNamespace(id=uuid.uuid4(),payload={'samples':[{},{}]})
    binding = SimpleNamespace(id=uuid.uuid4(),latest=None)
    class Session:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def scalar(self,*args):return binding
    saved = AsyncMock()
    monkeypatch.setattr(planning_observations,'save_observation',saved)
    await planning_observations.publish_lifecycle(Session,None,uuid.uuid4(),child,'failed',final=True)
    args = saved.await_args.args
    assert args[3]['status']=='failed' and args[3]['finish_count'] is None
    assert args[4]=='executor_lifecycle'
    assert saved.await_args.kwargs['kind']=='final'
    projection=normalize(args[3],{'task_name':str(child.id)},args[4],datetime.now(UTC).isoformat(),snapshot_kind='final')
    assert projection['process_id'] is None and projection['finish_count'] is None
    assert projection['total_count']==2
