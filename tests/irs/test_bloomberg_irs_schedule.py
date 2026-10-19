"""Canonical SLLSL9RR schedule, amortization, and fixed-cashflow contract."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
import QuantLib as ql
import registry.bootstrap  # noqa: F401 - register the public IRS instrument

from api.v1.helpers import build_instrument_from_request
from api.v1.schemas import InstrumentRequest
from core.interfaces.base import MarketEnvironment
from core.types.value_objects import PricingDate


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "bloomberg_irs_case.json"
)


def test_canonical_irs_schedule_amortization_and_fixed_cashflows():
    case = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    trade = case["trade"]
    fixed = trade["fixed_leg"]
    floating = trade["floating_leg"]
    conventions = case["conventions"]
    market = case["market_environment"]

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
        pricing_date=PricingDate(date.fromisoformat(market["valuation_date"])),
        forecast_curves={"USD": ql.YieldTermStructureHandle()},
    )
    swap = instrument.build(market_env)

    assert isinstance(swap, ql.OvernightIndexedSwap)
    expected_periods = (
        ("2026-05-31", "2027-05-28", "2027-05-28", 530000.0),
        ("2027-05-28", "2027-11-30", "2027-11-30", 265000.0),
    )

    fixed_schedule = swap.fixedSchedule()
    floating_schedule = swap.floatingSchedule()
    assert tuple(d.ISO() for d in fixed_schedule) == (
        "2026-05-31",
        "2027-05-28",
        "2027-11-30",
    )
    assert tuple(d.ISO() for d in floating_schedule) == tuple(
        d.ISO() for d in fixed_schedule
    )
    assert fixed_schedule.rule() == ql.DateGeneration.Backward
    assert floating_schedule.rule() == ql.DateGeneration.Backward

    fixed_leg = swap.fixedLeg()
    floating_leg = swap.overnightLeg()
    # Exactly two coupon cashflows per leg means no separate principal exchange.
    assert len(fixed_leg) == 2
    assert len(floating_leg) == 2
    assert swap.numberOfLegs() == 2

    fixed_coupons = [ql.as_fixed_rate_coupon(flow) for flow in fixed_leg]
    floating_coupons = [
        ql.as_overnight_indexed_coupon(flow) for flow in floating_leg
    ]
    assert tuple(swap.fixedNominals()) == (530000.0, 265000.0)
    assert tuple(swap.floatingNominals()) == (530000.0, 265000.0)

    for i, (start, end, payment, notional) in enumerate(expected_periods):
        fixed_coupon = fixed_coupons[i]
        overnight_coupon = floating_coupons[i]
        assert fixed_coupon.accrualStartDate().ISO() == start
        assert fixed_coupon.accrualEndDate().ISO() == end
        assert fixed_coupon.date().ISO() == payment
        assert fixed_coupon.nominal() == notional
        assert fixed_coupon.rate() == pytest.approx(0.05)
        assert fixed_coupon.accrualDays() == (362 if i == 0 else 186)

        assert overnight_coupon.accrualStartDate().ISO() == start
        assert overnight_coupon.accrualEndDate().ISO() == end
        assert overnight_coupon.date().ISO() == payment
        assert overnight_coupon.nominal() == notional

    assert fixed_coupons[0].amount() == pytest.approx(26647.22, abs=0.01)
    assert fixed_coupons[1].amount() == pytest.approx(6845.83, abs=0.01)
