import hashlib
import json

import pytest

from autoeval.standard_baselines import baseline_bundle


def test_reference_preserves_source_and_is_immutable():
 raw=json.dumps({'median':90.9,'metric':'accuracy','unit':'percent','inherited_from':'other-model'})
 e={'source_model':'model','mapping':{'dataset':'GPQA'},'files':{'baseline.json':{'raw':raw,'sha256':hashlib.sha256(raw.encode()).hexdigest(),'path':'model/GPQA_Diamond/baseline.json'}}}
 b=baseline_bundle(e,'SJTUyh/AutoEval-Standard','a'*40)['baselines'][0]
 assert b['value']==90.9 and b['conditions']['reference_only'] is True
 assert b['conditions']['standard_baseline']['inherited_from']=='other-model'
 assert baseline_bundle(e,'SJTUyh/AutoEval-Standard','a'*40)['baselines'][0]==b
 e['files']['baseline.json']['sha256']='0'*64
 with pytest.raises(ValueError,match='hash'):baseline_bundle(e,'repo','a'*40)
