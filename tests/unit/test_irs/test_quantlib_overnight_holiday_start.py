"""Standalone QuantLib regression: SOFR coupon whose accrual starts on a holiday.

QuantLib <= 1.42.1 starts compounding on the next business day when the accrual
start is a fixing-calendar holiday, but still annualises over the full accrual
period, so the first day's interest is lost (-1.13 bp on this flat-curve case).
QuantLib 1.43 (PR #2556, commit 5348d7a) accrues the holiday start day at the
preceding business day's fixing. These tests pin the 1.43 behaviour.

Uses QuantLib only: no Optima builders, fixtures, or market data.
"""

from __future__ import annotations

import pytest
import QuantLib as ql

EVALUATION_DATE = ql.Date(31, 3, 2026)
SUNDAY_START = ql.Date(31, 5, 2026)
PRECEDING_FRIDAY = ql.Date(29, 5, 2026)
NEXT_MONDAY = ql.Date(1, 6, 2026)
END = ql.Date(28, 5, 2027)
NOTIONAL = 1_000_000.0
RATE_TOLERANCE = 1e-7  # 0.001 bp


@pytest.fixture(autouse=True)
def _evaluation_date():
    previous = ql.Settings.instance().evaluationDate
    ql.Settings.instance().evaluationDate = EVALUATION_DATE
    yield
    ql.Settings.instance().evaluationDate = previous


@pytest.fixture
def curve():
    return ql.YieldTermStructureHandle(
        ql.FlatForward(EVALUATION_DATE, 0.04, ql.Actual365Fixed(), ql.Continuous)
    )


def _coupon(start: ql.Date, curve) -> ql.OvernightIndexedCoupon:
    coupon = ql.OvernightIndexedCoupon(END, NOTIONAL, start, END, ql.Sofr(curve))
    coupon.setPricer(ql.CompoundingOvernightIndexedCouponPricer())
    return coupon


def _discount_ratio_rate(start: ql.Date, curve) -> float:
    """Exact compounded overnight rate implied by the curve over the accrual period."""
    accrual = ql.Actual360().yearFraction(start, END)
    return (curve.discount(start) / curve.discount(END) - 1.0) / accrual


def test_calendar_premise_sunday_start_is_a_sofr_fixing_holiday():
    calendar = ql.Sofr().fixingCalendar()
    assert SUNDAY_START.weekday() == ql.Sunday
    assert not calendar.isBusinessDay(SUNDAY_START)
    assert calendar.adjust(SUNDAY_START, ql.Preceding) == PRECEDING_FRIDAY


def test_holiday_start_first_observation_uses_preceding_business_day_fixing(curve):
    coupon = _coupon(SUNDAY_START, curve)

    assert coupon.fixingDates()[0] == PRECEDING_FRIDAY
    assert coupon.valueDates()[0] == PRECEDING_FRIDAY
    assert coupon.valueDates()[1] == NEXT_MONDAY
    # Interest accrues from the contractual (unadjusted) start date.
    assert coupon.interestDates()[0] == SUNDAY_START
    assert coupon.interestDates()[1] == NEXT_MONDAY
    assert coupon.dt()[0] == pytest.approx(1.0 / 360.0, abs=1e-15)


def test_holiday_start_includes_initial_day_interest(curve):
    coupon = _coupon(SUNDAY_START, curve)

    accrual_days = END - SUNDAY_START
    assert accrual_days == 362
    assert coupon.accrualDays() == accrual_days
    # Compounding covers the whole accrual period: no day is dropped.
    assert sum(coupon.dt()) * 360.0 == pytest.approx(accrual_days, abs=1e-9)
    assert coupon.interestDates()[-1] == END
    # QL <= 1.42.1 gives -1.1339 bp here; 1.43 matches the discount ratio.
    assert coupon.rate() == pytest.approx(
        _discount_ratio_rate(SUNDAY_START, curve), abs=RATE_TOLERANCE
    )


@pytest.mark.parametrize("start", [PRECEDING_FRIDAY, NEXT_MONDAY], ids=["friday", "monday"])
def test_business_day_start_controls_match_discount_ratio(curve, start):
    coupon = _coupon(start, curve)

    assert coupon.fixingDates()[0] == start
    assert coupon.interestDates()[0] == start
    assert sum(coupon.dt()) * 360.0 == pytest.approx(END - start, abs=1e-9)
    assert coupon.rate() == pytest.approx(_discount_ratio_rate(start, curve), abs=RATE_TOLERANCE)


def test_sunday_start_accrues_one_more_day_than_monday_start(curve):
    """The Sunday coupon must not collapse into the Monday coupon (the pre-1.43 defect)."""
    sunday = _coupon(SUNDAY_START, curve)
    monday = _coupon(NEXT_MONDAY, curve)

    assert len(sunday.fixingDates()) == len(monday.fixingDates()) + 1
    assert sunday.amount() - monday.amount() == pytest.approx(
        NOTIONAL * 0.04 / 360.0, rel=0.05
    )  # roughly one day's interest at ~4%
