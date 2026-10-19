"""TDD contract for the provisional SOFR projection-curve inputs."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import QuantLib as ql
import pytest

from core.types.value_objects import PricingDate
from market.curves.yield_curve import CurveDefinition, YieldCurveBuilder


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "bloomberg_irs_case.json"
)

# PROVISIONAL DEVELOPMENT ASSUMPTIONS — NOT SME-CONFIRMED.
# Keep these assumptions isolated here so they can be revised in one place:
# - displayed Market Rate values are percentages (e.g. 3.6524 -> 0.036524);
# - the first dated rate applies from curve date to its quote date;
# - subsequent rates apply from the prior quote date to the current quote date;
# - each interval accrues using Actual/360 simple interest.
PROVISIONAL_MARKET_RATE_DIVISOR = 100.0
PROVISIONAL_INTERVAL_DAY_COUNT = ql.Actual360()


def test_bloomberg_simple_forwards_build_sofr_projection_curve():
    case = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    market = case["market_environment"]
    reference_date = date.fromisoformat(market["reference_date"])
    assert reference_date == date(2026, 3, 31)

    observations = [
        (date.fromisoformat(point["date"]), point["market_rate"])
        for point in market["market_data_points"]
    ]

    # Derive the expected cumulative discount factors from the provisional
    # simple-forward interval interpretation. These are assertions against the
    # production-built curve, not a curve constructed in this test.
    expected_discount_factors = [(reference_date, 1.0)]
    previous_date = reference_date
    previous_discount_factor = 1.0
    for quote_date, displayed_rate in observations:
        forward_rate = displayed_rate / PROVISIONAL_MARKET_RATE_DIVISOR
        start = ql.Date(previous_date.day, previous_date.month, previous_date.year)
        end = ql.Date(quote_date.day, quote_date.month, quote_date.year)
        tau = PROVISIONAL_INTERVAL_DAY_COUNT.yearFraction(start, end)
        previous_discount_factor /= 1.0 + forward_rate * tau
        expected_discount_factors.append((quote_date, previous_discount_factor))
        previous_date = quote_date

    try:
        definition = CurveDefinition(
            currency="USD",
            pricing_date=PricingDate(reference_date),
            forward_rates=observations,
        )
    except TypeError as exc:
        pytest.fail(
            "Optima's current CurveDefinition/YieldCurveBuilder path cannot "
            "accept dated simple-forward observations for a projection curve: "
            f"{exc}"
        )

    projection_handle = YieldCurveBuilder().build(definition)
    assert isinstance(projection_handle, ql.YieldTermStructureHandle)
    assert projection_handle.referenceDate() == ql.Date(31, 3, 2026)
    assert projection_handle.dayCounter().name() == "Actual/360"
    assert projection_handle.discount(ql.Date(31, 3, 2026)) == pytest.approx(
        1.0, abs=1e-14
    )
    assert isinstance(ql.Sofr(projection_handle), ql.OvernightIndex)

    # Check several interval relationships and recover their simple forwards
    # from the constructed term structure.
    check_indices = sorted({0, len(observations) // 4, len(observations) // 2,
                            3 * len(observations) // 4, len(observations) - 1})
    actual_discount_factors = dict(expected_discount_factors)
    for index in check_indices:
        quote_date, displayed_rate = observations[index]
        interval_start = reference_date if index == 0 else observations[index - 1][0]
        start = ql.Date(
            interval_start.day, interval_start.month, interval_start.year
        )
        end = ql.Date(quote_date.day, quote_date.month, quote_date.year)
        expected_df = actual_discount_factors[quote_date]
        assert projection_handle.discount(end) == pytest.approx(
            expected_df, rel=1e-12, abs=1e-14
        )
        assert projection_handle.discount(end) / projection_handle.discount(start) == pytest.approx(
            1.0 / (
                1.0
                + (displayed_rate / PROVISIONAL_MARKET_RATE_DIVISOR)
                * PROVISIONAL_INTERVAL_DAY_COUNT.yearFraction(start, end)
            ),
            rel=1e-12,
            abs=1e-14,
        )
        recovered_forward = projection_handle.forwardRate(
            start,
            end,
            PROVISIONAL_INTERVAL_DAY_COUNT,
            ql.Simple,
        ).rate()
        assert recovered_forward == pytest.approx(
            displayed_rate / PROVISIONAL_MARKET_RATE_DIVISOR,
            rel=1e-10,
            abs=1e-12,
        )
