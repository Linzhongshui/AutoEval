import io
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from autoeval.migrate_storage import copy_object


def source(raw):
    client = Mock()
    client.get_object.return_value = {"Body": io.BytesIO(raw), "ContentType": "application/json"}
    return client


def absent():
    return ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")


def test_storage_copy_dry_run_preserves_both_sides():
    target = Mock()
    target.get_object.side_effect = absent()
    original = source(b"original")
    assert copy_object(original, target, "bucket", "key", apply=False) == "would_copy"
    original.delete_object.assert_not_called()
    target.put_object.assert_not_called()


def test_storage_copy_checks_readback_before_success():
    target = Mock()
    target.get_object.side_effect = [absent(), {"Body": io.BytesIO(b"original")}]
    assert copy_object(source(b"original"), target, "bucket", "key", apply=True) == "copied"
    assert target.put_object.call_count == 1


def test_storage_copy_never_overwrites_conflicting_destination():
    target = Mock()
    target.get_object.return_value = {"Body": io.BytesIO(b"other")}
    with pytest.raises(ValueError, match="conflict"):
        copy_object(source(b"original"), target, "bucket", "key", apply=True)
    target.put_object.assert_not_called()


def test_storage_copy_detects_failed_readback():
    target = Mock()
    target.get_object.side_effect = [absent(), {"Body": io.BytesIO(b"corrupt")}]
    with pytest.raises(ValueError, match="verification failed"):
        copy_object(source(b"original"), target, "bucket", "key", apply=True)
