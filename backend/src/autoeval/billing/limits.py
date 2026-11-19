"""Conservative CNY reservations; unknown usage never frees reserved money."""

from decimal import ROUND_CEILING, Decimal

MICRO = Decimal("0.000001")


def maximum_request_cost(input_bound, output_bound, rates):
    if any(type(n) is not int or n < 0 for n in (input_bound, output_bound)):
        raise ValueError("Explicit nonnegative token bounds required")
    if output_bound == 0:
        raise ValueError("Explicit positive output bound required")
    tiers = [rates[k] for k in ("peak", "off_peak", "standard") if k in rates]
    if not tiers or rates.get("unit_tokens") != 1000000:
        raise ValueError("Unsupported rate contract")
    costs = []
    for tier in tiers:
        prices = [Decimal(str(tier[k])) for k in ("input_miss", "input_hit", "output")]
        if any(not x.is_finite() or x < 0 for x in prices):
            raise ValueError("Invalid price")
        costs.append((input_bound * max(prices[:2]) + output_bound * prices[2]) / 1000000)
    return max(costs).quantize(MICRO, rounding=ROUND_CEILING)


def reservation_allowed(total, spent, reserved, requested, section_limit, section_committed):
    values = [
        Decimal(str(x))
        for x in (total, spent, reserved, requested, section_limit, section_committed)
    ]
    if any(not x.is_finite() or x < 0 for x in values) or values[3] == 0:
        raise ValueError("Invalid budget amount")
    total, spent, reserved, requested, section_limit, section_committed = values
    return spent + reserved + requested <= total and section_committed + requested <= section_limit
