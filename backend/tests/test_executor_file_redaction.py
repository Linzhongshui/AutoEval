import hashlib

import pytest

from autoeval_runtime.debug_files import masked_slice


@pytest.mark.parametrize("start,end", [(0, 11), (4, 18), (10, 14), (2, 21)])
def test_preview_masks_known_secret_even_when_boundary_splits_it(start, end):
    secret = b"synthetic-token"
    data = b"before:" + secret + b":after"
    fingerprint = {
        "length": len(secret),
        "prefix": hashlib.sha256(secret[:32]).hexdigest(),
        "digest": hashlib.sha256(secret).hexdigest(),
    }
    result = masked_slice(data, start, end, fingerprint)
    assert (
        result
        == data[start : min(end, 7)] + b"[REDACTED]" + data[max(start, 7 + len(secret)) : end]
    )
