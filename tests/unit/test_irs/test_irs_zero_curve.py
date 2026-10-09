"""Construction tests for the fresh IRS zero-curve builder.

These tests use only the curve inputs (zero rates, discount factors, tenors).
Bloomberg trade outputs are deliberately kept out; they belong to the
reconciliation tests.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import date

import pytest
import QuantLib as ql

from market.curves.irs_zero_curve import (
    UnsupportedZeroCurveConvention,
    ZeroCurveConsistencyError,
    ZeroCurveConventions,
    ZeroCurveMarketData,
    ZeroCurveObservation,
    build_zero_curve,
)


def _ql(d: date) -> ql.Date:
    return ql.Date(d.day, d.month, d.year)


def test_pillar_dates_follow_spot_plus_tenor_and_match_fixture(
    usd_sofr_market_data, usd_sofr_curve_conventions, usd_sofr_zero_document
):
    curve = build_zero_curve(usd_sofr_market_data, usd_sofr_curve_conventions)

    assert curve.spot_date == date(2026, 4, 2)
    assert [p.isoformat() for p in curve.pillar_dates] == [
        row["pillar_date"] for row in usd_sofr_zero_document["observations"]
    ]
    assert curve.term_structure.referenceDate() == ql.Date(31, 3, 2026)


def test_every_supplied_discount_factor_is_reproduced_within_export_rounding(
    usd_sofr_market_data, usd_sofr_curve_conventions
):
    curve = build_zero_curve(usd_sofr_market_data, usd_sofr_curve_conventions)

    for observation, pillar in zip(usd_sofr_market_data.observations, curve.pillar_dates):
        t = (pillar - usd_sofr_market_data.reference_date).days / 365.0
        rounding_bound = 0.5e-6 + float(observation.discount_factor) * t * 0.5e-7
        assert curve.handle.discount(_ql(pillar)) == pytest.approx(
            float(observation.discount_factor), abs=rounding_bound
        ), observation.tenor


def test_pillar_zero_rates_are_returned_exactly(usd_sofr_market_data, usd_sofr_curve_conventions):
    curve = build_zero_curve(usd_sofr_market_data, usd_sofr_curve_conventions)

    for observation, pillar in zip(usd_sofr_market_data.observations, curve.pillar_dates):
        zero = curve.handle.zeroRate(_ql(pillar), ql.Actual365Fixed(), ql.Continuous).rate()
        assert zero == pytest.approx(float(observation.zero_rate), abs=1e-14)


def test_interpolation_is_linear_in_zero_rate_between_pillars(
    usd_sofr_market_data, usd_sofr_curve_conventions
):
    curve = build_zero_curve(usd_sofr_market_data, usd_sofr_curve_conventions)
    reference = usd_sofr_market_data.reference_date
    pillars, observations = curve.pillar_dates, usd_sofr_market_data.observations
    # 18M (04-Oct-2027) to 2Y (03-Apr-2028) and an interior date inside it.
    left, right = pillars[15], pillars[16]
    z_left, z_right = float(observations[15].zero_rate), float(observations[16].zero_rate)
    target = date(2027, 11, 30)
    weight = (target - left).days / (right - left).days
    expected_zero = z_left + weight * (z_right - z_left)
    t = (target - reference).days / 365.0

    assert curve.handle.zeroRate(_ql(target), ql.Actual365Fixed(), ql.Continuous).rate() == (
        pytest.approx(expected_zero, abs=1e-14)
    )
    assert curve.handle.discount(_ql(target)) == pytest.approx(
        math.exp(-expected_zero * t), abs=1e-14
    )


def test_front_segment_is_flat_at_first_pillar_zero(
    usd_sofr_market_data, usd_sofr_curve_conventions
):
    curve = build_zero_curve(usd_sofr_market_data, usd_sofr_curve_conventions)
    first_zero = float(usd_sofr_market_data.observations[0].zero_rate)

    for d in (date(2026, 4, 1), date(2026, 4, 6)):
        zero = curve.handle.zeroRate(_ql(d), ql.Actual365Fixed(), ql.Continuous).rate()
        # zeroRate() is recovered from a DF over a few days, so round-off is ~1e-14.
        assert zero == pytest.approx(first_zero, abs=1e-12)


def test_wrong_spot_lag_is_rejected_by_discount_factor_check(
    usd_sofr_market_data, usd_sofr_curve_conventions
):
    # Spot lag 0 instead of 2 shifts every pillar by two days; the supplied DFs
    # must expose it.
    wrong = replace(usd_sofr_curve_conventions, spot_lag_days=0)

    with pytest.raises(ZeroCurveConsistencyError, match="contradict"):
        build_zero_curve(usd_sofr_market_data, wrong)


def test_wrong_tenor_is_rejected_by_discount_factor_check(
    usd_sofr_market_data, usd_sofr_curve_conventions
):
    observations = list(usd_sofr_market_data.observations)
    observations[3] = replace(observations[3], tenor="30D")  # 1M quoted as 30 days
    data = replace(usd_sofr_market_data, observations=tuple(observations))

    with pytest.raises(ZeroCurveConsistencyError, match="30D"):
        build_zero_curve(data, usd_sofr_curve_conventions)


def test_curve_without_check_discount_factors_still_builds(
    usd_sofr_market_data, usd_sofr_curve_conventions
):
    stripped = replace(
        usd_sofr_market_data,
        observations=tuple(
            replace(o, discount_factor=None) for o in usd_sofr_market_data.observations
        ),
    )
    with_check = build_zero_curve(usd_sofr_market_data, usd_sofr_curve_conventions)
    without_check = build_zero_curve(stripped, usd_sofr_curve_conventions)

    d = ql.Date(30, 11, 2027)
    assert without_check.handle.discount(d) == with_check.handle.discount(d)


def test_extrapolation_beyond_last_pillar_is_off_unless_requested(
    usd_sofr_market_data, usd_sofr_curve_conventions
):
    beyond = ql.Date(1, 1, 2035)
    curve = build_zero_curve(usd_sofr_market_data, usd_sofr_curve_conventions)
    with pytest.raises(RuntimeError):
        curve.handle.discount(beyond)

    allowed = build_zero_curve(
        usd_sofr_market_data, replace(usd_sofr_curve_conventions, allow_extrapolation=True)
    )
    assert allowed.handle.discount(beyond) > 0


@pytest.mark.parametrize(
    "field, value",
    [
        ("interpolation", "log_linear_discount"),
        ("front_extrapolation", "flat_forward"),
        ("compounding", ql.Simple),
    ],
)
def test_unsupported_conventions_are_rejected(usd_sofr_curve_conventions, field, value):
    with pytest.raises(UnsupportedZeroCurveConvention):
        replace(usd_sofr_curve_conventions, **{field: value})


def test_conventions_have_no_defaults():
    with pytest.raises(TypeError):
        ZeroCurveConventions()  # type: ignore[call-arg]


@pytest.mark.parametrize("value", [2.0, "2", True, None])
def test_spot_lag_days_must_be_an_int(usd_sofr_curve_conventions, value):
    with pytest.raises(TypeError, match="spot_lag_days"):
        replace(usd_sofr_curve_conventions, spot_lag_days=value)


def test_spot_lag_days_cannot_be_negative(usd_sofr_curve_conventions):
    with pytest.raises(ValueError, match="negative"):
        replace(usd_sofr_curve_conventions, spot_lag_days=-1)


@pytest.mark.parametrize("value", [0, 1, "False", None])
def test_end_of_month_must_be_a_bool(usd_sofr_curve_conventions, value):
    with pytest.raises(TypeError, match="end_of_month"):
        replace(usd_sofr_curve_conventions, end_of_month=value)


@pytest.mark.parametrize("tolerance", [0.0, -1e-6, float("nan")])
def test_tolerance_must_be_positive_and_finite(usd_sofr_curve_conventions, tolerance):
    with pytest.raises(ValueError):
        replace(usd_sofr_curve_conventions, discount_factor_tolerance=tolerance)


def test_percentage_rates_and_bad_tenors_are_rejected():
    with pytest.raises(ValueError, match="percentage"):
        ZeroCurveObservation(tenor="1Y", zero_rate=3.7)
    with pytest.raises(ValueError, match="tenor"):
        ZeroCurveObservation(tenor="one year", zero_rate=0.037)


def test_non_increasing_tenors_are_rejected(usd_sofr_market_data, usd_sofr_curve_conventions):
    observations = usd_sofr_market_data.observations
    swapped = (observations[1], observations[0]) + observations[2:]
    with pytest.raises(ValueError, match="strictly increasing"):
        build_zero_curve(
            replace(usd_sofr_market_data, observations=swapped), usd_sofr_curve_conventions
        )


def test_empty_observations_and_role_mismatches_are_rejected(
    usd_sofr_market_data, usd_sofr_curve_conventions
):
    with pytest.raises(ValueError, match="at least one"):
        ZeroCurveMarketData(date(2026, 3, 31), "USD", "SOFR", ())
    with pytest.raises(ValueError, match="currency"):
        build_zero_curve(usd_sofr_market_data, usd_sofr_curve_conventions, expected_currency="EUR")
    with pytest.raises(ValueError, match="benchmark"):
        build_zero_curve(
            usd_sofr_market_data, usd_sofr_curve_conventions, expected_benchmark="ESTR"
        )


def test_builder_does_not_depend_on_global_evaluation_date(
    usd_sofr_market_data, usd_sofr_curve_conventions
):
    previous = ql.Settings.instance().evaluationDate
    try:
        ql.Settings.instance().evaluationDate = ql.Date(15, 1, 2026)
        a = build_zero_curve(usd_sofr_market_data, usd_sofr_curve_conventions)
        ql.Settings.instance().evaluationDate = ql.Date(15, 6, 2026)
        b = build_zero_curve(usd_sofr_market_data, usd_sofr_curve_conventions)
    finally:
        ql.Settings.instance().evaluationDate = previous
    d = ql.Date(30, 11, 2027)
    assert a.handle.discount(d) == b.handle.discount(d)
    assert a.term_structure.referenceDate() == ql.Date(31, 3, 2026)
