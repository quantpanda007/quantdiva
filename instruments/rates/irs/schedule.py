"""Pure contractual IRS schedule generation; contains no QuantLib/pricing code."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional, Tuple

from core.enums.definitions import Frequency
from core.types.value_objects import Money
from instruments.rates.irs.domain import IRSLegTerms, IRSTrade, PrincipalRepayment


class ScheduleDirection(str, Enum):
    FORWARD = "forward"
    BACKWARD = "backward"


class RepaymentTreatment(str, Enum):
    """Explicit notional treatment; no sign interpretation is applied implicitly."""

    ABSOLUTE_AMOUNT_REDUCES_NOTIONAL = "absolute_amount_reduces_notional"


@dataclass(frozen=True)
class ScheduleGeneration:
    """Explicit date-generation inputs for one leg.

    ``next_to_last_date`` is an explicit contractual boundary for schedules with a
    final stub. No universal stub rule is inferred from payment frequency.
    Explicit payment dates can be supplied when they differ from accrual ends. If
    absent, payment dates are left unadjusted at accrual ends.
    """

    direction: ScheduleDirection
    next_to_last_date: Optional[date] = None
    payment_dates: Optional[Tuple[date, ...]] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "direction", ScheduleDirection(self.direction))
        if self.payment_dates is not None:
            object.__setattr__(self, "payment_dates", tuple(self.payment_dates))


@dataclass(frozen=True)
class CouponPeriod:
    accrual_start: date
    accrual_end: date
    payment_date: date
    notional: Money


@dataclass(frozen=True)
class LegSchedule:
    periods: Tuple[CouponPeriod, ...]
    principal_repayments: Tuple[PrincipalRepayment, ...]


_FREQUENCY_MONTHS = {
    Frequency.ANNUAL: 12,
    Frequency.SEMIANNUAL: 6,
    Frequency.QUARTERLY: 3,
    Frequency.MONTHLY: 1,
}


def _shift_months(value: date, months: int) -> date:
    """Move by calendar months without silently applying an end-of-month rule."""
    month_index = value.year * 12 + value.month - 1 + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    try:
        return date(year, month, value.day)
    except ValueError as exc:
        raise ValueError(
            f"Frequency stepping from {value.isoformat()} would require an "
            "unspecified end-of-month/roll convention; provide explicit schedule boundaries"
        ) from exc


def _boundaries(
    effective: date,
    maturity: date,
    months: int,
    generation: ScheduleGeneration,
) -> Tuple[date, ...]:
    if not effective < maturity:
        raise ValueError("effective_date must be before maturity_date")

    if generation.next_to_last_date is not None:
        anchor = generation.next_to_last_date
        if generation.direction is not ScheduleDirection.BACKWARD:
            raise ValueError("next_to_last_date requires backward generation")
        if not effective < anchor < maturity:
            raise ValueError("next_to_last_date must be strictly inside the trade interval")

        descending = [maturity, anchor]
        cursor = anchor
        while True:
            previous = _shift_months(cursor, -months)
            if previous <= effective:
                break
            descending.append(previous)
            cursor = previous
        return (effective, *reversed(descending))

    if generation.direction is ScheduleDirection.BACKWARD:
        descending = [maturity]
        cursor = maturity
        while True:
            previous = _shift_months(cursor, -months)
            if previous <= effective:
                if previous != effective:
                    raise ValueError(
                        "frequency does not divide the trade interval; provide an "
                        "explicit stub boundary instead of relying on an unspecified stub rule"
                    )
                break
            descending.append(previous)
            cursor = previous
        return (effective, *reversed(descending))

    ascending = [effective]
    cursor = effective
    while True:
        following = _shift_months(cursor, months)
        if following >= maturity:
            if following != maturity:
                raise ValueError(
                    "frequency does not divide the trade interval; provide explicit "
                    "schedule boundaries instead of relying on an unspecified stub rule"
                )
            break
        ascending.append(following)
        cursor = following
    ascending.append(maturity)
    return tuple(ascending)


def generate_leg_schedule(
    trade: IRSTrade,
    leg: IRSLegTerms,
    generation: ScheduleGeneration,
    *,
    repayment_treatment: Optional[RepaymentTreatment] = None,
) -> LegSchedule:
    """Generate unadjusted coupon periods and outstanding notionals for one leg.

    Repayments are retained as dated amount entries. When period notionals must be
    updated, callers must explicitly choose the supported amount treatment. A
    repayment dated within a coupon period affects only periods whose accrual start
    is on or after that repayment date. This produces no principal cashflow.
    """
    if leg is not trade.pay_leg and leg is not trade.receive_leg:
        raise ValueError("leg must be one of the trade's independently defined legs")
    try:
        months = _FREQUENCY_MONTHS[leg.payment_frequency]
    except KeyError as exc:
        raise ValueError(
            f"payment frequency {leg.payment_frequency.value!r} is not supported by this schedule layer"
        ) from exc

    repayments = tuple(leg.principal_repayments)
    treatment = None if repayment_treatment is None else RepaymentTreatment(repayment_treatment)
    if repayments and treatment is None:
        raise ValueError("repayment_treatment must be explicit when repayments are present")

    dates = _boundaries(trade.effective_date, trade.maturity_date, months, generation)
    count = len(dates) - 1
    if generation.payment_dates is not None and len(generation.payment_dates) != count:
        raise ValueError("payment_dates must contain one date for each coupon period")

    initial_notional = leg.original_notional.amount
    ordered_repayments = tuple(sorted(repayments, key=lambda item: item.payment_date))
    periods = []
    for index, (start, end) in enumerate(zip(dates, dates[1:])):
        notional = initial_notional
        if treatment is RepaymentTreatment.ABSOLUTE_AMOUNT_REDUCES_NOTIONAL:
            for repayment in ordered_repayments:
                if repayment.payment_date <= start:
                    if repayment.amount.currency != leg.original_notional.currency:
                        raise ValueError("repayment and original notional currencies must match")
                    notional -= abs(repayment.amount.amount)

        payment_date = (
            generation.payment_dates[index]
            if generation.payment_dates is not None
            else end
        )
        periods.append(
            CouponPeriod(
                accrual_start=start,
                accrual_end=end,
                payment_date=payment_date,
                notional=Money(Decimal(notional), leg.original_notional.currency),
            )
        )

    return LegSchedule(periods=tuple(periods), principal_repayments=repayments)
