import argparse
import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from autoeval.activities import analysis_not_configured, execution_not_configured
from autoeval.config import get_settings
from autoeval.run_activities import execute_docker_diagnostic
from autoeval.workflows import AnalysisWorkflow, DockerDiagnosticWorkflow, RunWorkflow


async def serve(role: str):
    settings = get_settings()
    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    options = {
        "workflow": {
            "task_queue": "demo.workflow.v1",
            "workflows": [RunWorkflow, AnalysisWorkflow, DockerDiagnosticWorkflow],
        },
        "io": {
            "task_queue": "demo.io.v1",
            "activities": [execution_not_configured, execute_docker_diagnostic],
        },
        "result": {"task_queue": "demo.result.v1", "activities": [analysis_not_configured]},
    }
    async with Worker(client, **options[role]):
        await asyncio.Event().wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=["workflow", "io", "result"])
    asyncio.run(serve(parser.parse_args().role))


if __name__ == "__main__":
    main()
