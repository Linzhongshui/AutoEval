import copy
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from autoeval.billing.transport import budget_ignored, execution_route
from autoeval.evaluation import submission as service
from autoeval.evaluation.evaluation_tasks import SubmitTask
from autoeval.infrastructure.models import RunSnapshot
from autoeval.planning import PlanInput


def test_budget_override_requires_explicit_boolean_and_frozen_ack(tmp_path):
 base={'target_id':uuid.uuid4(),'resource_id':uuid.uuid4(),'resource_kind':'customer_ssh','tasks':[{'task_id':'GPQA','dataset':'GPQA','compilation_id':uuid.uuid4(),'manifest_id':uuid.uuid4()}]}
 assert 'ignore_budget' not in SubmitTask(**base).model_dump()
 assert 'ignore_budget' not in PlanInput(**base).model_dump()
 assert SubmitTask(**base,ignore_budget=True).model_dump()['ignore_budget'] is True
 for value in ['true',1,None]:
  with pytest.raises(ValidationError):SubmitTask(**base,ignore_budget=value)
 assert not budget_ignored({'inputs':{'ignore_budget':True}})
 assert budget_ignored({'inputs':{'ignore_budget':True},'model_budget':{'mode':'ignored'}})
 assert execution_route(SimpleNamespace(billing_execution_config=tmp_path/'missing'),uuid.uuid4(),uuid.uuid4(),'GPQA',ignore_budget=True) is None


@pytest.mark.asyncio
async def test_ignored_budget_freezes_ack_and_still_requires_preflight_and_locks(monkeypatch,tmp_path):
 target=SimpleNamespace(id=uuid.uuid4(),remote_model='deepseek-flash',base_url='https://api.deepseek.com/v1')
 body=PlanInput(target_id=target.id,resource_id=uuid.uuid4(),resource_kind='customer_ssh',ignore_budget=True,tasks=[{'task_id':'GPQA','dataset':'GPQA','compilation_id':uuid.uuid4(),'manifest_id':uuid.uuid4()}])
 task={**body.tasks[0].model_dump(mode='json'),'concurrency':1,'subset_scope':'lite','manifest_sha256':'0'*64,'samples':[{'sample_id':'gpqa_diamond:0'}],'tool':{'revision':'a'*40},'compilation':{'config':{'tool':'ais_bench','subcommand':'llm_accuracy','params':{'max_num_workers':1,'max_out_len':64}},'locked_fields':{'params.max_out_len':64}}}
 task['execution_template']={'family':'aisbench','revision':'a'*40,'image_id':'sha256:'+'1'*64}
 inputs={**body.model_dump(mode='json'),'tasks':[task]}
 fresh=SimpleNamespace(payload={'execution_ready':True,'supported_datasets':['GPQA'],'execution_templates':{'GPQA':task['execution_template']}},sha256='0'*64)
 monkeypatch.setattr(service,'resolve_inputs',AsyncMock(side_effect=lambda *a:copy.deepcopy(inputs)))
 monkeypatch.setattr(service,'current_preflight',AsyncMock(return_value=fresh))
 monkeypatch.setattr(service,'demand_for',lambda *a:{})
 monkeypatch.setattr(service,'fits',lambda *a:True)
 settings=SimpleNamespace(evaluation_origin='real',allowed_model_hosts=['api.deepseek.com'],billing_execution_config=tmp_path/'not-readable-full-scope-budget')
 class Session:
  def __init__(self):self.rows=[]
  async def scalar(self,*args):return None
  async def get(self,*args):return target
  def add(self,row):
   if getattr(row,'id',None) is None:row.id=uuid.uuid4()
   self.rows.append(row)
  async def flush(self):pass
 session=Session()
 result=await service.create_run(session,settings,body,None,'test-key')
 assert result['state']=='accepted'
 snapshot=next(r for r in session.rows if isinstance(r,RunSnapshot))
 assert budget_ignored(snapshot.canonical_body)
 assert snapshot.canonical_body['model_budget']['acknowledged_by']=='local-operator'
 assert datetime.fromisoformat(snapshot.canonical_body['model_budget']['execution_deadline']) <= datetime.now(UTC)+timedelta(hours=24)
 fresh.payload['execution_ready']=False
 with pytest.raises(HTTPException,match='Fresh resource preflight'):await service.create_run(Session(),settings,body,None,'no-preflight')
 fresh.payload['execution_ready']=True
 task['compilation']['config']['params']['max_out_len']=65
 with pytest.raises(HTTPException,match='standard locks'):await service.create_run(Session(),settings,body,None,'invalid-lock')
