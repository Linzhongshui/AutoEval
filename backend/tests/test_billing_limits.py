from decimal import Decimal

import pytest

from autoeval.billing_limits import maximum_request_cost, reservation_allowed


def test_peak_reservation_and_concurrent_commitments():
    rates = {
        "unit_tokens": 1000000,
        "peak": {"input_miss": "2", "input_hit": "0.04", "output": "8"},
        "off_peak": {"input_miss": "1", "input_hit": "0.02", "output": "4"},
    }
    assert maximum_request_cost(1048576, 262144, rates) == Decimal("4.194304")
    assert reservation_allowed(250, 0, 0, 240, 240, 0)
    assert not reservation_allowed(250, 0, 240, 11, 10, 0)
    assert not reservation_allowed(250, 0, 239, 2, 240, 239)
    assert maximum_request_cost(1, 1, rates) == Decimal("0.000010")
    with pytest.raises(ValueError):
        maximum_request_cost(1, 0, rates)
    with pytest.raises(ValueError):
        reservation_allowed(250, 0, 0, "NaN", 240, 0)
