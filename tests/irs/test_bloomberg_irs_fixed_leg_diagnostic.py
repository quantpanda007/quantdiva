"""Read-only fixed-leg cashflow and discount-factor diagnostic for SLLSL9RR."""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import QuantLib as ql
import pytest
import registry.bootstrap  # noqa: F401 - register the public IRS instrument

from api.v1.helpers import build_instrument_from_request
from api.v1.schemas import InstrumentRequest
from core.interfaces.base import MarketEnvironment
from core.types.value_objects import PricingDate
from market.curves.yield_curve import CurveDefinition, YieldCurveBuilder

# Validation-phase test (reads Bloomberg fixtures): excluded from the default run;
# run with `pytest -m validation`.
pytestmark = pytest.mark.validation


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "bloomberg_irs_case.json"
)
BLOOMBERG_FIXED_LEG_NPV = -31978.74


def test_canonical_fixed_leg_discounted_cashflows_diagnostic():
    case = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    trade = case["trade"]
    fixed = trade["fixed_leg"]
    floating = trade["floating_leg"]
    conventions = case["conventions"]
    market = case["market_environment"]
    reference_date = date.fromisoformat(market["reference_date"])

    discount_curve = YieldCurveBuilder().build(
        CurveDefinition(
            currency="USD",
            pricing_date=PricingDate(reference_date),
            discount_factors=[
                (date.fromisoformat(point["date"]), point["discount_factor"])
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
    instrument = build_instrument_from_request(
        InstrumentRequest(type="irs", params=params)
    )
    market_env = MarketEnvironment(
        pricing_date=PricingDate(reference_date),
        discount_curves={"USD": discount_curve},
        # No floating coupon calculation is requested by this test.
        forecast_curves={"USD": ql.YieldTermStructureHandle()},
    )
    swap = instrument.build(market_env)

    fixed_leg = swap.fixedLeg()
    assert len(fixed_leg) == 2
    payer_sign = -1.0 if fixed["direction"] == "payer" else 1.0
    details = []
    for cashflow in fixed_leg:
        payment_date = cashflow.date()
        amount = cashflow.amount()
        discount_factor = discount_curve.discount(payment_date)
        pv = payer_sign * amount * discount_factor
        details.append((cashflow, amount, discount_factor, pv))

    fixed_leg_pv = sum(item[3] for item in details)
    assert math.isfinite(fixed_leg_pv)
    assert fixed_leg_pv < 0.0

    print("FIXED_LEG_DISCOUNT_DIAGNOSTIC trade_id=SLLSL9RR")
    for i, (cashflow, amount, discount_factor, pv) in enumerate(details, start=1):
        print(
            f"period[{i}] payment_date={cashflow.date().ISO()} "
            f"cashflow={amount:.12f} "
            f"discount_factor={discount_factor:.12f} "
            f"signed_pv={pv:.12f}"
        )
    difference = fixed_leg_pv - BLOOMBERG_FIXED_LEG_NPV
    print(f"fixed_leg_pv={fixed_leg_pv:.12f}")
    print(f"bloomberg_reference_fixed_leg_npv={BLOOMBERG_FIXED_LEG_NPV:.2f}")
    print(f"difference_vs_bloomberg={difference:.12f}")

    assert tuple(item[0].date().ISO() for item in details) == (
        "2027-05-28",
        "2027-11-30",
    )
    assert tuple(item[1] for item in details) == pytest.approx(
        (26647.2222222222, 6845.8333333333), abs=1e-8
    )
    assert tuple(item[2] for item in details) == pytest.approx(
        (0.9575097772775483, 0.9403359266768191), abs=1e-14
    )
    assert fixed_leg_pv == pytest.approx(-31952.3588464404, abs=1e-8)
