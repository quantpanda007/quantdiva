"""TDD contract for separate SOFR projection and discount engine wiring."""

from __future__ import annotations

import json
from datetime import date
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


def test_pricing_service_uses_projection_curve_for_sofr_and_discount_curve_for_engine(
    monkeypatch,
):
    case = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    trade = case["trade"]
    fixed = trade["fixed_leg"]
    floating = trade["floating_leg"]
    conventions = case["conventions"]
    market = case["market_environment"]
    reference_date = date.fromisoformat(market["reference_date"])

    # The discount input uses only supplied Discount Factor observations.
    discount_factors = [
        (date.fromisoformat(point["date"]), point["discount_factor"])
        for point in market["market_data_points"]
    ]
    builder = YieldCurveBuilder()
    discount_curve = builder.build(
        CurveDefinition(
            currency="USD",
            pricing_date=PricingDate(reference_date),
            discount_factors=discount_factors,
        )
    )

    # The projection input uses only Market Rate observations. YieldCurveBuilder
    # applies the provisional percent scale, first/reference interval, prior
    # quote-date interval boundaries, and Actual/360 accrual documented in its
    # simple-forward conversion path. These assumptions remain provisional.
    forward_rates = [
        (date.fromisoformat(point["date"]), point["market_rate"])
        for point in market["market_data_points"]
    ]
    projection_curve = builder.build(
        CurveDefinition(
            currency="USD",
            pricing_date=PricingDate(reference_date),
            forward_rates=forward_rates,
        )
    )
    assert discount_curve is not projection_curve
    assert discount_curve.currentLink() is not projection_curve.currentLink()

    market_env = MarketEnvironment(
        pricing_date=PricingDate(reference_date),
        discount_curves={"USD": discount_curve},
        forecast_curves={"USD": projection_curve},
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
        # The current API schema has no fields for dated dual curves, so the
        # fixture curves are built above and placed in MarketEnvironment.
        market_data=MarketDataRequest(
            pricing_date=market["valuation_date"],
            underlyings={"USD": UnderlyingData(spot=1.0)},
        ),
        model="black_scholes",
        engine="analytic",
    )
    instrument = build_instrument_from_request(request.instrument)

    built_swaps = []
    original_build = instrument.build

    def capture_swap_build(environment):
        swap = original_build(environment)
        built_swaps.append(swap)
        return swap

    instrument.build = capture_swap_build

    original_engine_class = ql.DiscountingSwapEngine
    engine_curves = []
    built_engines = []

    def capture_discounting_engine(curve, *args, **kwargs):
        engine_curves.append(curve)
        engine = original_engine_class(curve, *args, **kwargs)
        built_engines.append(engine)
        return engine

    # Observe the public QuantLib engine-constructor argument used by the
    # registered engine while allowing PricingService to run its normal flow.
    monkeypatch.setattr(ql, "DiscountingSwapEngine", capture_discounting_engine)
    pricing_result = PricingService().price(
        instrument=instrument,
        market_env=market_env,
        model_type=request.model,
        engine_type=request.engine,
    )

    assert pricing_result.trade_id == instrument.trade_id()
    assert len(built_swaps) == 1
    swap = built_swaps[0]
    assert isinstance(swap, ql.OvernightIndexedSwap)

    # The OIS's public index handle must forecast from the projection curve.
    sofr_index = swap.overnightIndex()
    assert sofr_index.familyName() == "SOFR"
    index_curve = sofr_index.forwardingTermStructure()
    probe_date = ql.Date(7, 4, 2026)
    assert index_curve.discount(probe_date) == pytest.approx(
        projection_curve.discount(probe_date), rel=1e-13, abs=1e-14
    )
    assert index_curve.discount(probe_date) != pytest.approx(
        discount_curve.discount(probe_date), rel=1e-10, abs=1e-12
    )

    # The registered IRS engine is DiscountingSwapEngine, and its public
    # constructor receives the USD discount handle from MarketEnvironment.
    assert len(engine_curves) == 1
    assert isinstance(built_engines[0], original_engine_class)
    assert engine_curves[0].discount(probe_date) == pytest.approx(
        discount_curve.discount(probe_date), rel=1e-13, abs=1e-14
    )
    assert engine_curves[0].discount(probe_date) != pytest.approx(
        projection_curve.discount(probe_date), rel=1e-10, abs=1e-12
    )

    # PricingService returned only after its normal instrument build, engine
    # attachment, and QuantLib pricing call completed successfully.
