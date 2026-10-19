"""QuantLib-native floating coupon construction with explicit benchmark mapping."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterator, Optional, Tuple, Union, overload

import QuantLib as ql

from core.enums.definitions import DayCountConvention, Frequency
from instruments.rates.irs.domain import (
    IRSLegKind,
    IRSLegTerms,
    ObservationConventions,
)
from instruments.rates.irs.quantlib_schedule import QuantLibLegSchedule


class UnsupportedBenchmarkMapping(ValueError):
    """The benchmark/tenor/currency combination has no confirmed QuantLib mapping."""


def _to_ql_date(value: date) -> ql.Date:
    return ql.Date(value.day, value.month, value.year)


def _day_counter(convention: DayCountConvention) -> ql.DayCounter:
    if convention is DayCountConvention.ACT_360:
        return ql.Actual360()
    if convention is DayCountConvention.ACT_365:
        return ql.Actual365Fixed()
    if convention is DayCountConvention.THIRTY_360:
        return ql.Thirty360(ql.Thirty360.BondBasis)
    raise ValueError(f"floating-leg day count {convention.value!r} is not supported")


def _to_python_date(value: ql.Date) -> date:
    return date(value.year(), value.month(), value.dayOfMonth())


_OVERNIGHT_BENCHMARKS = {
    ("SOFRRATE", "1D", "USD", Frequency.DAILY): ql.Sofr,
    ("MUTKCALM", "1D", "JPY", Frequency.DAILY): ql.Tonar,
}


def build_floating_index(
    terms: IRSLegTerms,
    currency: str,
    forwarding_curve: Optional[ql.YieldTermStructureHandle] = None,
) -> ql.OvernightIndex:
    """Map only the supported daily-reset overnight benchmarks.

    USD SOFRRATE 1D -> ql.Sofr (confirmed on TC1/TC3). JPY MUTKCALM 1D (Bloomberg's
    TONA ticker) -> ql.Tonar: the JPY OIS bootstrap on ql.Japan reproduces Bloomberg's
    TC6/TC10 discount factors (OI-16); the mapping is not SME-confirmed."""
    if terms.kind is not IRSLegKind.FLOATING:
        raise ValueError("build_floating_index requires floating leg terms")

    mapping = (terms.benchmark, terms.benchmark_tenor, currency, terms.reset_frequency)
    factory = _OVERNIGHT_BENCHMARKS.get(mapping)
    if factory is None:
        raise UnsupportedBenchmarkMapping(
            "unsupported floating benchmark mapping "
            f"{mapping!r}; supported: {sorted(_OVERNIGHT_BENCHMARKS, key=str)}"
        )
    return factory(forwarding_curve) if forwarding_curve is not None else factory()


@dataclass(frozen=True)
class FloatingObservationMapping:
    """QuantLib observation settings plus the untouched contractual convention."""

    contractual: ObservationConventions
    lookback_days: int
    quantlib_lockout_days: int
    in_arrears: bool
    averaging_method: int
    apply_observation_shift: bool
    compound_spread_daily: bool
    cutoff_mapping: Optional[str] = None

    @property
    def cutoff_days(self) -> int:
        # Rate cutoff is retained in the domain; it is not mapped to lockoutDays.
        assert self.contractual.cutoff_days is not None
        return self.contractual.cutoff_days


@dataclass(frozen=True)
class CouponObservationDates:
    """Generated observation dates for one contractual coupon period."""

    fixing_dates: Tuple[date, ...]
    value_dates: Tuple[date, ...]
    interest_dates: Tuple[date, ...]


@dataclass(frozen=True)
class FloatingObservationSchedule:
    """Reset/observation date sequences, separate from leg terms and coupons."""

    periods: Tuple[CouponObservationDates, ...]


@dataclass(frozen=True)
class QuantLibFloatingLeg:
    """Native QuantLib leg plus typed coupons and contractual inputs for audit."""

    quantlib_leg: ql.Leg
    coupons: Tuple[ql.OvernightIndexedCoupon, ...]
    index: ql.OvernightIndex
    terms: IRSLegTerms
    contractual_schedule: QuantLibLegSchedule
    observation_settings: FloatingObservationMapping
    observation_schedule: FloatingObservationSchedule

    def __len__(self) -> int:
        return len(self.coupons)

    def __iter__(self) -> Iterator[ql.OvernightIndexedCoupon]:
        return iter(self.coupons)

    @overload
    def __getitem__(self, index: int) -> ql.OvernightIndexedCoupon: ...

    @overload
    def __getitem__(self, index: slice) -> Tuple[ql.OvernightIndexedCoupon, ...]: ...

    def __getitem__(self, index: Union[int, slice]):
        return self.coupons[index]


def _observation_mapping(
    observation: Optional[ObservationConventions],
) -> FloatingObservationMapping:
    if observation is None:
        raise ValueError("floating observation conventions must be explicit")
    required = {
        "lookback_days": observation.lookback_days,
        "cutoff_days": observation.cutoff_days,
        "reset_timing": observation.reset_timing,
        "compounding": observation.compounding,
        "lookback_type": observation.lookback_type,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise ValueError(f"floating observation conventions require {', '.join(missing)}")
    if observation.lookback_type != "Lookback":
        raise ValueError(f"unsupported lookback type {observation.lookback_type!r}")

    reset_timing = observation.reset_timing.strip().lower()
    if reset_timing == "in arrears":
        in_arrears = True
    elif reset_timing == "in advance":
        in_arrears = False
    else:
        raise ValueError(f"unsupported reset timing {observation.reset_timing!r}")

    if observation.compounding != "ExcludeSprd":
        raise ValueError(
            f"unsupported spread-compounding convention {observation.compounding!r}"
        )

    return FloatingObservationMapping(
        contractual=observation,
        lookback_days=observation.lookback_days,
        # QuantLib calls this lockoutDays. The requirements keep rate cutoff distinct
        # and do not confirm that rate cutoff is a lockout, so no mapping is made.
        quantlib_lockout_days=0,
        in_arrears=in_arrears,
        averaging_method=ql.RateAveraging.Compound,
        apply_observation_shift=False,
        compound_spread_daily=False,
        cutoff_mapping=None,
    )


def build_floating_leg(
    terms: IRSLegTerms,
    contractual_schedule: QuantLibLegSchedule,
    currency: str,
    *,
    forwarding_curve: Optional[ql.YieldTermStructureHandle] = None,
) -> QuantLibFloatingLeg:
    """Build explicit overnight coupons from one leg's translated schedule.

    No curve, fixing forecast, payment adjustment, or valuation is performed here.
    Rate cutoff remains contractual metadata until its equivalence to QuantLib's
    lockout convention is confirmed.
    """
    if terms.kind is not IRSLegKind.FLOATING:
        raise ValueError("build_floating_leg requires floating leg terms")
    if terms.floating_spread_rate is None or terms.floating_leverage is None:
        raise ValueError("floating spread and leverage must be explicit")

    index = build_floating_index(terms, currency, forwarding_curve)
    observation = _observation_mapping(terms.observation)
    day_counter = _day_counter(terms.day_count)
    periods = contractual_schedule.periods

    notionals = ql.DoubleVector([float(period.notional.amount) for period in periods])
    gearings = ql.DoubleVector([float(terms.floating_leverage)] * len(periods))
    spreads = ql.DoubleVector([float(terms.floating_spread_rate)] * len(periods))
    payment_dates = ql.DateVector(
        [_to_ql_date(period.payment_date) for period in periods]
    )

    # OvernightLeg owns QuantLib's reset/observation construction. Explicit dates,
    # NullCalendar, and Unadjusted prevent this builder from changing the contract.
    quantlib_leg = ql.OvernightLeg(
        notionals,
        contractual_schedule.quantlib_schedule,
        index,
        day_counter,
        ql.Unadjusted,
        gearings=gearings,
        spreads=spreads,
        telescopicValueDates=False,
        averagingMethod=observation.averaging_method,
        paymentCalendar=ql.NullCalendar(),
        paymentLag=0,
        lookbackDays=observation.lookback_days,
        lockoutDays=observation.quantlib_lockout_days,
        applyObservationShift=observation.apply_observation_shift,
        compoundSpreadDaily=observation.compound_spread_daily,
        inArrears=observation.in_arrears,
        paymentDates=payment_dates,
    )
    coupons = tuple(ql.as_overnight_indexed_coupon(cashflow) for cashflow in quantlib_leg)

    if len(coupons) != len(periods):
        raise RuntimeError("QuantLib OvernightLeg did not preserve contractual period count")

    observation_schedule = FloatingObservationSchedule(
        periods=tuple(
            CouponObservationDates(
                fixing_dates=tuple(_to_python_date(d) for d in coupon.fixingDates()),
                value_dates=tuple(_to_python_date(d) for d in coupon.valueDates()),
                interest_dates=tuple(_to_python_date(d) for d in coupon.interestDates()),
            )
            for coupon in coupons
        )
    )

    return QuantLibFloatingLeg(
        quantlib_leg=quantlib_leg,
        coupons=coupons,
        index=index,
        terms=terms,
        contractual_schedule=contractual_schedule,
        observation_settings=observation,
        observation_schedule=observation_schedule,
    )
