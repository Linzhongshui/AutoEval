from temporalio import activity
from temporalio.exceptions import ApplicationError


@activity.defn
async def execution_not_configured(run_id: str) -> None:
    raise ApplicationError(
        "SSH/tool adapter is not implemented", type="ADAPTER_NOT_CONFIGURED", non_retryable=True
    )


@activity.defn
async def analysis_not_configured(job_id: str) -> None:
    raise ApplicationError(
        "Analyzer is not implemented", type="ANALYZER_NOT_CONFIGURED", non_retryable=True
    )
