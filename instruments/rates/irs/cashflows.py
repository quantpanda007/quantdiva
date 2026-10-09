"""Period-by-period cashflow rows for a built fresh IRS swap.

Reads the swap that was priced; it does not rebuild the trade, schedule,
coupons, rates or market environment, and it does not change any QuantLib
setting.

* Accrual dates, payment date and notional come from the contractual periods
  each built leg keeps; the tests check they match the QuantLib coupons.
* Day-count fraction, coupon rate, spread and amount come from the QuantLib
  coupons on the swap. For an overnight-indexed coupon the rate is QuantLib's
  compounded rate including the spread.
* The discount factor is ``discount_curve.discount(payment_date)``; the PV is the
  signed amount times that factor, which is how ``ql.DiscountingSwapEngine``
  values each cashflow when the curve's reference date is the evaluation date.
  Pass the curve the engine used (``market_env.discount_curves[currency]``).

Signs: amounts and PVs on the paid leg are negative, so each leg's PVs sum to
``swap.legNPV`` and all rows sum to ``swap.NPV()``.

Precondition: QuantLib's evaluation date must equal the discount curve's
reference date (the valuation date). The function checks this and raises
``CashflowExtractionError``; it never sets the evaluation date itself.

Already-paid cashflows are refused: if any coupon pays on or before the
valuation date, ``CashflowExtractionError`` is raised before anything is
discounted. (The engine excludes such cashflows; seasoned trades, including
historical fixings, are out of scope for now.)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional, Tuple

import QuantLib as ql

from instruments.rates.irs.fixed_leg import QuantLibFixedLeg
from instruments.rates.irs.floating_leg import QuantLibFloatingLeg
from instruments.rates.irs.instrument import QuantLibIRSInstrument


class CashflowExtractionError(RuntimeError):
    """Raised when cashflows cannot be read consistently from the built swap."""


@dataclass(frozen=True)
class IRSCashflowRow:
    """One coupon period of one leg, as priced."""

    leg: str  # "fixed" or "floating"
    side: str  # "pay" or "receive"
    period: int  # 1-based, in payment order
    accrual_start: date
    accrual_end: date
    payment_date: date
    notional: float  # unsigned contractual notional for the period
    day_count_fraction: float
    rate: float  # decimal; fixed coupon, or compounded overnight rate incl. spread
    spread: Optional[float]  # decimal; None for the fixed leg
    amount: float  # signed: negative on the paid leg
    discount_factor: float
    present_value: float  # signed: amount * discount_factor


def _py(value: ql.Date) -> date:
    return date(value.year(), value.month(), value.dayOfMonth())


def _leg_kind(leg) -> str:
    if isinstance(leg, QuantLibFixedLeg):
        return "fixed"
    if isinstance(leg, QuantLibFloatingLeg):
        return "floating"
    raise CashflowExtractionError(f"unsupported leg type {type(leg).__name__}")


def _leg_rows(
    leg,
    side: str,
    discount_curve: ql.YieldTermStructureHandle,
    valuation_date: ql.Date,
) -> Tuple[IRSCashflowRow, ...]:
    kind = _leg_kind(leg)
    sign = -1.0 if side == "pay" else 1.0
    periods = leg.contractual_schedule.periods
    if len(periods) != len(leg.coupons):
        raise CashflowExtractionError(
            f"{kind} leg has {len(leg.coupons)} coupons for {len(periods)} contractual periods"
        )
    rows = []
    for number, (period, coupon) in enumerate(zip(periods, leg.coupons), start=1):
        coupon_dates = (
            _py(coupon.accrualStartDate()),
            _py(coupon.accrualEndDate()),
            _py(coupon.date()),
        )
        if coupon_dates != (period.accrual_start, period.accrual_end, period.payment_date):
            raise CashflowExtractionError(
                f"{kind} period {number}: QuantLib coupon dates {coupon_dates} differ from the "
                "contractual period"
            )
        if coupon.date() <= valuation_date:
            raise CashflowExtractionError(
                f"{kind} period {number} pays on {coupon.date().ISO()}, on or before the "
                f"valuation date {valuation_date.ISO()}; already-paid cashflows are not "
                "supported (seasoned trades are out of scope)"
            )
        amount = sign * coupon.amount()
        discount_factor = discount_curve.discount(coupon.date())
        rows.append(
            IRSCashflowRow(
                leg=kind,
                side=side,
                period=number,
                accrual_start=period.accrual_start,
                accrual_end=period.accrual_end,
                payment_date=period.payment_date,
                notional=float(period.notional.amount),
                day_count_fraction=coupon.accrualPeriod(),
                rate=coupon.rate(),
                spread=coupon.spread() if kind == "floating" else None,
                amount=amount,
                discount_factor=discount_factor,
                present_value=amount * discount_factor,
            )
        )
    return tuple(rows)


def irs_cashflow_rows(
    built: QuantLibIRSInstrument,
    discount_curve: ql.YieldTermStructureHandle,
) -> Tuple[IRSCashflowRow, ...]:
    """Rows for the pay leg, then the receive leg, read from the priced swap."""
    if not isinstance(built, QuantLibIRSInstrument):
        raise CashflowExtractionError("built must be the QuantLibIRSInstrument that was priced")
    try:
        reference_date = discount_curve.referenceDate()
    except RuntimeError as exc:  # empty handle
        raise CashflowExtractionError(f"discount curve is not usable: {exc}") from exc
    evaluation_date = ql.Settings.instance().evaluationDate
    if evaluation_date != reference_date:
        raise CashflowExtractionError(
            f"QuantLib evaluation date {evaluation_date.ISO()} differs from the discount "
            f"curve reference date {reference_date.ISO()}; extract cashflows while the "
            "evaluation date used for pricing is still set"
        )
    return _leg_rows(built.pay_leg, "pay", discount_curve, reference_date) + _leg_rows(
        built.receive_leg, "receive", discount_curve, reference_date
    )
