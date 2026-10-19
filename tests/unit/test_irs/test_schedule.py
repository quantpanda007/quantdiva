from datetime import date
from decimal import Decimal

import pytest

from core.enums.definitions import DayCountConvention, Frequency
from core.types.value_objects import Money
from instruments.rates.irs.domain import (
    IRSLegTerms,
    IRSTrade,
    PrincipalRepayment,
)
from instruments.rates.irs.schedule import (
    RepaymentTreatment,
    ScheduleDirection,
    ScheduleGeneration,
    generate_leg_schedule,
)


def _fixed_leg(frequency, notional, repayments=()):
    return IRSLegTerms(
        kind="fixed",
        payment_frequency=frequency,
        day_count=DayCountConvention.ACT_360,
        original_notional=Money(Decimal(str(notional)), "USD"),
        fixed_coupon_rate=Decimal("0.05"),
        principal_repayments=tuple(repayments),
    )


def _floating_leg(frequency, notional, repayments=()):
    return IRSLegTerms(
        kind="floating",
        payment_frequency=frequency,
        day_count=DayCountConvention.ACT_360,
        original_notional=Money(Decimal(str(notional)), "USD"),
        benchmark="SOFRRATE",
        benchmark_tenor="1D",
        floating_spread_rate=Decimal("0.001"),
        floating_leverage=Decimal("1"),
        reset_frequency=Frequency.DAILY,
        principal_repayments=tuple(repayments),
    )


def _trade(pay_leg, receive_leg, effective, maturity):
    return IRSTrade(
        trade_id="schedule-test",
        currency="USD",
        valuation_date=date(2025, 1, 1),
        effective_date=effective,
        maturity_date=maturity,
        pay_leg=pay_leg,
        receive_leg=receive_leg,
        principal_exchange="Never",
    )


def test_simple_annual_schedule_uses_contractual_interval_and_unadjusted_payment_dates():
    effective = date(2025, 1, 15)
    maturity = date(2028, 1, 15)
    trade = _trade(
        _fixed_leg(Frequency.ANNUAL, 1000),
        _floating_leg(Frequency.ANNUAL, 1000),
        effective,
        maturity,
    )

    schedule = generate_leg_schedule(
        trade,
        trade.pay_leg,
        ScheduleGeneration(
            direction=ScheduleDirection.BACKWARD,
            payment_dates=(
                date(2026, 1, 20),
                date(2027, 1, 20),
                date(2028, 1, 20),
            ),
        ),
    )

    assert [(p.accrual_start, p.accrual_end) for p in schedule.periods] == [
        (date(2025, 1, 15), date(2026, 1, 15)),
        (date(2026, 1, 15), date(2027, 1, 15)),
        (date(2027, 1, 15), date(2028, 1, 15)),
    ]
    assert [p.payment_date for p in schedule.periods] == [
        date(2026, 1, 20), date(2027, 1, 20), date(2028, 1, 20)
    ]


def test_tc1_uses_explicit_next_to_last_date_and_absolute_repayment_amount():
    repayment = PrincipalRepayment(
        payment_date=date(2027, 5, 28),
        amount=Money(Decimal("265000"), "USD"),
    )
    trade = _trade(
        _fixed_leg(Frequency.ANNUAL, 530000, (repayment,)),
        _floating_leg(Frequency.ANNUAL, 530000),
        date(2026, 5, 31),
        date(2027, 11, 30),
    )

    schedule = generate_leg_schedule(
        trade,
        trade.pay_leg,
        ScheduleGeneration(
            direction=ScheduleDirection.BACKWARD,
            next_to_last_date=date(2027, 5, 28),
        ),
        repayment_treatment=RepaymentTreatment.ABSOLUTE_AMOUNT_REDUCES_NOTIONAL,
    )

    assert [(p.accrual_start, p.accrual_end) for p in schedule.periods] == [
        (date(2026, 5, 31), date(2027, 5, 28)),
        (date(2027, 5, 28), date(2027, 11, 30)),
    ]
    assert [p.payment_date for p in schedule.periods] == [
        date(2027, 5, 28), date(2027, 11, 30)
    ]
    assert [p.notional.amount for p in schedule.periods] == [
        Decimal("530000"), Decimal("265000")
    ]
    assert schedule.principal_repayments == (repayment,)
    assert trade.principal_exchange == "Never"
    assert not hasattr(schedule, "principal_exchange_cashflows")


def test_pay_and_receive_schedules_are_independent_and_can_have_different_lengths():
    trade = _trade(
        _fixed_leg(Frequency.QUARTERLY, 1000),
        _floating_leg(Frequency.ANNUAL, 800),
        date(2025, 1, 15),
        date(2027, 1, 15),
    )

    pay = generate_leg_schedule(
        trade, trade.pay_leg, ScheduleGeneration(ScheduleDirection.BACKWARD)
    )
    receive = generate_leg_schedule(
        trade, trade.receive_leg, ScheduleGeneration(ScheduleDirection.BACKWARD)
    )

    assert len(pay.periods) == 8
    assert len(receive.periods) == 2
    assert pay.periods[0].notional.amount == Decimal("1000")
    assert receive.periods[0].notional.amount == Decimal("800")


def test_independent_repayment_rows_and_midperiod_repayment_affect_only_later_periods():
    pay_repayments = (
        PrincipalRepayment(date(2025, 7, 1), Money(Decimal("100"), "USD")),
        PrincipalRepayment(date(2025, 9, 1), Money(Decimal("50"), "USD")),
    )
    receive_repayments = (
        PrincipalRepayment(date(2025, 8, 1), Money(Decimal("25"), "USD")),
    )
    trade = _trade(
        _fixed_leg(Frequency.ANNUAL, 1000, pay_repayments),
        _floating_leg(Frequency.ANNUAL, 500, receive_repayments),
        date(2025, 1, 1),
        date(2027, 1, 1),
    )

    pay = generate_leg_schedule(
        trade,
        trade.pay_leg,
        ScheduleGeneration(ScheduleDirection.BACKWARD),
        repayment_treatment=RepaymentTreatment.ABSOLUTE_AMOUNT_REDUCES_NOTIONAL,
    )
    receive = generate_leg_schedule(
        trade,
        trade.receive_leg,
        ScheduleGeneration(ScheduleDirection.BACKWARD),
        repayment_treatment=RepaymentTreatment.ABSOLUTE_AMOUNT_REDUCES_NOTIONAL,
    )

    assert [p.notional.amount for p in pay.periods] == [Decimal("1000"), Decimal("850")]
    assert [p.notional.amount for p in receive.periods] == [Decimal("500"), Decimal("475")]
    assert len(pay.principal_repayments) == 2
    assert len(receive.principal_repayments) == 1
    assert pay.principal_repayments[0].payment_date == date(2025, 7, 1)


def test_repayment_schedule_requires_explicit_amount_treatment():
    repayment = PrincipalRepayment(date(2026, 1, 1), Money(Decimal("10"), "USD"))
    trade = _trade(
        _fixed_leg(Frequency.ANNUAL, 100, (repayment,)),
        _floating_leg(Frequency.ANNUAL, 100),
        date(2025, 1, 1),
        date(2027, 1, 1),
    )

    with pytest.raises(ValueError, match="repayment_treatment"):
        generate_leg_schedule(
            trade,
            trade.pay_leg,
            ScheduleGeneration(ScheduleDirection.BACKWARD),
        )


def test_non_regular_interval_requires_explicit_stub_boundary():
    trade = _trade(
        _fixed_leg(Frequency.ANNUAL, 100),
        _floating_leg(Frequency.ANNUAL, 100),
        date(2026, 5, 31),
        date(2027, 11, 30),
    )

    with pytest.raises(ValueError, match="explicit stub boundary"):
        generate_leg_schedule(
            trade,
            trade.pay_leg,
            ScheduleGeneration(ScheduleDirection.BACKWARD),
        )
