import hashlib
import io
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from autoeval.repair_gpqa_evidence import restore_exact


def missing_client():
    client = Mock()
    client.get_object.side_effect = ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
    return client


def test_repair_requires_exact_digest_before_any_storage_operation():
    client = Mock()
    with pytest.raises(ValueError, match="immutable digest"):
        restore_exact(client, "bucket", "key", "0" * 64, b"different", apply=True)
    client.get_object.assert_not_called()
    client.put_object.assert_not_called()


def test_repair_dry_run_does_not_write_and_apply_writes_original_bytes():
    raw = b'{"original":true}'
    digest = hashlib.sha256(raw).hexdigest()
    client = missing_client()
    assert restore_exact(client, "bucket", "key", digest, raw) == "would_restore"
    client.put_object.assert_not_called()
    assert restore_exact(client, "bucket", "key", digest, raw, apply=True) == "restored"
    assert client.put_object.call_args.kwargs["Body"] == raw


def test_repair_never_overwrites_existing_conflicting_evidence():
    client = Mock()
    client.get_object.return_value = {"Body": io.BytesIO(b"conflict")}
    raw = b"original"
    with pytest.raises(ValueError, match="refusing to overwrite"):
        restore_exact(client, "bucket", "key", hashlib.sha256(raw).hexdigest(), raw, apply=True)
    client.put_object.assert_not_called()


def test_repair_existing_matching_object_is_idempotent():
    raw = b"original"
    client = Mock()
    client.get_object.return_value = {"Body": io.BytesIO(raw)}
    assert (
        restore_exact(client, "bucket", "key", hashlib.sha256(raw).hexdigest(), raw, apply=True)
        == "verified"
    )
    client.put_object.assert_not_called()
