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
from instruments.rates.irs.floating_leg import (
    UnsupportedBenchmarkMapping,
    build_floating_index,
    build_floating_leg,
)
from instruments.rates.irs.quantlib_schedule import translate_leg_schedule
from instruments.rates.irs.schedule import (
    RepaymentTreatment,
    ScheduleDirection,
    ScheduleGeneration,
    generate_leg_schedule,
)


def _fixed_leg(frequency, notional):
    return IRSLegTerms(
        kind="fixed",
        payment_frequency=frequency,
        day_count=DayCountConvention.ACT_360,
        original_notional=Money(Decimal(str(notional)), "USD"),
        fixed_coupon_rate=Decimal("0.05"),
    )


def _floating_leg(
    frequency=Frequency.ANNUAL,
    *,
    benchmark="SOFRRATE",
    tenor="1D",
    reset_frequency=Frequency.DAILY,
    spread="0.001",
    leverage="1",
    lookback=1,
    cutoff=1,
    reset_timing="In Arrears",
    compounding="ExcludeSprd",
    lookback_type="Lookback",
    notional=530000,
    repayments=(),
):
    return IRSLegTerms(
        kind="floating",
        payment_frequency=frequency,
        day_count=DayCountConvention.ACT_360,
        original_notional=Money(Decimal(str(notional)), "USD"),
        benchmark=benchmark,
        benchmark_tenor=tenor,
        reset_frequency=reset_frequency,
        floating_spread_rate=Decimal(spread),
        floating_leverage=Decimal(leverage),
        observation=ObservationConventions(
            lookback_days=lookback,
            cutoff_days=cutoff,
            reset_timing=reset_timing,
            compounding=compounding,
            lookback_type=lookback_type,
        ),
        principal_repayments=tuple(repayments),
    )


def _trade(pay_leg, receive_leg, effective, maturity, currency="USD"):
    return IRSTrade(
        trade_id="floating-leg-test",
        currency=currency,
        valuation_date=date(2026, 3, 31),
        effective_date=effective,
        maturity_date=maturity,
        pay_leg=pay_leg,
        receive_leg=receive_leg,
        principal_exchange="Never",
    )


def _tc1_floating_leg():
    repayments = (
        PrincipalRepayment(date(2027, 5, 28), Money(Decimal("265000"), "USD")),
    )
    trade = _trade(
        _fixed_leg(Frequency.ANNUAL, 530000),
        _floating_leg(
            repayments=repayments,
            notional=530000,
            spread="0.001",
            leverage="1",
            lookback=1,
            cutoff=1,
        ),
        date(2026, 5, 31),
        date(2027, 11, 30),
    )
    contractual = generate_leg_schedule(
        trade,
        trade.receive_leg,
        ScheduleGeneration(
            ScheduleDirection.BACKWARD,
            next_to_last_date=date(2027, 5, 28),
        ),
        repayment_treatment=RepaymentTreatment.ABSOLUTE_AMOUNT_REDUCES_NOTIONAL,
    )
    return trade, trade.receive_leg, translate_leg_schedule(contractual)


def _coupons(floating_leg):
    return tuple(ql.as_overnight_indexed_coupon(cashflow) for cashflow in floating_leg.quantlib_leg)


def test_tc1_floating_leg_uses_supported_usd_sofr_index_and_contract_period_data():
    trade, terms, schedule = _tc1_floating_leg()

    floating = build_floating_leg(terms, schedule, trade.currency)

    assert isinstance(floating.index, ql.Sofr)
    assert floating.index.currency().code() == "USD"
    assert floating.index.tenor().length() == 1
    assert floating.index.tenor().units() == ql.Days
    assert len(floating.quantlib_leg) == 2
    coupons = _coupons(floating)
    assert [(c.accrualStartDate(), c.accrualEndDate()) for c in coupons] == [
        (ql.Date(31, 5, 2026), ql.Date(28, 5, 2027)),
        (ql.Date(28, 5, 2027), ql.Date(30, 11, 2027)),
    ]
    assert [c.date() for c in coupons] == [
        ql.Date(28, 5, 2027), ql.Date(30, 11, 2027)
    ]
    assert [c.nominal() for c in coupons] == [530000.0, 265000.0]
    assert [c.dayCounter().name() for c in coupons] == ["Actual/360", "Actual/360"]
    assert terms.payment_frequency is Frequency.ANNUAL
    assert terms.reset_frequency is Frequency.DAILY
    assert [c.spread() for c in coupons] == pytest.approx([0.001, 0.001])
    assert [c.gearing() for c in coupons] == pytest.approx([1.0, 1.0])


def test_floating_spread_and_leverage_are_per_leg_inputs_not_builder_defaults():
    _, terms, schedule = _tc1_floating_leg()
    varied_terms = _floating_leg(spread="0.00275", leverage="1.4", notional=530000)
    varied_schedule = schedule

    floating = build_floating_leg(varied_terms, varied_schedule, "USD")
    coupons = _coupons(floating)

    assert [c.spread() for c in coupons] == pytest.approx([0.00275, 0.00275])
    assert [c.gearing() for c in coupons] == pytest.approx([1.4, 1.4])
    assert terms.floating_spread_rate == Decimal("0.001")


def test_lookback_cutoff_and_reset_timing_are_kept_separate():
    trade, terms, schedule = _tc1_floating_leg()

    floating = build_floating_leg(terms, schedule, trade.currency)
    coupons = _coupons(floating)

    assert floating.observation_settings.lookback_days == 1
    assert floating.observation_settings.cutoff_days == 1
    assert floating.observation_settings.quantlib_lockout_days == 0
    assert floating.observation_settings.in_arrears is True
    assert floating.observation_settings.compound_spread_daily is False
    assert all(
        c.rateComputationStartDate() == c.accrualStartDate()
        and c.rateComputationEndDate() == c.accrualEndDate()
        for c in coupons
    )
    assert all(c.lockoutDays() == 0 for c in coupons)
    assert all(c.compoundSpreadDaily() is False for c in coupons)
    assert all(c.averagingMethod() == ql.RateAveraging.Compound for c in coupons)
    first_observation = floating.observation_schedule.periods[0]
    # Accrual starts Sun 31-May-2026 (SOFR fixing holiday). Its rate applies from the
    # preceding business day, Fri 29-May; a 1-business-day lookback then observes
    # Thu 28-May. QuantLib >= 1.43 (PR #2556, commit 5348d7a) accrues the holiday start
    # day; QuantLib <= 1.42.1 started compounding on Mon 01-Jun, dropping that day, so
    # its first fixing was 29-May.
    assert first_observation.fixing_dates[0] == date(2026, 5, 28)
    assert len(first_observation.fixing_dates) > 1


def test_reset_frequency_is_independent_of_payment_frequency_and_other_leg():
    trade = _trade(
        _fixed_leg(Frequency.ANNUAL, 100000),
        _floating_leg(frequency=Frequency.SEMIANNUAL, notional=90000),
        date(2025, 1, 15),
        date(2027, 1, 15),
    )
    contractual = generate_leg_schedule(
        trade, trade.receive_leg, ScheduleGeneration(ScheduleDirection.BACKWARD)
    )

    floating = build_floating_leg(
        trade.receive_leg, translate_leg_schedule(contractual), trade.currency
    )

    assert trade.receive_leg.reset_frequency is Frequency.DAILY
    assert trade.receive_leg.payment_frequency is Frequency.SEMIANNUAL
    assert trade.pay_leg.payment_frequency is Frequency.ANNUAL
    assert len(floating.quantlib_leg) == 4


def test_in_advance_is_mapped_explicitly_when_requested():
    trade = _trade(
        _fixed_leg(Frequency.ANNUAL, 1000),
        _floating_leg(
            frequency=Frequency.ANNUAL,
            notional=1000,
            reset_timing="In Advance",
        ),
        date(2025, 1, 15),
        date(2026, 1, 15),
    )
    contractual = generate_leg_schedule(
        trade, trade.receive_leg, ScheduleGeneration(ScheduleDirection.BACKWARD)
    )

    floating = build_floating_leg(
        trade.receive_leg, translate_leg_schedule(contractual), trade.currency
    )

    assert floating.observation_settings.in_arrears is False
    assert floating.coupons[0].rateComputationStartDate() != floating.coupons[0].accrualStartDate()


@pytest.mark.parametrize("benchmark,tenor", [
    ("SF0006M", "6M"),
    ("IRSWOF", "6M"),
    ("MUTKCALM", "1D"),
    ("TONAR", "1D"),
])
def test_unresolved_benchmark_mappings_fail_explicitly(benchmark, tenor):
    terms = _floating_leg(benchmark=benchmark, tenor=tenor)

    with pytest.raises(UnsupportedBenchmarkMapping, match=benchmark):
        build_floating_index(terms, "USD")


def test_sofr_mapping_rejects_wrong_currency_tenor_or_reset_frequency():
    for terms, currency in (
        (_floating_leg(tenor="6M"), "USD"),
        (_floating_leg(reset_frequency=Frequency.SEMIANNUAL), "USD"),
        (_floating_leg(), "EUR"),
    ):
        with pytest.raises(UnsupportedBenchmarkMapping):
            build_floating_index(terms, currency)
