from datetime import date
from decimal import Decimal

import pytest

from core.enums.definitions import DayCountConvention, Frequency
from core.types.value_objects import Money
from instruments.rates.irs.domain import (
    IRSLegTerms,
    IRSTrade,
    ObservationConventions,
    PrincipalRepayment,
)


def _repayment(day: int, amount: int) -> PrincipalRepayment:
    return PrincipalRepayment(
        payment_date=date(2027, 1, day),
        amount=Money(Decimal(amount), "USD"),
    )


def test_irs_domain_keeps_pay_and_receive_terms_and_repayments_independent():
    pay_leg = IRSLegTerms(
        kind="fixed",
        payment_frequency=Frequency.QUARTERLY,
        day_count=DayCountConvention.ACT_360,
        original_notional=Money(Decimal("1000"), "USD"),
        fixed_coupon_rate=Decimal("0.0475"),
        principal_repayments=(_repayment(10, 100), _repayment(20, 200)),
    )
    receive_leg = IRSLegTerms(
        kind="floating",
        payment_frequency=Frequency.ANNUAL,
        day_count=DayCountConvention.ACT_365,
        original_notional=Money(Decimal("1000"), "USD"),
        benchmark="SOFRRATE",
        benchmark_tenor="1D",
        floating_spread_rate=Decimal("0.00125"),
        floating_leverage=Decimal("1"),
        reset_frequency=Frequency.DAILY,
        observation=ObservationConventions(
            lookback_days=1,
            cutoff_days=2,
            reset_timing="In Arrears",
            compounding="ExcludeSprd",
        ),
        principal_repayments=(_repayment(15, 50),),
    )
    trade = IRSTrade(
        trade_id="T-IRS-1",
        currency="USD",
        valuation_date=date(2026, 3, 31),
        effective_date=date(2026, 5, 31),
        maturity_date=date(2028, 5, 31),
        pay_leg=pay_leg,
        receive_leg=receive_leg,
        principal_exchange="Never",
    )

    assert trade.pay_leg is pay_leg
    assert trade.receive_leg is receive_leg
    assert trade.pay_leg.payment_frequency is Frequency.QUARTERLY
    assert trade.receive_leg.payment_frequency is Frequency.ANNUAL
    assert trade.pay_leg.day_count is DayCountConvention.ACT_360
    assert trade.receive_leg.day_count is DayCountConvention.ACT_365
    assert trade.receive_leg.reset_frequency is Frequency.DAILY
    assert trade.pay_leg.fixed_coupon_rate == Decimal("0.0475")
    assert trade.receive_leg.floating_spread_rate == Decimal("0.00125")
    assert len(trade.pay_leg.principal_repayments) == 2
    assert len(trade.receive_leg.principal_repayments) == 1
    assert trade.receive_leg.principal_repayments[0].amount.amount == Decimal("50")
    assert trade.principal_exchange == "Never"


def test_fixed_leg_rejects_floating_terms_and_floating_leg_requires_reset_terms():
    with pytest.raises(ValueError, match="fixed_coupon_rate"):
        IRSLegTerms(
            kind="fixed",
            payment_frequency=Frequency.ANNUAL,
            day_count=DayCountConvention.ACT_360,
            original_notional=Money(Decimal("1000"), "USD"),
        )

    with pytest.raises(ValueError, match="reset_frequency"):
        IRSLegTerms(
            kind="floating",
            payment_frequency=Frequency.ANNUAL,
            day_count=DayCountConvention.ACT_360,
            original_notional=Money(Decimal("1000"), "USD"),
            benchmark="SF0006M",
            benchmark_tenor="6M",
            floating_spread_rate=Decimal("0"),
            floating_leverage=Decimal("1"),
        )
