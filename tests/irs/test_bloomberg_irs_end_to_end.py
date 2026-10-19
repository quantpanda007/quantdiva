"""End-to-end pricing smoke test for the canonical Bloomberg IRS inputs."""

from __future__ import annotations

import json
import math
from datetime import date
from numbers import Real
from pathlib import Path

import QuantLib as ql
import pytest
import registry.bootstrap  # noqa: F401 - register instruments, models, engines

from api.v1.helpers import build_instrument_from_request
from api.v1.schemas import (
    InstrumentRequest,
    MarketDataRequest,
    PricingRequest,
    UnderlyingData,
)
from core.interfaces.base import MarketEnvironment
from core.types.value_objects import PricingDate
from market.curves.yield_curve import CurveDefinition, YieldCurveBuilder
from services.pricers.pricing_service import PricingService


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "bloomberg_irs_case.json"
)


def test_canonical_bloomberg_irs_prices_end_to_end_with_finite_usd_npv(monkeypatch):
    case = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    trade = case["trade"]
    fixed = trade["fixed_leg"]
    floating = trade["floating_leg"]
    conventions = case["conventions"]
    market = case["market_environment"]
    reference_date = date.fromisoformat(market["reference_date"])

    builder = YieldCurveBuilder()
    discount_curve = builder.build(
        CurveDefinition(
            currency="USD",
            pricing_date=PricingDate(reference_date),
            discount_factors=[
                (date.fromisoformat(point["date"]), point["discount_factor"])
                for point in market["market_data_points"]
            ],
        )
    )
    # PROVISIONAL assumptions are documented and isolated in the production
    # simple-forward conversion path and its projection-curve TDD contract.
    projection_curve = builder.build(
        CurveDefinition(
            currency="USD",
            pricing_date=PricingDate(reference_date),
            forward_rates=[
                (date.fromisoformat(point["date"]), point["market_rate"])
                for point in market["market_data_points"]
            ],
        )
    )

    params = {
        "trade_id": trade["trade_id"],
        "notional": trade["notional"]["amount"],
        "currency": trade["currency"],
        "start_date": trade["effective_date"],
        "end_date": trade["maturity_date"],
        "fixed_rate": fixed["rate"],
        "fixed_leg_frequency": fixed["payment_frequency"].lower(),
        "float_leg_frequency": floating["payment_frequency"].lower(),
        "fixed_day_count": fixed["day_count"],
        "float_day_count": floating["day_count"],
        "direction": "pay" if fixed["direction"] == "payer" else "receive",
        "float_index": floating["index"],
        "float_index_tenor": floating["index_tenor"],
        "float_spread": floating["spread_decimal"],
        "leverage": floating["leverage"],
        "lookback_days": conventions["lookback_days"],
        "rate_cutoff_days": conventions["rate_cutoff_days"],
        "days_before_type": conventions["days_before_type"],
        "reset_type": conventions["reset_type"],
        "compounding": conventions["compounding"],
        "business_day_convention": conventions["business_day_convention"][
            "normalized_name"
        ],
        "schedule_generation": conventions["schedule_generation"],
        "principal_exchange": trade["principal_exchange"],
        "amortization": trade["amortization"],
    }
    request = PricingRequest(
        instrument=InstrumentRequest(type="irs", params=params),
        # Dated dual curves are not expressible in MarketDataRequest yet; use
        # the canonical request for its instrument/model/engine selectors and
        # attach the fixture-built curves to the existing MarketEnvironment.
        market_data=MarketDataRequest(
            pricing_date=market["valuation_date"],
            underlyings={"USD": UnderlyingData(spot=1.0)},
        ),
        model="black_scholes",
        engine="analytic",
    )
    instrument = build_instrument_from_request(request.instrument)
    market_env = MarketEnvironment(
        pricing_date=PricingDate(reference_date),
        discount_curves={"USD": discount_curve},
        forecast_curves={"USD": projection_curve},
    )

    built_swaps = []
    original_build = instrument.build

    def capture_swap_build(environment):
        swap = original_build(environment)
        built_swaps.append(swap)
        return swap

    instrument.build = capture_swap_build

    original_engine_class = ql.DiscountingSwapEngine
    discount_handles = []
    built_engines = []

    def capture_discounting_engine(curve, *args, **kwargs):
        discount_handles.append(curve)
        engine = original_engine_class(curve, *args, **kwargs)
        built_engines.append(engine)
        return engine

    monkeypatch.setattr(ql, "DiscountingSwapEngine", capture_discounting_engine)
    result = PricingService().price(
        instrument=instrument,
        market_env=market_env,
        model_type=request.model,
        engine_type=request.engine,
    )

    assert len(built_swaps) == 1
    swap = built_swaps[0]
    assert isinstance(swap, ql.OvernightIndexedSwap)
    assert swap.overnightIndex().familyName() == "SOFR"
    assert swap.overnightIndex().forwardingTermStructure().discount(
        ql.Date(7, 4, 2026)
    ) == pytest.approx(projection_curve.discount(ql.Date(7, 4, 2026)))

    assert len(built_engines) == 1
    assert isinstance(built_engines[0], original_engine_class)
    assert discount_handles[0].discount(ql.Date(7, 4, 2026)) == pytest.approx(
        discount_curve.discount(ql.Date(7, 4, 2026))
    )

    # PricingService returns only after attaching the engine and completing its
    # normal QuantLib instrument pricing call. Validate result shape/health,
    # with no Bloomberg value comparison or tolerance.
    assert result.trade_id == instrument.trade_id()
    assert result.currency == "USD"
    assert isinstance(result.npv, Real) and not isinstance(result.npv, bool)
    assert math.isfinite(float(result.npv))

    def value_text(value):
        return repr(float(value))

    def date_text(value):
        return value.ISO()

    discount_reference_date = discount_curve.referenceDate()
    projection_reference_date = projection_curve.referenceDate()
    print(f"IRS_DIAGNOSTICS trade_id={trade['trade_id']}")
    print(f"total_npv={value_text(result.npv)}")
    print(f"fixed_leg_npv={value_text(swap.fixedLegNPV())}")
    print(f"floating_leg_npv={value_text(swap.overnightLegNPV())}")
    print(f"discount_curve_reference_date={date_text(discount_reference_date)}")
    print(f"projection_curve_reference_date={date_text(projection_reference_date)}")

    leg_details = (
        ("fixed", swap.fixedLeg(), -1.0 if fixed["direction"] == "payer" else 1.0),
        (
            "floating",
            swap.overnightLeg(),
            1.0 if floating["direction"] == "receiver" else -1.0,
        ),
    )
    for leg_name, cashflows, sign in leg_details:
        for period_number, cashflow in enumerate(cashflows, start=1):
            if leg_name == "floating":
                coupon = ql.as_overnight_indexed_coupon(cashflow)
            else:
                coupon = ql.as_coupon(cashflow)

            payment_date = cashflow.date()
            notional = coupon.nominal()
            amount = cashflow.amount()
            discount_factor = discount_curve.discount(payment_date)
            present_value = sign * amount * discount_factor
            rate_value = coupon.rate()

            print(
                f"{leg_name}_period[{period_number}]: "
                f"accrual_start={date_text(coupon.accrualStartDate())} "
                f"accrual_end={date_text(coupon.accrualEndDate())} "
                f"payment_date={date_text(payment_date)} "
                f"notional={value_text(notional)} "
                f"coupon_rate={value_text(rate_value)} "
                f"cashflow_amount={value_text(amount)} "
                f"discount_factor={value_text(discount_factor)} "
                f"present_value={value_text(present_value)}"
            )

            if leg_name == "floating":
                try:
                    effective_index_fixing = coupon.effectiveIndexFixing()
                    effective_coupon_rate = coupon.rate()
                    print(
                        f"floating_period[{period_number}]_overnight: "
                        f"effective_index_fixing={value_text(effective_index_fixing)} "
                        f"effective_coupon_rate={value_text(effective_coupon_rate)}"
                    )
                except (AttributeError, RuntimeError, TypeError) as exc:
                    print(
                        f"floating_period[{period_number}]_overnight: "
                        f"effective_coupon=UNAVAILABLE ({type(exc).__name__}: {exc})"
                    )
