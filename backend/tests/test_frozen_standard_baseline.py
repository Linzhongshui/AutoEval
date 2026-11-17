import hashlib
import json

import pytest

from autoeval.catalog.benchmarks import compare_frozen_standard


def task(dataset='GPQA',metric='accuracy'):
 raw=json.dumps({'median':90.9,'unit':'percent','metric':metric,'range':None,'tolerance':None})
 return {'dataset':dataset,'standard_baseline_source':{'benchmark':'GPQA_Diamond' if dataset=='GPQA' else dataset,'revision':'a'*40,'repository':'SJTUyh/AutoEval-Standard','source_model':'DeepSeek-V4.1-Flash-1017','file':{'raw':raw,'path':'model/benchmark/baseline.json','sha256':hashlib.sha256(raw.encode()).hexdigest()}}}

def test_full_standard_difference():
 summary={'accuracy':92,'validity':'complete','scoring_status':'succeeded','subset_scope':'full'}
 result=compare_frozen_standard(summary,task())
 assert result['status']=='matched' and result['difference']==pytest.approx(1.1)
 assert result['verdict'] is None
 assert compare_frozen_standard(dict(summary,subset_scope='lite'),task())['difference'] is None
 assert compare_frozen_standard(dict(summary,validity='partial'),task())['difference'] is None
 assert compare_frozen_standard(summary,task('AutomationBench','pass_rate'))['status']=='matched'
 assert compare_frozen_standard(summary,task('AutomationBench','accuracy'))['status']=='incomparable'
 t=task();t['standard_baseline_source']['file']['raw']+=' '
 with pytest.raises(ValueError,match='hash'):compare_frozen_standard(summary,t)
