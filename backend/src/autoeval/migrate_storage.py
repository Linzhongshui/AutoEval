"""Explicit development S3 copy; verify bytes, preserve source, never overwrite conflicts."""

import argparse
import hashlib
import tempfile
from urllib.parse import urlsplit

from botocore.exceptions import ClientError

from autoeval.config import get_settings
from autoeval.datasets import storage


def inventory(client, bucket):
    return {
        item["Key"]: (item["Size"], item["ETag"])
        for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket)
        for item in page.get("Contents", [])
    }


def checksum(stream):
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def copy_object(source, target, bucket, key, *, apply):
    response = source.get_object(Bucket=bucket, Key=key)
    with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as content:
        try:
            while chunk := response["Body"].read(1024 * 1024):
                content.write(chunk)
        finally:
            response["Body"].close()
        content.seek(0)
        expected = checksum(content)
        try:
            existing = target.get_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in {"NoSuchKey", "NoSuchBucket", "404"}:
                raise
        else:
            try:
                actual = checksum(existing["Body"])
            finally:
                existing["Body"].close()
            if actual != expected:
                raise ValueError("Destination conflict; no overwrite or cutover permitted")
            return "verified"
        if not apply:
            return "would_copy"
        content.seek(0)
        target.put_object(
            Bucket=bucket,
            Key=key,
            Body=content,
            ContentType=response.get("ContentType", "application/octet-stream"),
            Metadata=response.get("Metadata", {}),
        )
        copied = target.get_object(Bucket=bucket, Key=key)
        try:
            if checksum(copied["Body"]) != expected:
                raise ValueError("Destination verification failed; keep original storage")
        finally:
            copied["Body"].close()
        return "copied"


def migrate(target_endpoint, *, apply=False):
    settings = get_settings()
    target_url = urlsplit(target_endpoint)
    if (
        settings.environment != "development"
        or target_url.scheme != "http"
        or target_url.hostname not in {"127.0.0.1", "localhost"}
        or target_url.username
        or target_url.password
        or target_url.query
        or target_url.fragment
    ):
        raise ValueError("This command accepts local development storage only")
    if settings.s3_endpoint.rstrip("/") == target_endpoint.rstrip("/"):
        raise ValueError("Distinct source and destination required")
    source = storage(settings)
    target = storage(settings.model_copy(update={"s3_endpoint": target_endpoint}))
    try:
        before = inventory(source, settings.s3_bucket)
        if apply:
            try:
                target.head_bucket(Bucket=settings.s3_bucket)
            except ClientError as exc:
                if exc.response["Error"]["Code"] not in {"404", "NoSuchBucket"}:
                    raise
                target.create_bucket(Bucket=settings.s3_bucket)
        counts = {}
        for key in before:
            state = copy_object(source, target, settings.s3_bucket, key, apply=apply)
            counts[state] = counts.get(state, 0) + 1
        if before != inventory(source, settings.s3_bucket):
            raise ValueError("Source changed during migration; do not switch endpoints")
        return {
            "objects": len(before),
            "bytes": sum(size for size, _ in before.values()),
            "outcomes": counts,
            "source_preserved": True,
        }
    finally:
        source.close()
        target.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-endpoint", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(migrate(args.target_endpoint, apply=args.apply))


if __name__ == "__main__":
    main()
