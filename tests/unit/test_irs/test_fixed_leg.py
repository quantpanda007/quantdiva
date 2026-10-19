from datetime import date
from decimal import Decimal

import QuantLib as ql
import pytest

from core.enums.definitions import DayCountConvention, Frequency
from core.types.value_objects import Money
from instruments.rates.irs.domain import IRSLegTerms, IRSTrade, PrincipalRepayment
from instruments.rates.irs.fixed_leg import build_fixed_leg
from instruments.rates.irs.quantlib_schedule import translate_leg_schedule
from instruments.rates.irs.schedule import (
    RepaymentTreatment,
    ScheduleDirection,
    ScheduleGeneration,
    generate_leg_schedule,
)


def _fixed_leg(frequency, notional, rate="0.05", repayments=()):
    return IRSLegTerms(
        kind="fixed",
        payment_frequency=frequency,
        day_count=DayCountConvention.ACT_360,
        original_notional=Money(Decimal(str(notional)), "USD"),
        fixed_coupon_rate=Decimal(rate),
        principal_repayments=tuple(repayments),
    )


def _floating_leg(frequency, notional):
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
    )


def _trade(pay_leg, receive_leg, effective, maturity):
    return IRSTrade(
        trade_id="fixed-leg-test",
        currency="USD",
        valuation_date=date(2026, 3, 31),
        effective_date=effective,
        maturity_date=maturity,
        pay_leg=pay_leg,
        receive_leg=receive_leg,
        principal_exchange="Never",
    )


def _tc1_fixed_leg():
    repayments = (
        PrincipalRepayment(date(2027, 5, 28), Money(Decimal("265000"), "USD")),
    )
    trade = _trade(
        _fixed_leg(Frequency.ANNUAL, 530000, repayments=repayments),
        _floating_leg(Frequency.ANNUAL, 530000),
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
        repayment_treatment=RepaymentTreatment.ABSOLUTE_AMOUNT_REDUCES_NOTIONAL,
    )
    return trade.pay_leg, translate_leg_schedule(contractual)


def test_tc1_fixed_leg_builds_two_quantlib_fixed_coupon_cashflows():
    terms, schedule = _tc1_fixed_leg()

    leg = build_fixed_leg(terms, schedule)

    assert len(leg) == 2
    assert isinstance(leg.quantlib_leg, ql.Leg)
    assert len(leg.quantlib_leg) == 2
    assert all(isinstance(cashflow, ql.FixedRateCoupon) for cashflow in leg)
    first, second = leg
    assert (first.accrualStartDate(), first.accrualEndDate()) == (
        ql.Date(31, 5, 2026), ql.Date(28, 5, 2027)
    )
    assert (second.accrualStartDate(), second.accrualEndDate()) == (
        ql.Date(28, 5, 2027), ql.Date(30, 11, 2027)
    )


def test_fixed_leg_coupon_amounts_dates_notionals_rate_and_day_count_are_preserved():
    terms, schedule = _tc1_fixed_leg()

    leg = build_fixed_leg(terms, schedule)

    assert [cashflow.date() for cashflow in leg] == [
        ql.Date(28, 5, 2027),
        ql.Date(30, 11, 2027),
    ]
    assert [cashflow.nominal() for cashflow in leg] == [530000.0, 265000.0]
    assert [cashflow.rate() for cashflow in leg] == pytest.approx([0.05, 0.05])
    assert [cashflow.dayCounter().name() for cashflow in leg] == [
        "Actual/360",
        "Actual/360",
    ]
    assert [cashflow.amount() for cashflow in leg] == pytest.approx(
        [26647.2222222222, 6845.8333333333], abs=1e-8
    )
    assert [cashflow.date() for cashflow in leg.quantlib_leg] == [
        ql.Date(28, 5, 2027), ql.Date(30, 11, 2027)
    ]
    assert [cashflow.amount() for cashflow in leg.quantlib_leg] == pytest.approx(
        [26647.2222222222, 6845.8333333333], abs=1e-8
    )


def test_fixed_leg_builder_uses_only_its_own_contractual_schedule():
    trade = _trade(
        _fixed_leg(Frequency.QUARTERLY, 100000),
        _floating_leg(Frequency.ANNUAL, 90000),
        date(2025, 1, 15),
        date(2027, 1, 15),
    )
    contractual = generate_leg_schedule(
        trade, trade.pay_leg, ScheduleGeneration(ScheduleDirection.BACKWARD)
    )
    translated = translate_leg_schedule(contractual)

    leg = build_fixed_leg(trade.pay_leg, translated)

    assert len(leg) == 8
    assert len(translated.periods) == 8
    assert trade.receive_leg.payment_frequency is Frequency.ANNUAL


def test_fixed_leg_builder_rejects_floating_leg_terms():
    terms = _floating_leg(Frequency.ANNUAL, 100000)
    _, schedule = _tc1_fixed_leg()

    with pytest.raises(ValueError, match="fixed"):
        build_fixed_leg(terms, schedule)
