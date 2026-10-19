"""TDD contract for preserving Bloomberg discount-factor curve pillars."""

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


def test_bloomberg_discount_factor_pillars_build_usd_discount_curve():
    case = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    market = case["market_environment"]
    reference_date = date.fromisoformat(market["reference_date"])
    assert reference_date == date(2026, 3, 31)

    # Pass only the supplied discount-factor observations through Optima's
    # production curve builder. Market Rate values are deliberately unused.
    discount_factors = [
        (date.fromisoformat(point["date"]), point["discount_factor"])
        for point in market["market_data_points"]
    ]
    try:
        definition = CurveDefinition(
            currency="USD",
            pricing_date=PricingDate(reference_date),
            discount_factors=discount_factors,
        )
    except TypeError as exc:
        pytest.fail(
            "Optima's current CurveDefinition/YieldCurveBuilder path cannot "
            "accept dated discount-factor observations: "
            f"{exc}"
        )

    curve = YieldCurveBuilder().build(definition)
    assert isinstance(curve, ql.YieldTermStructureHandle)
    assert curve.referenceDate() == ql.Date(31, 3, 2026)
    assert curve.dayCounter().name() == "Actual/360"
    assert curve.discount(ql.Date(31, 3, 2026)) == pytest.approx(1.0, abs=1e-14)

    # Pillar checks establish that construction preserves the supplied inputs;
    # no interpolation behavior between pillars is prescribed here.
    for pillar_date, expected_df in discount_factors[:: max(1, len(discount_factors) // 5)]:
        ql_pillar = ql.Date(pillar_date.day, pillar_date.month, pillar_date.year)
        assert curve.discount(ql_pillar) == pytest.approx(
            expected_df, rel=1e-12, abs=1e-14
        )

    # Bloomberg supplies the discount factors at the two coupon payment dates.
    # These are direct discounting inputs for both swap legs; Market Rate is
    # not passed to this curve definition. The assertions establish the
    # canonical payment-date contract without specifying behavior elsewhere.
    payment_date_discount_factors = (
        (date(2027, 5, 28), 0.958306),
        (date(2027, 11, 30), 0.941092),
    )
    actual_payment_date_discount_factors = tuple(
        curve.discount(ql.Date(d.day, d.month, d.year))
        for d, _ in payment_date_discount_factors
    )
    expected_payment_date_discount_factors = tuple(
        expected for _, expected in payment_date_discount_factors
    )
    assert actual_payment_date_discount_factors == pytest.approx(
        expected_payment_date_discount_factors, rel=1e-6, abs=1e-8
    )
