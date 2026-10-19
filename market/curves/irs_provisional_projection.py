"""Explicit provisional conversion of IRS simple-forward quotes for QuantLib.

This module is intentionally isolated. Its assumptions are not Bloomberg-
confirmed and can be replaced without changing IRS contractual inputs, legs,
instrument assembly, or engine attachment.

PROVISIONAL methodology:
* displayed Market Rate values are percentages, so divide by 100;
* each quote is a simple reference-date-to-pillar forward rate;
* create a synthetic projection discount factor at each pillar using
  ``D(T) = 1 / (1 + R(T) * yearFraction(reference, T))``;
* use QuantLib ``DiscountCurve`` with its default LogLinear interpolation.

Supplied discount-factor observations are not used in this conversion.
"""

from __future__ import annotations

from dataclasses import dataclass

import QuantLib as ql

from market.curves.irs_market_data import SimpleForwardCurveMarketData


PROVISIONAL_PROJECTION_METHODOLOGY = (
    "simple reference-date forwards / 100 converted to simple-compounded "
    "synthetic discount factors; QuantLib DiscountCurve LogLinear interpolation"
)


@dataclass(frozen=True)
class ProvisionalProjectionCurve:
    """QuantLib projection handle plus source data and provisional labeling."""

    market_data: SimpleForwardCurveMarketData
    term_structure: ql.DiscountCurve
    handle: ql.YieldTermStructureHandle
    methodology: str = PROVISIONAL_PROJECTION_METHODOLOGY

    @property
    def methodology_is_provisional(self) -> bool:
        return True


def _to_ql_date(value) -> ql.Date:
    return ql.Date(value.day, value.month, value.year)


def build_provisional_projection_curve(
    market_data: SimpleForwardCurveMarketData,
    *,
    day_counter: ql.DayCounter,
    expected_currency: str,
    expected_benchmark: str,
) -> ProvisionalProjectionCurve:
    """Build a provisional QuantLib handle from simple reference-date quotes."""
    currency = expected_currency.strip().upper()
    benchmark = expected_benchmark.strip()
    if market_data.currency != currency:
        raise ValueError(
            f"projection curve currency {market_data.currency!r} does not match {currency!r}"
        )
    if market_data.benchmark != benchmark:
        raise ValueError(
            f"projection curve benchmark {market_data.benchmark!r} does not match "
            f"{benchmark!r}"
        )

    reference = _to_ql_date(market_data.reference_date)
    dates = [reference]
    discounts = [1.0]
    for observation in market_data.observations:
        pillar = _to_ql_date(observation.date)
        rate = float(observation.rate) / 100.0
        year_fraction = day_counter.yearFraction(reference, pillar)
        denominator = 1.0 + rate * year_fraction
        if denominator <= 0.0:
            raise ValueError(
                f"simple forward at {observation.date.isoformat()} implies "
                "a non-positive provisional discount factor"
            )
        dates.append(pillar)
        discounts.append(1.0 / denominator)

    curve = ql.DiscountCurve(dates, discounts, day_counter)
    handle = ql.YieldTermStructureHandle(curve)
    return ProvisionalProjectionCurve(market_data, curve, handle)
