"""Build QuantLib fixed coupons from an already-generated contractual schedule."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Tuple, Union, overload

import QuantLib as ql

from core.enums.definitions import DayCountConvention
from instruments.rates.irs.domain import IRSLegKind, IRSLegTerms
from instruments.rates.irs.quantlib_schedule import QuantLibLegSchedule


def _to_ql_date(value) -> ql.Date:
    return ql.Date(value.day, value.month, value.year)


def _day_counter(convention: DayCountConvention) -> ql.DayCounter:
    if convention is DayCountConvention.ACT_360:
        return ql.Actual360()
    if convention is DayCountConvention.ACT_365:
        return ql.Actual365Fixed()
    if convention is DayCountConvention.THIRTY_360:
        # The requirements baseline records this mapping as established repository behavior.
        return ql.Thirty360(ql.Thirty360.BondBasis)
    raise ValueError(f"fixed-leg day count {convention.value!r} is not supported")


@dataclass(frozen=True)
class QuantLibFixedLeg:
    """Native QuantLib Leg with coupon references and contractual period metadata."""

    quantlib_leg: ql.Leg
    coupons: Tuple[ql.FixedRateCoupon, ...]
    contractual_schedule: QuantLibLegSchedule

    def __len__(self) -> int:
        return len(self.coupons)

    def __iter__(self) -> Iterator[ql.FixedRateCoupon]:
        return iter(self.coupons)

    @overload
    def __getitem__(self, index: int) -> ql.FixedRateCoupon: ...

    @overload
    def __getitem__(self, index: slice) -> Tuple[ql.FixedRateCoupon, ...]: ...

    def __getitem__(self, index: Union[int, slice]):
        return self.coupons[index]


def build_fixed_leg(
    terms: IRSLegTerms,
    contractual_schedule: QuantLibLegSchedule,
) -> QuantLibFixedLeg:
    """Create a fixed coupon for each contractual period without valuation.

    ``FixedRateLeg`` cannot encode arbitrary per-period payment dates. Individual
    ``FixedRateCoupon`` objects preserve each contractual payment date and nominal,
    and are also collected into a native ``ql.Leg`` for downstream instruments.
    """
    if terms.kind is not IRSLegKind.FIXED:
        raise ValueError("build_fixed_leg requires fixed leg terms")
    if terms.fixed_coupon_rate is None:
        raise ValueError("fixed_coupon_rate is required for a fixed leg")

    day_counter = _day_counter(terms.day_count)
    coupon_rate = float(terms.fixed_coupon_rate)
    coupons = []
    quantlib_leg = ql.Leg()

    for period in contractual_schedule.periods:
        coupon = ql.FixedRateCoupon(
            _to_ql_date(period.payment_date),
            float(period.notional.amount),
            coupon_rate,
            day_counter,
            _to_ql_date(period.accrual_start),
            _to_ql_date(period.accrual_end),
        )
        coupons.append(coupon)
        quantlib_leg.append(coupon)

    return QuantLibFixedLeg(
        quantlib_leg=quantlib_leg,
        coupons=tuple(coupons),
        contractual_schedule=contractual_schedule,
    )
