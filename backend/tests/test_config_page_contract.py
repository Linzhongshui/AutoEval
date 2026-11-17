import copy
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from autoeval.planning.routes import PlanningOptions
from autoeval.responses import ObjectPageEnvelope
from autoeval.standard_inputs import row_data


def test_planning_options_is_paginated_object_not_array():
 page=ObjectPageEnvelope[PlanningOptions].model_validate({'data':{'compilations':[],'manifests':[],'curves':[]},'request_id':'test','next_offset':None})
 assert page.model_dump()['data']=={'compilations':[],'manifests':[],'curves':[]}
 from autoeval.api import create_app
 schema=create_app().openapi()
 ref=schema['paths']['/api/autoeval/v1/planning/options']['get']['responses']['200']['content']['application/json']['schema']['$ref']
 assert 'ObjectPageEnvelope' in ref


def test_legacy_standard_input_presentation_does_not_mutate_source():
 payload={};original=copy.deepcopy(payload)
 row=SimpleNamespace(id=uuid.uuid4(),repository='operator',revision='a'*40,source_model='model',benchmark='AutomationBench',content_sha256='0'*64,created_at=datetime.now(UTC),payload=payload)
 data=row_data(row)
 assert data['mapping']['dataset']=='AutomationBench' and data['files']=={}
 assert payload==original
 row.benchmark='unknown'
 assert row_data(row)['mapping']=={}
