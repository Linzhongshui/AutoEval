"""Opt-in live dependency tests. Moto validates S3 protocol, not production durability."""

import os
import uuid

import boto3
import pytest
from temporalio.client import Client, WorkflowFailureError
from temporalio.worker import Worker

from autoeval.activities import execution_not_configured
from autoeval.config import get_settings
from autoeval.workflows import RunWorkflow

pytestmark = pytest.mark.skipif(
    not os.environ.get("AE_INFRA_TEST"), reason="Live infrastructure required"
)


async def test_live_temporal_worker_rejects_unimplemented_execution():
    settings = get_settings()
    client = await Client.connect(settings.temporal_address)
    queue = "test-" + uuid.uuid4().hex
    async with (
        Worker(client, task_queue=queue, workflows=[RunWorkflow]),
        Worker(client, task_queue="demo.io.v1", activities=[execution_not_configured]),
    ):
        with pytest.raises(WorkflowFailureError):
            await client.execute_workflow(
                RunWorkflow.run,
                "test-" + uuid.uuid4().hex,
                id="test-" + uuid.uuid4().hex,
                task_queue=queue,
            )


def test_live_s3_put_get_delete():
    settings = get_settings()
    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name="us-east-1",
    )
    key = "integration/" + uuid.uuid4().hex
    try:
        client.put_object(Bucket=settings.s3_bucket, Key=key, Body=b"protocol-test")
        response = client.get_object(Bucket=settings.s3_bucket, Key=key)
        try:
            assert response["Body"].read() == b"protocol-test"
        finally:
            response["Body"].close()
    finally:
        client.delete_object(Bucket=settings.s3_bucket, Key=key)
        client.close()
