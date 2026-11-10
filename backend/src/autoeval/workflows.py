from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn
class RunWorkflow:
    @workflow.run
    async def run(self, run_id: str) -> None:
        await workflow.execute_activity(
            "execution_not_configured",
            run_id,
            task_queue="demo.io.v1",
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


@workflow.defn
class AnalysisWorkflow:
    @workflow.run
    async def run(self, job_id: str) -> None:
        await workflow.execute_activity(
            "analysis_not_configured",
            job_id,
            task_queue="demo.result.v1",
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


@workflow.defn
class DockerDiagnosticWorkflow:
    @workflow.run
    async def run(self, run_id: str) -> dict:
        return await workflow.execute_activity(
            "execute_docker_diagnostic",
            run_id,
            task_queue="demo.io.v1",
            start_to_close_timeout=timedelta(minutes=3),
            heartbeat_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
