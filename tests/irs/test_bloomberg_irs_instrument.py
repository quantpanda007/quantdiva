"""Instrument-construction contract for the canonical Bloomberg IRS inputs."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import QuantLib as ql
import registry.bootstrap  # noqa: F401 - register the public IRS instrument

from api.v1.helpers import build_instrument_from_request
from api.v1.schemas import InstrumentRequest
from core.interfaces.base import MarketEnvironment
from core.types.value_objects import PricingDate

import pytest

# Validation-phase test (reads Bloomberg fixtures): excluded from the default run;
# run with `pytest -m validation`.
pytestmark = pytest.mark.validation


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "bloomberg_irs_case.json"
)


def test_canonical_bloomberg_case_builds_sofr_overnight_indexed_swap():
    case = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    trade = case["trade"]
    fixed = trade["fixed_leg"]
    floating = trade["floating_leg"]
    conventions = case["conventions"]
    market = case["market_environment"]

    # Adapt the canonical fixture fields to the existing registered IRS request
    # contract; construction still goes through Optima's public request helper.
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
        # ql.OvernightIndexedSwap.Payer is pay fixed / receive floating.
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
        # An unlinked handle is not market data; it lets the legacy index
        # constructor receive a handle instead of None. No curve is built or
        # queried because this test only constructs the instrument.
        forecast_curves={"USD": ql.YieldTermStructureHandle()},
    )

    swap = instrument.build(market_env)

    # This is the first intended failure on the current implementation:
    # InterestRateSwap.build() currently returns ql.VanillaSwap.
    assert isinstance(swap, ql.OvernightIndexedSwap), (
        "Canonical SOFR IRS must build ql.OvernightIndexedSwap; "
        f"current instrument builder returned {type(swap).__name__}."
    )

    assert instrument.currency() == "USD"
    assert instrument.start_date.isoformat() == trade["effective_date"]
    assert instrument.end_date.isoformat() == trade["maturity_date"]
    assert swap.startDate().ISO() <= trade["effective_date"]
    assert swap.maturityDate().ISO() == trade["maturity_date"]

    assert swap.type() == ql.OvernightIndexedSwap.Payer
    assert swap.fixedRate() == fixed["rate"]
    assert swap.spread() == floating["spread_decimal"]
    assert swap.paymentFrequency() == ql.Annual
    assert swap.fixedDayCount().name() == "Actual/360"

    # QuantLib exposes this getter as OvernightIndex (the base wrapper), not
    # as the ql.Sofr subclass. familyName() identifies SOFR without depending
    # on the version-specific display string returned by name().
    index = swap.overnightIndex()
    assert isinstance(index, ql.OvernightIndex)
    assert index.familyName() == "SOFR"
    assert index.currency().code() == "USD"
    assert index.tenor().length() == 1
    assert index.tenor().units() == ql.Days
    assert index.dayCounter().name() == "Actual/360"

    fixed_schedule = swap.fixedSchedule()
    floating_schedule = swap.floatingSchedule()
    assert fixed_schedule.rule() == ql.DateGeneration.Backward
    assert floating_schedule.rule() == ql.DateGeneration.Backward
    # Accrual boundaries remain as specified; payment dates use Modified
    # Following independently through OvernightIndexedSwap's payment settings.
    assert fixed_schedule.businessDayConvention() == ql.Unadjusted
    assert floating_schedule.businessDayConvention() == ql.Unadjusted
    assert fixed_schedule.terminationDateBusinessDayConvention() == ql.ModifiedFollowing
    assert floating_schedule.terminationDateBusinessDayConvention() == ql.ModifiedFollowing
    expected_accrual_dates = ("2026-05-31", "2027-05-28", "2027-11-30")
    assert len(fixed_schedule) == 3
    assert len(floating_schedule) == 3
    assert tuple(date.ISO() for date in fixed_schedule) == expected_accrual_dates
    assert tuple(date.ISO() for date in floating_schedule) == expected_accrual_dates
    assert len(swap.fixedLeg()) == 2
    assert len(swap.overnightLeg()) == 2
    assert tuple(swap.fixedNominals()) == (530000.0, 265000.0)
    assert tuple(swap.floatingNominals()) == (530000.0, 265000.0)
    assert tuple(flow.date().ISO() for flow in swap.fixedLeg()) == (
        "2027-05-28",
        "2027-11-30",
    )
    assert tuple(flow.date().ISO() for flow in swap.overnightLeg()) == (
        "2027-05-28",
        "2027-11-30",
    )

    # The OIS getter returns cashflows; QuantLib's public cast exposes the
    # overnight indexed coupon type and its observable daily fixing schedule.
    overnight_coupons = [
        ql.as_overnight_indexed_coupon(cashflow)
        for cashflow in swap.overnightLeg()
    ]
    assert all(
        isinstance(coupon, ql.OvernightIndexedCoupon)
        for coupon in overnight_coupons
    )
    assert all(
        coupon.dayCounter().name() == "Actual/360"
        and coupon.averagingMethod() == ql.RateAveraging.Compound
        and coupon.compoundSpreadDaily() is False
        and coupon.spread() == floating["spread_decimal"]
        for coupon in overnight_coupons
    )

    assert swap.lookbackDays() == conventions["lookback_days"]
    assert swap.lockoutDays() == conventions["rate_cutoff_days"]
    assert swap.averagingMethod() == ql.RateAveraging.Compound
    for coupon in overnight_coupons:
        fixing_dates = coupon.fixingDates()
        # OvernightIndexedCoupon.isInArrears() is False in the installed 1.41
        # binding even for OIS coupons. Verify the public daily observations
        # spanning the accrual period instead of relying on that flag.
        assert len(fixing_dates) > 1
        assert fixing_dates[0] < coupon.accrualEndDate()
        assert fixing_dates[-1] < coupon.accrualEndDate()
