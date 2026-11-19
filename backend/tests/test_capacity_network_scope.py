from datetime import UTC, datetime, timedelta

from autoeval.evaluation.service import fits
from autoeval.evaluation.task_monitor import freshness


def resource(networks=None):
    return {'cpu_cores':72,'mem_mb':737383,'disk_gb':3236,'network_available':networks}


def test_gpqa_ignores_harbor_network_leases_but_checks_cpu_and_memory():
    demand={'cpu':1.04,'mem':1056,'disk':0,'networks':0}
    used={'cpu':3.52,'mem':9488,'disk':20,'networks':1}
    assert fits(demand,used,resource())
    assert not fits(demand,{**used,'cpu':72},resource())
    assert not fits(demand,{**used,'mem':737383},resource())


def test_harbor_still_requires_positive_available_network_capacity():
    demand={'cpu':2.5,'mem':8448,'disk':20,'networks':1}
    used={'cpu':3.52,'mem':9488,'disk':20,'networks':1}
    assert not fits(demand,used,resource())
    assert not fits(demand,used,resource(1))
    assert fits(demand,used,resource(2))


def test_waiting_for_resource_is_not_collector_outage():
    value={'observed_at':(datetime.now(UTC)-timedelta(minutes=20)).isoformat(),'snapshot_kind':'live','collection_status':'waiting_tool'}
    assert not freshness(value)['stale']
    assert freshness({**value,'collection_status':'available'})['stale']
