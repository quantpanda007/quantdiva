import json
import math
from datetime import date
from decimal import Decimal
from pathlib import Path

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
from instruments.rates.irs.schedule import (
    RepaymentTreatment,
    ScheduleDirection,
    ScheduleGeneration,
    generate_leg_schedule,
)
from instruments.rates.irs.quantlib_schedule import translate_leg_schedule
from instruments.rates.irs.engine import attach_discounting_engine
from market.curves.irs_market_data import (
    DiscountCurveMarketData,
    DiscountFactorObservation,
    IRSMarketData,
    SimpleForwardCurveMarketData,
    SimpleForwardObservation,
    build_discount_curve,
)
from market.curves.irs_provisional_projection import build_provisional_projection_curve

# Validation-phase test (reads Bloomberg fixtures): excluded from the default run;
# run with `pytest -m validation`.
pytestmark = pytest.mark.validation


FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "bloomberg_irs_case.json"
)


@pytest.fixture(autouse=True)
def restore_quantlib_evaluation_date():
    settings = ql.Settings.instance()
    previous_date = settings.evaluationDate
    yield
    settings.evaluationDate = previous_date


def _build_canonical_components():
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    trade_data = fixture["trade"]
    market_data = fixture["market_environment"]
    reference_date = date.fromisoformat(market_data["reference_date"])
    ql.Settings.instance().evaluationDate = ql.Date(
        reference_date.day, reference_date.month, reference_date.year
    )

    data_points = market_data["market_data_points"]
    market = IRSMarketData(
        discount_curve=DiscountCurveMarketData(
            reference_date=reference_date,
            currency=market_data["currency"],
            observations=tuple(
                DiscountFactorObservation(
                    date.fromisoformat(point["date"]),
                    Decimal(str(point["discount_factor"])),
                )
                for point in data_points
            ),
        ),
        projection_curve=SimpleForwardCurveMarketData(
            reference_date=reference_date,
            currency=market_data["currency"],
            benchmark=trade_data["floating_leg"]["index"],
            observations=tuple(
                SimpleForwardObservation(
                    date.fromisoformat(point["date"]),
                    Decimal(str(point["market_rate"])),
                )
                for point in data_points
            ),
        ),
    )

    principal_repayment = PrincipalRepayment(
        payment_date=date(2027, 5, 28),
        amount=Money(Decimal("265000"), "USD"),
    )
    fixed_terms = IRSLegTerms(
        kind="fixed",
        payment_frequency=Frequency.ANNUAL,
        day_count=DayCountConvention.ACT_360,
        original_notional=Money(Decimal("530000"), "USD"),
        principal_repayments=(principal_repayment,),
        fixed_coupon_rate=Decimal("0.05"),
    )
    floating_terms = IRSLegTerms(
        kind="floating",
        payment_frequency=Frequency.ANNUAL,
        day_count=DayCountConvention.ACT_360,
        original_notional=Money(Decimal("530000"), "USD"),
        principal_repayments=(principal_repayment,),
        benchmark="SOFRRATE",
        benchmark_tenor="1D",
        floating_spread_rate=Decimal("0.001"),
        floating_leverage=Decimal("1"),
        reset_frequency=Frequency.DAILY,
        observation=ObservationConventions(
            lookback_days=1,
            cutoff_days=1,
            reset_timing="In Arrears",
            compounding="ExcludeSprd",
            lookback_type="Lookback",
        ),
    )
    trade = IRSTrade(
        trade_id=trade_data["trade_id"],
        currency=trade_data["currency"],
        valuation_date=reference_date,
        effective_date=date.fromisoformat(trade_data["effective_date"]),
        maturity_date=date.fromisoformat(trade_data["maturity_date"]),
        pay_leg=fixed_terms,
        receive_leg=floating_terms,
        principal_exchange=trade_data["principal_exchange"],
    )
    generation = ScheduleGeneration(
        direction=ScheduleDirection.BACKWARD,
        next_to_last_date=date(2027, 5, 28),
    )
    pay_contract = generate_leg_schedule(
        trade,
        trade.pay_leg,
        generation,
        repayment_treatment=RepaymentTreatment.ABSOLUTE_AMOUNT_REDUCES_NOTIONAL,
    )
    receive_contract = generate_leg_schedule(
        trade,
        trade.receive_leg,
        generation,
        repayment_treatment=RepaymentTreatment.ABSOLUTE_AMOUNT_REDUCES_NOTIONAL,
    )

    discount_curve = build_discount_curve(
        market.discount_curve,
        day_counter=ql.Actual360(),
        expected_currency=trade.currency,
    )
    projection_curve = build_provisional_projection_curve(
        market.projection_curve,
        day_counter=ql.Actual360(),
        expected_currency=trade.currency,
        expected_benchmark="SOFR",
    )
    fixed_leg = build_fixed_leg(
        trade.pay_leg, translate_leg_schedule(pay_contract)
    )
    floating_leg = build_floating_leg(
        trade.receive_leg,
        translate_leg_schedule(receive_contract),
        trade.currency,
        forwarding_curve=projection_curve.handle,
    )
    instrument = assemble_quantlib_irs(fixed_leg, floating_leg)
    engine = attach_discounting_engine(instrument, discount_curve)
    return fixture, trade, discount_curve, projection_curve, floating_leg, instrument, engine


def test_tc1_builds_and_prices_with_distinct_discount_and_projection_curves():
    (
        fixture,
        trade,
        discount_curve,
        projection_curve,
        floating_leg,
        assembled,
        attached_engine,
    ) = _build_canonical_components()

    swap = assembled.quantlib_instrument
    assert isinstance(swap, ql.Swap)
    assert isinstance(attached_engine.quantlib_engine, ql.DiscountingSwapEngine)
    assert attached_engine.instrument is assembled
    assert attached_engine.discount_curve is discount_curve.handle
    assert floating_leg.index.forwardingTermStructure().discount(
        ql.Date(30, 3, 2027)
    ) == pytest.approx(projection_curve.handle.discount(ql.Date(30, 3, 2027)))
    assert floating_leg.index.forwardingTermStructure().discount(
        ql.Date(30, 3, 2027)
    ) != pytest.approx(discount_curve.handle.discount(ql.Date(30, 3, 2027)))
    assert discount_curve.handle is not projection_curve.handle
    assert discount_curve.term_structure is not projection_curve.term_structure
    assert isinstance(floating_leg.index, ql.Sofr)
    assert floating_leg.index.currency().code() == trade.currency == "USD"
    assert floating_leg.index.forwardingTermStructure().referenceDate() == ql.Date(
        31, 3, 2026
    )
    assert [coupon.nominal() for coupon in assembled.pay_leg.coupons] == [
        530000.0,
        265000.0,
    ]
    assert [coupon.nominal() for coupon in assembled.receive_leg.coupons] == [
        530000.0,
        265000.0,
    ]

    fixed_pv = swap.legNPV(0)
    floating_pv = swap.legNPV(1)
    total_npv = swap.NPV()
    assert isinstance(total_npv, (int, float))
    assert math.isfinite(total_npv)
    assert fixed_pv < 0.0
    assert floating_pv > 0.0
    assert total_npv == pytest.approx(fixed_pv + floating_pv, abs=1e-8)

    # External Bloomberg values are printed only as diagnostic references.
    references = {"fixed": -31978.74, "floating": 24023.74, "total": -7955.00}
    print(f"Optima provisional fixed-leg PV: {fixed_pv:.12f}")
    print(f"Optima provisional floating-leg PV: {floating_pv:.12f}")
    print(f"Optima provisional total NPV: {total_npv:.12f}")
    print(
        "External Bloomberg diagnostics (not assertions): "
        f"fixed={references['fixed']:.2f} (difference={fixed_pv-references['fixed']:.12f}), "
        f"floating={references['floating']:.2f} "
        f"(difference={floating_pv-references['floating']:.12f}), "
        f"total={references['total']:.2f} (difference={total_npv-references['total']:.12f})"
    )


def test_provisional_curve_inputs_and_output_are_separate_from_discount_curve():
    _, _, discount_curve, projection_curve, _, _, _ = _build_canonical_components()

    assert projection_curve.methodology_is_provisional is True
    assert projection_curve.market_data is not discount_curve.market_data
    assert projection_curve.handle is not discount_curve.handle
    assert projection_curve.term_structure is not discount_curve.term_structure

