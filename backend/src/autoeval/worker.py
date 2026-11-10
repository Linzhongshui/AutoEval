import argparse
import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from autoeval.activities import analysis_not_configured, execution_not_configured
from autoeval.analysis_activity import execute_report_analysis
from autoeval.config import get_settings
from autoeval.evaluation_activity import execute_gpqa_exploration
from autoeval.run_activities import execute_docker_diagnostic
from autoeval.workflows import (
    AnalysisWorkflow,
    DockerDiagnosticWorkflow,
    GpqaExplorationWorkflow,
    ReportAnalysisWorkflow,
    RunWorkflow,
)


async def serve(role: str):
    settings = get_settings()
    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    options = {
        "workflow": {
            "task_queue": settings.gpqa_workflow_queue,
            "workflows": [
                RunWorkflow,
                AnalysisWorkflow,
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
            "activities": [analysis_not_configured, execute_report_analysis],
        },
        "gpqa": {
            "task_queue": settings.gpqa_activity_queue,
            "activities": [execute_gpqa_exploration],
        },
    }
    async with Worker(client, **options[role]):
        await asyncio.Event().wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=["workflow", "analysis-workflow", "io", "result", "gpqa"])
    asyncio.run(serve(parser.parse_args().role))


if __name__ == "__main__":
    main()
