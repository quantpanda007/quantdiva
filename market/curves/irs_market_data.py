"""Market-data and curve boundary for the fresh IRS implementation.

Discount-factor observations can be passed directly to QuantLib's
``DiscountCurve``. Dated simple-forward observations are retained as market
data only: their confirmed labels do not yet determine a unique QuantLib
projection term-structure construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional, Tuple, Union

import QuantLib as ql


DecimalLike = Union[Decimal, int, float, str]


def _decimal(value: DecimalLike, field_name: str) -> Decimal:
    result = value if isinstance(value, Decimal) else Decimal(str(value))
    if not result.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return result


def _validate_observation_dates(
    reference_date: date,
    observations: Tuple[object, ...],
) -> None:
    if not observations:
        raise ValueError("at least one market-data observation is required")
    dates = tuple(observation.date for observation in observations)
    if any(observation_date <= reference_date for observation_date in dates):
        raise ValueError("observation dates must be after the reference date")
    if any(left >= right for left, right in zip(dates, dates[1:])):
        raise ValueError("observation dates must be strictly increasing")


@dataclass(frozen=True)
class DiscountFactorObservation:
    """One supplied discount factor at a dated pillar."""

    date: date
    discount_factor: DecimalLike

    def __post_init__(self) -> None:
        value = _decimal(self.discount_factor, "discount_factor")
        if value <= 0:
            raise ValueError("discount_factor must be positive")
        object.__setattr__(self, "discount_factor", value)


@dataclass(frozen=True)
class SimpleForwardObservation:
    """One supplied simple-forward quote, preserved without transformation."""

    date: date
    rate: DecimalLike

    def __post_init__(self) -> None:
        object.__setattr__(self, "rate", _decimal(self.rate, "rate"))


@dataclass(frozen=True)
class DiscountCurveMarketData:
    """Dated, currency-specific discount-factor inputs."""

    reference_date: date
    currency: str
    observations: Tuple[DiscountFactorObservation, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "currency", self.currency.strip().upper())
        object.__setattr__(self, "observations", tuple(self.observations))
        if not self.currency:
            raise ValueError("currency is required")
        _validate_observation_dates(self.reference_date, self.observations)


@dataclass(frozen=True)
class SimpleForwardCurveMarketData:
    """Dated forward quotes keyed by currency and benchmark identity.

    This is intentionally a market-data representation, not a QuantLib
    projection curve. Construction of that curve remains unavailable until the
    forward-to-term-structure methodology is specified.
    """

    reference_date: date
    currency: str
    benchmark: str
    observations: Tuple[SimpleForwardObservation, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "currency", self.currency.strip().upper())
        object.__setattr__(self, "benchmark", self.benchmark.strip())
        object.__setattr__(self, "observations", tuple(self.observations))
        if not self.currency:
            raise ValueError("currency is required")
        if not self.benchmark:
            raise ValueError("benchmark is required")
        _validate_observation_dates(self.reference_date, self.observations)


@dataclass(frozen=True)
class IRSMarketData:
    """Separate discount and projection inputs for one IRS market context."""

    discount_curve: DiscountCurveMarketData
    projection_curve: SimpleForwardCurveMarketData

    def __post_init__(self) -> None:
        if self.discount_curve.currency != self.projection_curve.currency:
            raise ValueError("discount and projection currency values must match")
        if self.discount_curve.reference_date != self.projection_curve.reference_date:
            raise ValueError("discount and projection curve reference dates must match")


@dataclass(frozen=True)
class QuantLibDiscountCurve:
    """Built QuantLib discount term structure with its source observations."""

    market_data: DiscountCurveMarketData
    term_structure: ql.DiscountCurve
    handle: ql.YieldTermStructureHandle


class ProjectionCurveMethodologyUnspecified(ValueError):
    """Raised until confirmed forward-quote semantics determine a QL curve."""


def _to_ql_date(value: date) -> ql.Date:
    return ql.Date(value.day, value.month, value.year)


def build_discount_curve(
    market_data: DiscountCurveMarketData,
    *,
    day_counter: ql.DayCounter,
    expected_currency: Optional[str] = None,
) -> QuantLibDiscountCurve:
    """Build a direct QuantLib DiscountCurve from supplied DF observations.

    QuantLib requires the reference-date node to have DF 1.0. The anchor is
    added here; each supplied pillar value is passed through unchanged. The
    three-argument DiscountCurve constructor retains QuantLib's established
    LogLinear discount-factor interpolation default.
    """
    if expected_currency is not None and market_data.currency != expected_currency.strip().upper():
        raise ValueError(
            f"discount curve currency {market_data.currency!r} does not match "
            f"requested currency {expected_currency.strip().upper()!r}"
        )

    dates = [_to_ql_date(market_data.reference_date)]
    discounts = [1.0]
    dates.extend(_to_ql_date(item.date) for item in market_data.observations)
    discounts.extend(float(item.discount_factor) for item in market_data.observations)

    curve = ql.DiscountCurve(dates, discounts, day_counter)
    handle = ql.YieldTermStructureHandle(curve)
    return QuantLibDiscountCurve(
        market_data=market_data,
        term_structure=curve,
        handle=handle,
    )


def build_projection_curve(
    market_data: SimpleForwardCurveMarketData,
    *,
    expected_currency: Optional[str] = None,
    expected_benchmark: Optional[str] = None,
) -> None:
    """Stop at preserved observations until a QL conversion is specified."""
    if expected_currency is not None and market_data.currency != expected_currency.strip().upper():
        raise ValueError(
            f"projection curve currency {market_data.currency!r} does not match "
            f"requested currency {expected_currency.strip().upper()!r}"
        )
    if expected_benchmark is not None and market_data.benchmark != expected_benchmark.strip():
        raise ValueError(
            f"projection curve benchmark {market_data.benchmark!r} does not match "
            f"requested benchmark {expected_benchmark.strip()!r}"
        )
    raise ProjectionCurveMethodologyUnspecified(
        "dated simple-forward observations are preserved, but the confirmed "
        "inputs do not specify a QuantLib projection term-structure conversion"
    )
