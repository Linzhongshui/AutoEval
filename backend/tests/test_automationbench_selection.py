from autoeval.planning import TaskInput
from autoeval.planning_engine import DATASETS


def test_automationbench_is_a_supported_selection():
    assert 'AutomationBench' in DATASETS
    assert 'AutomationBench' in TaskInput.model_fields['dataset'].annotation.__args__
