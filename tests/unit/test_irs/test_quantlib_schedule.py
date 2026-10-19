from datetime import date
from decimal import Decimal

import QuantLib as ql

from core.enums.definitions import DayCountConvention, Frequency
from core.types.value_objects import Money
from instruments.rates.irs.domain import IRSLegTerms, IRSTrade
from instruments.rates.irs.quantlib_schedule import (
    translate_irs_schedules,
    translate_leg_schedule,
)
from instruments.rates.irs.schedule import (
    ScheduleDirection,
    ScheduleGeneration,
    generate_leg_schedule,
)


def _leg(kind, frequency, notional):
    values = dict(
        kind=kind,
        payment_frequency=frequency,
        day_count=DayCountConvention.ACT_360,
        original_notional=Money(Decimal(str(notional)), "USD"),
    )
    if kind == "fixed":
        values["fixed_coupon_rate"] = Decimal("0.05")
    else:
        values.update(
            benchmark="SOFRRATE",
            benchmark_tenor="1D",
            floating_spread_rate=Decimal("0.001"),
            floating_leverage=Decimal("1"),
            reset_frequency=Frequency.DAILY,
        )
    return IRSLegTerms(**values)


def _trade(pay_leg, receive_leg, effective, maturity):
    return IRSTrade(
        trade_id="quantlib-schedule-test",
        currency="USD",
        valuation_date=date(2025, 1, 1),
        effective_date=effective,
        maturity_date=maturity,
        pay_leg=pay_leg,
        receive_leg=receive_leg,
        principal_exchange="Never",
    )


def _py_dates(ql_schedule):
    return tuple(date(d.year(), d.month(), d.dayOfMonth()) for d in ql_schedule)


def test_regular_annual_contractual_schedule_translates_to_quantlib_dates():
    trade = _trade(
        _leg("fixed", Frequency.ANNUAL, 1000),
        _leg("floating", Frequency.ANNUAL, 1000),
        date(2025, 1, 15),
        date(2028, 1, 15),
    )
    contractual = generate_leg_schedule(
        trade, trade.pay_leg, ScheduleGeneration(ScheduleDirection.BACKWARD)
    )

    translated = translate_leg_schedule(contractual)

    assert isinstance(translated.quantlib_schedule, ql.Schedule)
    assert _py_dates(translated.quantlib_schedule) == (
        date(2025, 1, 15),
        date(2026, 1, 15),
        date(2027, 1, 15),
        date(2028, 1, 15),
    )


def test_tc1_irregular_contractual_dates_are_preserved_without_rule_generation():
    trade = _trade(
        _leg("fixed", Frequency.ANNUAL, 530000),
        _leg("floating", Frequency.ANNUAL, 530000),
        date(2026, 5, 31),
        date(2027, 11, 30),
    )
    contractual = generate_leg_schedule(
        trade,
        trade.pay_leg,
        ScheduleGeneration(
            ScheduleDirection.BACKWARD,
            next_to_last_date=date(2027, 5, 28),
        ),
    )

    translated = translate_leg_schedule(contractual)

    assert _py_dates(translated.quantlib_schedule) == (
        date(2026, 5, 31),
        date(2027, 5, 28),
        date(2027, 11, 30),
    )
    assert translated.contractual_schedule is contractual


def test_period_notionals_payment_dates_and_accrual_dates_remain_attached():
    trade = _trade(
        _leg("fixed", Frequency.ANNUAL, 530000),
        _leg("floating", Frequency.ANNUAL, 530000),
        date(2026, 5, 31),
        date(2027, 11, 30),
    )
    contractual = generate_leg_schedule(
        trade,
        trade.pay_leg,
        ScheduleGeneration(
            ScheduleDirection.BACKWARD,
            next_to_last_date=date(2027, 5, 28),
            payment_dates=(date(2027, 5, 29), date(2027, 12, 1)),
        ),
    )

    translated = translate_leg_schedule(contractual)

    assert [
        (p.accrual_start, p.accrual_end, p.payment_date, p.notional.amount)
        for p in translated.periods
    ] == [
        (date(2026, 5, 31), date(2027, 5, 28), date(2027, 5, 29), Decimal("530000")),
        (date(2027, 5, 28), date(2027, 11, 30), date(2027, 12, 1), Decimal("530000")),
    ]


def test_pay_and_receive_quantlib_schedules_remain_independent():
    trade = _trade(
        _leg("fixed", Frequency.QUARTERLY, 1000),
        _leg("floating", Frequency.ANNUAL, 800),
        date(2025, 1, 15),
        date(2027, 1, 15),
    )
    pay = generate_leg_schedule(
        trade, trade.pay_leg, ScheduleGeneration(ScheduleDirection.BACKWARD)
    )
    receive = generate_leg_schedule(
        trade, trade.receive_leg, ScheduleGeneration(ScheduleDirection.BACKWARD)
    )

    translated = translate_irs_schedules(pay, receive)

    assert len(translated.pay.periods) == 8
    assert len(translated.receive.periods) == 2
    assert len(translated.pay.quantlib_schedule) == 9
    assert len(translated.receive.quantlib_schedule) == 3
    assert translated.pay.periods[0].notional.amount == Decimal("1000")
    assert translated.receive.periods[0].notional.amount == Decimal("800")


def test_translation_does_not_create_principal_exchange_cashflows():
    trade = _trade(
        _leg("fixed", Frequency.ANNUAL, 100),
        _leg("floating", Frequency.ANNUAL, 100),
        date(2025, 1, 15),
        date(2027, 1, 15),
    )
    contractual = generate_leg_schedule(
        trade, trade.pay_leg, ScheduleGeneration(ScheduleDirection.BACKWARD)
    )

    translated = translate_leg_schedule(contractual)

    assert not hasattr(translated, "principal_exchange_cashflows")
    assert not hasattr(translated, "cashflows")


def test_irregular_schedule_uses_explicit_dates_not_quantlib_stub_inference():
    trade = _trade(
        _leg("fixed", Frequency.ANNUAL, 530000),
        _leg("floating", Frequency.ANNUAL, 530000),
        date(2026, 5, 31),
        date(2027, 11, 30),
    )
    contractual = generate_leg_schedule(
        trade,
        trade.pay_leg,
        ScheduleGeneration(
            ScheduleDirection.BACKWARD,
            next_to_last_date=date(2027, 5, 28),
        ),
    )

    translated = translate_leg_schedule(contractual)

    assert _py_dates(translated.quantlib_schedule) == tuple(
        [contractual.periods[0].accrual_start]
        + [period.accrual_end for period in contractual.periods]
    )
