import argparse
import asyncio
from contextlib import AsyncExitStack

from temporalio.client import Client
from temporalio.worker import Worker

from autoeval.analysis.activity import execute_report_analysis
from autoeval.evaluation.activities import analysis_not_configured, execution_not_configured
from autoeval.evaluation.evaluation_activity import execute_gpqa_exploration
from autoeval.evaluation.fixture_pipeline import execute_unified_fixture
from autoeval.evaluation.monitored_execution import execute_monitored_gpqa
from autoeval.evaluation.orchestration import execute_planned_evaluation
from autoeval.evaluation.run_activities import execute_docker_diagnostic
from autoeval.evaluation.workflows import (
    ISOLATED_DATASET_QUEUE,
    AnalysisWorkflow,
    DockerDiagnosticWorkflow,
    GpqaExplorationWorkflow,
    LangfuseImportWorkflow,
    MonitoredGpqaWorkflow,
    PlannedEvaluationWorkflow,
    ReportAnalysisWorkflow,
    RunWorkflow,
    UnifiedFixtureWorkflow,
)
from autoeval.infrastructure.config import get_settings
from autoeval.reporting.langfuse_integration import import_harbor_trace
from autoeval.reporting.unified_activity import collect_unified_output


def role_options(settings):
    """Single source of truth for Temporal roles.

    Each role runs one task queue. Worker roles execute workflows only, activity
    roles execute activities only, and mixed queues (``workflow``) exist for the
    legacy exploration path. Every role needs a reachable Temporal frontend at
    ``settings.temporal_address``; activity roles additionally need database,
    object storage and any resource (Docker/SSH) they touch at runtime.
    """
    return {
        "langfuse": {
            "task_queue": "demo.langfuse.v1",
            "workflows": [LangfuseImportWorkflow],
            "activities": [import_harbor_trace],
        },
        "monitored": {
            "task_queue": "demo.monitored.v1",
            "workflows": [MonitoredGpqaWorkflow],
            "activities": [execute_monitored_gpqa],
        },
        "fixture": {
            "task_queue": "demo.fixture.workflow.v1",
            "workflows": [UnifiedFixtureWorkflow],
            "activities": [execute_unified_fixture],
        },
        "workflow": {
            "task_queue": settings.gpqa_workflow_queue,
            "workflows": [
                PlannedEvaluationWorkflow,
                RunWorkflow,
                AnalysisWorkflow,
                MonitoredGpqaWorkflow,
                DockerDiagnosticWorkflow,
                GpqaExplorationWorkflow,
                ReportAnalysisWorkflow,
            ],
        },
        "analysis-workflow": {
            "task_queue": settings.analysis_workflow_queue,
            "workflows": [ReportAnalysisWorkflow],
        },
        "io": {
            "task_queue": "demo.io.v1",
            "activities": [execution_not_configured, execute_docker_diagnostic],
        },
        "result": {
            "task_queue": settings.analysis_activity_queue,
            "activities": [
                analysis_not_configured,
                execute_report_analysis,
                collect_unified_output,
            ],
        },
        "isolated-execution": {
            "task_queue": ISOLATED_DATASET_QUEUE,
            "workflows": [PlannedEvaluationWorkflow],
            "activities": [execute_planned_evaluation],
        },
        "planning-execution": {
            "task_queue": "demo.planning-execution.v1",
            "activities": [execute_planned_evaluation],
        },
        "gpqa": {
            "task_queue": settings.gpqa_activity_queue,
            "activities": [execute_gpqa_exploration],
        },
    }


async def serve(role: str):
    settings = get_settings()
    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    roles = role_options(settings)
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(Worker(client, **roles[role]))
        if role == "planning-execution":
            # Existing deployments serve both new isolated runs and in-flight legacy activities.
            await stack.enter_async_context(Worker(client, **roles["isolated-execution"]))
        await asyncio.Event().wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=sorted(role_options(get_settings())))
    asyncio.run(serve(parser.parse_args().role))


if __name__ == "__main__":
    main()
