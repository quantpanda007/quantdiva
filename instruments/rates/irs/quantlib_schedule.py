"""Translate contractual IRS accrual boundaries to explicit QuantLib schedules.

The contractual ``LegSchedule`` remains authoritative. QuantLib receives only its
explicit accrual date vector; no date generation, adjustment, stub, or calendar
rules are inferred in this translation layer. Payment dates, notionals, and
repayments remain attached to the contractual periods alongside the QL schedule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Tuple

import QuantLib as ql

from core.types.value_objects import Money
from instruments.rates.irs.domain import PrincipalRepayment
from instruments.rates.irs.schedule import CouponPeriod, LegSchedule


def _to_ql_date(value: date) -> ql.Date:
    return ql.Date(value.day, value.month, value.year)


def _to_python_date(value: ql.Date) -> date:
    return date(value.year(), value.month(), value.dayOfMonth())


@dataclass(frozen=True)
class QuantLibLegSchedule:
    """QuantLib accrual schedule plus unchanged contractual period metadata."""

    quantlib_schedule: ql.Schedule
    contractual_schedule: LegSchedule

    @property
    def periods(self) -> Tuple[CouponPeriod, ...]:
        return self.contractual_schedule.periods

    @property
    def principal_repayments(self) -> Tuple[PrincipalRepayment, ...]:
        return self.contractual_schedule.principal_repayments

    @property
    def accrual_dates(self) -> Tuple[date, ...]:
        return tuple(_to_python_date(d) for d in self.quantlib_schedule)


@dataclass(frozen=True)
class QuantLibIRSSchedules:
    """Independent translated schedules for the trade's Pay and Receive legs."""

    pay: QuantLibLegSchedule
    receive: QuantLibLegSchedule


def translate_leg_schedule(contractual: LegSchedule) -> QuantLibLegSchedule:
    """Build a QL Schedule from explicit accrual dates without generating dates."""
    periods = contractual.periods
    if not periods:
        raise ValueError("cannot translate an empty contractual schedule")

    for previous, current in zip(periods, periods[1:]):
        if previous.accrual_end != current.accrual_start:
            raise ValueError("contractual accrual periods must be contiguous")

    python_dates = (periods[0].accrual_start,) + tuple(
        period.accrual_end for period in periods
    )
    if any(left >= right for left, right in zip(python_dates, python_dates[1:])):
        raise ValueError("contractual accrual dates must be strictly increasing")

    # Explicit DateVector constructor: no tenor, DateGeneration rule, or EOM rule
    # is supplied. NullCalendar + Unadjusted ensures the vector is not adjusted.
    dates = ql.DateVector([_to_ql_date(value) for value in python_dates])
    ql_schedule = ql.Schedule(
        dates,
        ql.NullCalendar(),
        ql.Unadjusted,
        ql.Unadjusted,
    )
    if tuple(_to_python_date(d) for d in ql_schedule) != python_dates:
        raise RuntimeError("QuantLib Schedule did not preserve the contractual accrual dates")

    return QuantLibLegSchedule(
        quantlib_schedule=ql_schedule,
        contractual_schedule=contractual,
    )


def translate_irs_schedules(
    pay_schedule: LegSchedule,
    receive_schedule: LegSchedule,
) -> QuantLibIRSSchedules:
    """Translate Pay and Receive schedules independently, preserving each sidecar."""
    return QuantLibIRSSchedules(
        pay=translate_leg_schedule(pay_schedule),
        receive=translate_leg_schedule(receive_schedule),
    )
