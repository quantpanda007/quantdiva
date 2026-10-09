"""Zero-rate curve construction for the fresh IRS implementation.

Builds a QuantLib zero curve from tenor-keyed zero-rate observations under
fully explicit conventions. Pillar dates are derived from the tenors (spot lag,
calendar, business-day convention); they are never taken from display dates.

Input is structured market data only. This module does not read files and does
not know any fixture or vendor export format, so the same builder can later be
fed from an external market-data source.

Supported methodology (anything else is rejected, not silently defaulted):
* zero rates continuously compounded on the supplied day counter;
* linear interpolation in zero rate between pillars;
* flat extension of the first pillar's zero rate back to the reference date.

Optional supplied discount factors are used only as a consistency check on the
derived pillar dates; they never alter the curve.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional, Tuple, Union

import QuantLib as ql

DecimalLike = Union[Decimal, int, float, str]

LINEAR_ZERO = "linear_zero"
FLAT_FIRST_ZERO = "flat_first_zero"
_SUPPORTED_INTERPOLATION = (LINEAR_ZERO,)
_SUPPORTED_FRONT_EXTRAPOLATION = (FLAT_FIRST_ZERO,)
_SUPPORTED_COMPOUNDING = (ql.Continuous,)


class UnsupportedZeroCurveConvention(ValueError):
    """Raised for conventions this builder does not implement."""


class ZeroCurveConsistencyError(ValueError):
    """Raised when a supplied discount factor contradicts the derived pillar."""


def _to_ql_date(value: date) -> ql.Date:
    return ql.Date(value.day, value.month, value.year)


def _to_python_date(value: ql.Date) -> date:
    return date(value.year(), value.month(), value.dayOfMonth())


def _finite_decimal(value: DecimalLike, field_name: str) -> Decimal:
    result = value if isinstance(value, Decimal) else Decimal(str(value))
    if not result.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return result


@dataclass(frozen=True)
class ZeroCurveObservation:
    """One pillar: market tenor, decimal zero rate, optional check DF."""

    tenor: str
    zero_rate: DecimalLike
    discount_factor: Optional[DecimalLike] = None

    def __post_init__(self) -> None:
        tenor = self.tenor.strip().upper()
        if not tenor:
            raise ValueError("tenor is required")
        try:
            ql.Period(tenor)
        except RuntimeError as exc:
            raise ValueError(f"invalid tenor {self.tenor!r}") from exc
        object.__setattr__(self, "tenor", tenor)

        rate = _finite_decimal(self.zero_rate, "zero_rate")
        if abs(rate) >= 1:
            raise ValueError(
                f"zero_rate {rate} for {tenor} looks like a percentage; supply a decimal rate"
            )
        object.__setattr__(self, "zero_rate", rate)

        if self.discount_factor is not None:
            factor = _finite_decimal(self.discount_factor, "discount_factor")
            if factor <= 0:
                raise ValueError("discount_factor must be positive")
            object.__setattr__(self, "discount_factor", factor)


@dataclass(frozen=True)
class ZeroCurveMarketData:
    """Dated, currency- and benchmark-keyed zero-rate observations."""

    reference_date: date
    currency: str
    benchmark: str
    observations: Tuple[ZeroCurveObservation, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "currency", self.currency.strip().upper())
        object.__setattr__(self, "benchmark", self.benchmark.strip())
        object.__setattr__(self, "observations", tuple(self.observations))
        if not self.currency:
            raise ValueError("currency is required")
        if not self.benchmark:
            raise ValueError("benchmark is required")
        if not self.observations:
            raise ValueError("at least one zero-rate observation is required")


@dataclass(frozen=True)
class ZeroCurveConventions:
    """Every convention is explicit; there are no defaults."""

    calendar: ql.Calendar
    spot_lag_days: int
    business_day_convention: int
    end_of_month: bool
    day_counter: ql.DayCounter
    compounding: int
    interpolation: str
    front_extrapolation: str
    allow_extrapolation: bool
    discount_factor_tolerance: float

    def __post_init__(self) -> None:
        # bool is a subclass of int, so reject it explicitly.
        if isinstance(self.spot_lag_days, bool) or not isinstance(self.spot_lag_days, int):
            raise TypeError(
                f"spot_lag_days must be an int, got {type(self.spot_lag_days).__name__}"
            )
        if self.spot_lag_days < 0:
            raise ValueError("spot_lag_days cannot be negative")
        if not isinstance(self.end_of_month, bool):
            raise TypeError(
                f"end_of_month must be a bool, got {type(self.end_of_month).__name__}"
            )
        if self.compounding not in _SUPPORTED_COMPOUNDING:
            raise UnsupportedZeroCurveConvention(
                "only continuously compounded zero rates are supported"
            )
        if self.interpolation not in _SUPPORTED_INTERPOLATION:
            raise UnsupportedZeroCurveConvention(
                f"unsupported interpolation {self.interpolation!r}; "
                f"supported: {_SUPPORTED_INTERPOLATION}"
            )
        if self.front_extrapolation not in _SUPPORTED_FRONT_EXTRAPOLATION:
            raise UnsupportedZeroCurveConvention(
                f"unsupported front extrapolation {self.front_extrapolation!r}; "
                f"supported: {_SUPPORTED_FRONT_EXTRAPOLATION}"
            )
        tolerance = self.discount_factor_tolerance
        if not (tolerance > 0 and math.isfinite(tolerance)):
            raise ValueError("discount_factor_tolerance must be a positive finite number")


@dataclass(frozen=True)
class QuantLibZeroCurve:
    """Built QuantLib zero curve with its inputs and derived pillar dates."""

    market_data: ZeroCurveMarketData
    conventions: ZeroCurveConventions
    spot_date: date
    pillar_dates: Tuple[date, ...]
    term_structure: ql.ZeroCurve
    handle: ql.YieldTermStructureHandle


def derive_pillar_dates(
    reference_date: date,
    tenors: Tuple[str, ...],
    conventions: ZeroCurveConventions,
) -> Tuple[date, Tuple[date, ...]]:
    """Spot = reference + spot lag business days; pillar = spot + tenor, adjusted."""
    calendar = conventions.calendar
    spot = calendar.advance(_to_ql_date(reference_date), conventions.spot_lag_days, ql.Days)
    pillars = tuple(
        calendar.advance(
            spot,
            ql.Period(tenor),
            conventions.business_day_convention,
            conventions.end_of_month,
        )
        for tenor in tenors
    )
    return _to_python_date(spot), tuple(_to_python_date(p) for p in pillars)


def build_zero_curve(
    market_data: ZeroCurveMarketData,
    conventions: ZeroCurveConventions,
    *,
    expected_currency: Optional[str] = None,
    expected_benchmark: Optional[str] = None,
) -> QuantLibZeroCurve:
    """Build the curve; reject inconsistent inputs rather than adjusting them."""
    if expected_currency is not None and market_data.currency != expected_currency.strip().upper():
        raise ValueError(
            f"zero curve currency {market_data.currency!r} does not match "
            f"requested currency {expected_currency.strip().upper()!r}"
        )
    if expected_benchmark is not None and market_data.benchmark != expected_benchmark.strip():
        raise ValueError(
            f"zero curve benchmark {market_data.benchmark!r} does not match "
            f"requested benchmark {expected_benchmark.strip()!r}"
        )

    observations = market_data.observations
    spot, pillars = derive_pillar_dates(
        market_data.reference_date, tuple(o.tenor for o in observations), conventions
    )
    if pillars[0] <= market_data.reference_date:
        raise ValueError("first pillar must fall after the reference date")
    if any(left >= right for left, right in zip(pillars, pillars[1:])):
        raise ValueError("tenors must produce strictly increasing pillar dates")

    reference = _to_ql_date(market_data.reference_date)
    day_counter = conventions.day_counter
    mismatches = []
    for observation, pillar in zip(observations, pillars):
        if observation.discount_factor is None:
            continue
        implied = ql.InterestRate(
            float(observation.zero_rate), day_counter, conventions.compounding, ql.Annual
        ).discountFactor(reference, _to_ql_date(pillar))
        supplied = float(observation.discount_factor)
        if abs(implied - supplied) > conventions.discount_factor_tolerance:
            mismatches.append(
                f"{observation.tenor} -> {pillar.isoformat()}: implied {implied:.8f}, "
                f"supplied {supplied:.8f}"
            )
    if mismatches:
        raise ZeroCurveConsistencyError(
            "supplied discount factors contradict the derived pillar dates/conventions: "
            + "; ".join(mismatches)
        )

    rates = [float(o.zero_rate) for o in observations]
    term_structure = ql.ZeroCurve(
        [reference] + [_to_ql_date(p) for p in pillars],
        [rates[0]] + rates,  # FLAT_FIRST_ZERO: first pillar rate at the reference date
        day_counter,
        conventions.calendar,
        ql.Linear(),
        conventions.compounding,
        ql.Annual,
    )
    if conventions.allow_extrapolation:
        term_structure.enableExtrapolation()
    handle = ql.YieldTermStructureHandle(term_structure)
    return QuantLibZeroCurve(
        market_data=market_data,
        conventions=conventions,
        spot_date=spot,
        pillar_dates=pillars,
        term_structure=term_structure,
        handle=handle,
    )
