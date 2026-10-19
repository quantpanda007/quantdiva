import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import QuantLib as ql
import pytest

from market.curves.irs_market_data import (
    DiscountFactorObservation,
    DiscountCurveMarketData,
    IRSMarketData,
    ProjectionCurveMethodologyUnspecified,
    SimpleForwardCurveMarketData,
    SimpleForwardObservation,
    build_discount_curve,
    build_projection_curve,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "bloomberg_irs_case.json"
)


@pytest.fixture(scope="module")
def fixture_data():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _curve_data(fixture_data):
    market = fixture_data["market_environment"]
    reference_date = date.fromisoformat(market["reference_date"])
    discount = DiscountCurveMarketData(
        reference_date=reference_date,
        currency=market["currency"],
        observations=tuple(
            DiscountFactorObservation(
                date.fromisoformat(point["date"]), Decimal(str(point["discount_factor"]))
            )
            for point in market["market_data_points"]
        ),
    )
    projection = SimpleForwardCurveMarketData(
        reference_date=reference_date,
        currency=market["currency"],
        benchmark=fixture_data["trade"]["floating_leg"]["index"],
        observations=tuple(
            SimpleForwardObservation(
                date.fromisoformat(point["date"]), Decimal(str(point["market_rate"]))
            )
            for point in market["market_data_points"]
        ),
    )
    return IRSMarketData(discount_curve=discount, projection_curve=projection)


def test_canonical_discount_curve_preserves_reference_anchor_and_all_df_pillars(fixture_data):
    data = _curve_data(fixture_data)

    built = build_discount_curve(data.discount_curve, day_counter=ql.Actual360())

    assert data.discount_curve.reference_date == date(2026, 3, 31)
    assert built.handle.referenceDate() == ql.Date(31, 3, 2026)
    assert built.handle.discount(ql.Date(31, 3, 2026)) == pytest.approx(1.0)
    assert len(data.discount_curve.observations) == 20
    for observation in data.discount_curve.observations:
        ql_date = ql.Date(
            observation.date.day, observation.date.month, observation.date.year
        )
        assert built.handle.discount(ql_date) == pytest.approx(
            float(observation.discount_factor), abs=1e-12
        )
    assert built.market_data is data.discount_curve
    assert built.handle.dayCounter().name() == "Actual/360"


def test_projection_market_data_preserves_raw_simple_forwards_without_curve_conversion(
    fixture_data,
):
    market_data = _curve_data(fixture_data)
    projection = market_data.projection_curve

    assert projection.reference_date == date(2026, 3, 31)
    assert projection.currency == "USD"
    assert projection.benchmark == "SOFR"
    assert len(projection.observations) == 20
    source_points = fixture_data["market_environment"]["market_data_points"]
    assert [point.date.isoformat() for point in projection.observations] == [
        source["date"] for source in source_points
    ]
    assert [point.rate for point in projection.observations] == [
        Decimal(str(source["market_rate"])) for source in source_points
    ]

    with pytest.raises(ProjectionCurveMethodologyUnspecified):
        build_projection_curve(projection)


def test_discount_and_projection_inputs_are_separate_and_currency_mapping_is_checked(
    fixture_data,
):
    market_data = _curve_data(fixture_data)

    assert market_data.discount_curve.observations is not market_data.projection_curve.observations
    assert market_data.discount_curve.reference_date == market_data.projection_curve.reference_date
    assert [item.discount_factor for item in market_data.discount_curve.observations] != [
        item.rate for item in market_data.projection_curve.observations
    ]
    with pytest.raises(ValueError, match="currency"):
        build_discount_curve(
            market_data.discount_curve,
            day_counter=ql.Actual360(),
            expected_currency="EUR",
        )
    with pytest.raises(ValueError, match="benchmark"):
        build_projection_curve(market_data.projection_curve, expected_benchmark="SF0006M")


def test_curve_data_rejects_mixed_currency_roles(fixture_data):
    data = _curve_data(fixture_data)
    incompatible_projection = SimpleForwardCurveMarketData(
        reference_date=data.projection_curve.reference_date,
        currency="EUR",
        benchmark=data.projection_curve.benchmark,
        observations=data.projection_curve.observations,
    )

    with pytest.raises(ValueError, match="currency"):
        IRSMarketData(data.discount_curve, incompatible_projection)
