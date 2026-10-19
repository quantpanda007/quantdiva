from datetime import date
from decimal import Decimal

import QuantLib as ql
import pytest

from core.enums.definitions import DayCountConvention, Frequency
from core.types.value_objects import Money
from instruments.rates.irs.domain import (
    IRSLegTerms,
    IRSTrade,
    ObservationConventions,
    PrincipalRepayment,
)
from instruments.rates.irs.fixed_leg import build_fixed_leg
from instruments.rates.irs.floating_leg import build_floating_leg
from instruments.rates.irs.instrument import assemble_quantlib_irs
from instruments.rates.irs.quantlib_schedule import translate_leg_schedule
from instruments.rates.irs.schedule import (
    RepaymentTreatment,
    ScheduleDirection,
    ScheduleGeneration,
    generate_leg_schedule,
)


def _tc1_components():
    repayment = PrincipalRepayment(
        date(2027, 5, 28), Money(Decimal("265000"), "USD")
    )
    fixed_terms = IRSLegTerms(
        kind="fixed",
        payment_frequency=Frequency.ANNUAL,
        day_count=DayCountConvention.ACT_360,
        original_notional=Money(Decimal("530000"), "USD"),
        fixed_coupon_rate=Decimal("0.05"),
        principal_repayments=(repayment,),
    )
    floating_terms = IRSLegTerms(
        kind="floating",
        payment_frequency=Frequency.ANNUAL,
        day_count=DayCountConvention.ACT_360,
        original_notional=Money(Decimal("530000"), "USD"),
        benchmark="SOFRRATE",
        benchmark_tenor="1D",
        floating_spread_rate=Decimal("0.001"),
        floating_leverage=Decimal("1"),
        reset_frequency=Frequency.DAILY,
        principal_repayments=(repayment,),
        observation=ObservationConventions(
            lookback_days=1,
            cutoff_days=1,
            reset_timing="In Arrears",
            compounding="ExcludeSprd",
            lookback_type="Lookback",
        ),
    )
    trade = IRSTrade(
        trade_id="SLLSL9RR",
        currency="USD",
        valuation_date=date(2026, 3, 31),
        effective_date=date(2026, 5, 31),
        maturity_date=date(2027, 11, 30),
        pay_leg=fixed_terms,
        receive_leg=floating_terms,
        principal_exchange="Never",
    )
    generation = ScheduleGeneration(
        ScheduleDirection.BACKWARD,
        next_to_last_date=date(2027, 5, 28),
    )
    pay_schedule = generate_leg_schedule(
        trade,
        trade.pay_leg,
        generation,
        repayment_treatment=RepaymentTreatment.ABSOLUTE_AMOUNT_REDUCES_NOTIONAL,
    )
    receive_schedule = generate_leg_schedule(
        trade,
        trade.receive_leg,
        generation,
        repayment_treatment=RepaymentTreatment.ABSOLUTE_AMOUNT_REDUCES_NOTIONAL,
    )
    fixed_leg = build_fixed_leg(trade.pay_leg, translate_leg_schedule(pay_schedule))
    floating_leg = build_floating_leg(
        trade.receive_leg,
        translate_leg_schedule(receive_schedule),
        trade.currency,
    )
    return trade, fixed_leg, floating_leg


def test_tc1_assembles_native_swap_from_existing_fixed_and_sofr_overnight_legs():
    trade, fixed_leg, floating_leg = _tc1_components()

    assembled = assemble_quantlib_irs(fixed_leg, floating_leg)

    instrument = assembled.quantlib_instrument
    assert isinstance(instrument, ql.Swap)
    assert assembled.pay_leg is fixed_leg
    assert assembled.receive_leg is floating_leg
    assert instrument.payer(0) is True
    assert instrument.payer(1) is False
    assert instrument.numberOfLegs() == 2

    fixed_coupons = assembled.pay_leg.coupons
    floating_coupons = assembled.receive_leg.coupons
    expected_periods = [
        (ql.Date(31, 5, 2026), ql.Date(28, 5, 2027), ql.Date(28, 5, 2027), 530000),
        (ql.Date(28, 5, 2027), ql.Date(30, 11, 2027), ql.Date(30, 11, 2027), 265000),
    ]

    assert len(fixed_coupons) == len(floating_coupons) == 2
    assert len(instrument.leg(0)) == len(instrument.leg(1)) == 2
    assert [cashflow.date() for cashflow in instrument.leg(0)] == [
        ql.Date(28, 5, 2027), ql.Date(30, 11, 2027)
    ]
    assert [cashflow.date() for cashflow in instrument.leg(1)] == [
        ql.Date(28, 5, 2027), ql.Date(30, 11, 2027)
    ]
    assert [
        (c.accrualStartDate(), c.accrualEndDate(), c.date(), c.nominal())
        for c in fixed_coupons
    ] == expected_periods
    assert [c.rate() for c in fixed_coupons] == pytest.approx([0.05, 0.05])
    assert [
        (c.accrualStartDate(), c.accrualEndDate(), c.date(), c.nominal())
        for c in floating_coupons
    ] == expected_periods
    assert isinstance(floating_leg.index, ql.Sofr)
    assert assembled.receive_leg.index is floating_leg.index
    assert [c.spread() for c in floating_coupons] == pytest.approx([0.001, 0.001])
    assert [c.gearing() for c in floating_coupons] == pytest.approx([1.0, 1.0])
    assert trade.currency == "USD"


def test_instrument_assembly_needs_no_projection_conversion_or_valuation_result():
    _, fixed_leg, floating_leg = _tc1_components()

    assembled = assemble_quantlib_irs(fixed_leg, floating_leg)

    with pytest.raises(RuntimeError, match="empty Handle"):
        floating_leg.index.forwardingTermStructure().currentLink()
    assert isinstance(assembled.quantlib_instrument, ql.Swap)

