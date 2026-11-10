"""Explicit local-development infrastructure setup; never invokes a model."""

import argparse

import boto3

from autoeval.config import get_settings


def storage():
    settings = get_settings()
    if settings.environment != "development":
        raise RuntimeError("Development bootstrap only")
    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name="us-east-1",
    )
    try:
        try:
            client.head_bucket(Bucket=settings.s3_bucket)
        except client.exceptions.ClientError as exc:
            if str(exc.response["Error"]["Code"]) not in {"404", "NoSuchBucket"}:
                raise
            client.create_bucket(Bucket=settings.s3_bucket)
        print("Development evidence bucket is available")
    finally:
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["storage"])
    parser.parse_args()
    storage()
