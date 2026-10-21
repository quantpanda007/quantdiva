"""Shared fixtures for fresh IRS tests: the USD SOFR zero curve of 31-Mar-2026.

The JSON fixture format is a test concern only. It is translated here into the
structured ``ZeroCurveMarketData`` the production builder accepts, so the
builder never depends on the fixture's path or layout.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import QuantLib as ql

from core.enums.definitions import DayCountConvention, Frequency
from core.types.value_objects import Money
from instruments.rates.irs.domain import IRSLegKind, IRSLegTerms, ObservationConventions
from instruments.rates.irs.engine import attach_discounting_engine
from instruments.rates.irs.fixed_leg import QuantLibFixedLeg, build_fixed_leg
from instruments.rates.irs.floating_leg import QuantLibFloatingLeg, build_floating_leg
from instruments.rates.irs.instrument import QuantLibIRSInstrument, assemble_quantlib_irs
from instruments.rates.irs.quantlib_schedule import translate_leg_schedule
from instruments.rates.irs.schedule import CouponPeriod, LegSchedule
from market.curves.irs_market_data import QuantLibDiscountCurve
from market.curves.irs_zero_curve import (
    FLAT_FIRST_ZERO,
    LINEAR_ZERO,
    ZeroCurveConventions,
    ZeroCurveMarketData,
    ZeroCurveObservation,
    build_zero_curve,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests/fixtures/bloomberg_irs"
# Raw source of the USD prepared snapshot, kept beside it in the canonical market-data layout
# (moved from tests/fixtures/bloomberg_irs/curves/ unchanged; migration 2026-10-21).
USD_SOFR_ZERO_FIXTURE = ROOT / "market_data/2026-03-31/USD/2026-03-31-USD-SOFR-zero.json"

# Export rounding: DF to 6 dp (5e-7) plus zero rate to 5 dp of a percent
# (<= 5e-8 * t * DF, about 2.5e-7 at 5Y). 1e-6 covers both and still rejects a
# wrong spot lag or tenor (e.g. spot lag 0 instead of 2 shifts every pillar by two
# days), whose DF errors are of order 1e-4.
USD_SOFR_DF_TOLERANCE = 1e-6


def load_usd_sofr_zero_fixture() -> dict:
    return json.loads(USD_SOFR_ZERO_FIXTURE.read_text(encoding="utf-8"))


def usd_sofr_market_data_from_fixture(document: dict) -> ZeroCurveMarketData:
    return ZeroCurveMarketData(
        reference_date=date.fromisoformat(document["reference_date"]),
        currency=document["currency"],
        benchmark=document["benchmark"],
        observations=tuple(
            ZeroCurveObservation(
                tenor=row["inferred_tenor"],
                zero_rate=row["zero_rate_percent"] / 100.0,
                discount_factor=row["discount_factor"],
            )
            for row in document["observations"]
        ),
    )


def usd_sofr_conventions() -> ZeroCurveConventions:
    return ZeroCurveConventions(
        calendar=ql.UnitedStates(ql.UnitedStates.SOFR),
        spot_lag_days=2,
        business_day_convention=ql.ModifiedFollowing,
        end_of_month=False,
        day_counter=ql.Actual365Fixed(),
        compounding=ql.Continuous,
        interpolation=LINEAR_ZERO,
        front_extrapolation=FLAT_FIRST_ZERO,
        allow_extrapolation=False,
        discount_factor_tolerance=USD_SOFR_DF_TOLERANCE,
    )


@pytest.fixture(scope="session")
def usd_sofr_zero_document() -> dict:
    return load_usd_sofr_zero_fixture()


@pytest.fixture(scope="session")
def usd_sofr_market_data(usd_sofr_zero_document) -> ZeroCurveMarketData:
    return usd_sofr_market_data_from_fixture(usd_sofr_zero_document)


@pytest.fixture(scope="session")
def usd_sofr_curve_conventions() -> ZeroCurveConventions:
    return usd_sofr_conventions()


# --- TC1 -------------------------------------------------------------------


def load_tc1() -> tuple[dict, dict, dict]:
    """Canonical case, untouched Bloomberg source, and Bloomberg reference outputs."""

    def _json(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    return (
        _json(FIXTURES / "cases/TC1.json"),
        _json(FIXTURES / "source/TC1.json"),
        _json(FIXTURES / "references/TC1.json"),
    )


@dataclass(frozen=True)
class PricedTC1:
    instrument: QuantLibIRSInstrument
    fixed: QuantLibFixedLeg
    floating: QuantLibFloatingLeg
    discount_handle: ql.YieldTermStructureHandle


def build_tc1_swap(case: dict, source: dict, curve) -> PricedTC1:
    """Assemble TC1 with Optima's production leg, swap and engine builders.

    Trade terms come from the canonical case, except the lookback, which is read
    from the Bloomberg source (``leg_2.days_before_accrual`` = 0); the case
    fixture records 1 (open item OI-3). ``curve`` is used for both projection
    and discounting. The caller owns the global evaluation date.
    """
    trade = case["trade"]
    pay, receive = trade["pay_leg"], trade["receive_leg"]
    boundaries = case["schedule_inputs"]["receive_leg"]["explicit_accrual_boundaries"]
    payments = case["schedule_inputs"]["receive_leg"]["payment_dates"]
    balances = [row["notional"] for row in trade["amortization_source"]["period_notionals"]]
    periods = tuple(
        CouponPeriod(
            date.fromisoformat(boundaries[i]),
            date.fromisoformat(boundaries[i + 1]),
            date.fromisoformat(payments[i]),
            Money(Decimal(str(balances[i])), trade["currency"]),
        )
        for i in range(len(payments))
    )
    schedule = translate_leg_schedule(LegSchedule(periods=periods, principal_repayments=()))
    notional = Money(Decimal(str(trade["notional"]["amount"])), trade["currency"])
    fixed_terms = IRSLegTerms(
        kind=IRSLegKind.FIXED,
        payment_frequency=Frequency.ANNUAL,
        day_count=DayCountConvention.ACT_360,
        original_notional=notional,
        fixed_coupon_rate=Decimal(str(pay["fixed_coupon"]["value"])) / Decimal(100),
    )
    observation = receive["observation"]
    floating_terms = IRSLegTerms(
        kind=IRSLegKind.FLOATING,
        payment_frequency=Frequency.ANNUAL,
        day_count=DayCountConvention.ACT_360,
        original_notional=notional,
        benchmark="SOFRRATE",
        benchmark_tenor=receive["benchmark_tenor"],
        floating_spread_rate=Decimal(str(receive["floating_spread"]["value"])) / Decimal(10000),
        floating_leverage=Decimal(str(receive["leverage"])),
        reset_frequency=Frequency.DAILY,
        observation=ObservationConventions(
            lookback_days=source["leg_2"]["days_before_accrual"],
            cutoff_days=observation["cutoff_days"],
            reset_timing=observation["reset_timing"],
            compounding=observation["compounding"],
            lookback_type=observation["lookback_type"],
        ),
    )
    fixed = build_fixed_leg(fixed_terms, schedule)
    floating = build_floating_leg(
        floating_terms, schedule, trade["currency"], forwarding_curve=curve.handle
    )
    instrument = assemble_quantlib_irs(fixed, floating)
    # attach_discounting_engine reads only ``.handle``; the zero curve is wrapped
    # in the existing discount-curve record without its DF market data.
    attach_discounting_engine(
        instrument, QuantLibDiscountCurve(None, curve.term_structure, curve.handle)
    )
    return PricedTC1(instrument, fixed, floating, curve.handle)


def build_usd_sofr_zero_curve():
    """Production zero-curve builder fed from the committed fixture."""
    return build_zero_curve(
        usd_sofr_market_data_from_fixture(load_usd_sofr_zero_fixture()),
        usd_sofr_conventions(),
        expected_currency="USD",
        expected_benchmark="SOFR",
    )


def _py(value: ql.Date) -> date:
    return date(value.year(), value.month(), value.dayOfMonth())


@pytest.fixture(scope="session")
def tc1_documents() -> tuple[dict, dict, dict]:
    return load_tc1()


@pytest.fixture(scope="session")
def tc1_valuation(tc1_documents) -> dict:
    """Price TC1 once on the production zero curve and snapshot every output.

    All QuantLib evaluation happens inside this fixture while the evaluation
    date is set, then the previous global date is restored.
    """
    case, source, _ = tc1_documents
    valuation_date = date.fromisoformat(case["trade"]["valuation_date"])
    previous = ql.Settings.instance().evaluationDate
    ql.Settings.instance().evaluationDate = ql.Date(
        valuation_date.day, valuation_date.month, valuation_date.year
    )
    try:
        curve = build_usd_sofr_zero_curve()
        priced = build_tc1_swap(case, source, curve)
        swap = priced.instrument.quantlib_instrument
        floating_periods = []
        for coupon in priced.floating.coupons:
            floating_periods.append(
                {
                    "accrual_start": _py(coupon.accrualStartDate()),
                    "accrual_end": _py(coupon.accrualEndDate()),
                    "payment_date": _py(coupon.date()),
                    "fixing_dates": [_py(d) for d in coupon.fixingDates()],
                    "value_dates": [_py(d) for d in coupon.valueDates()],
                    "interest_dates": [_py(d) for d in coupon.interestDates()],
                    "dt": list(coupon.dt()),
                    "rate_pct": coupon.rate() * 100.0,
                    "amount": coupon.amount(),
                    "accrual_days": coupon.accrualDays(),
                    "discount_factor": priced.discount_handle.discount(coupon.date()),
                }
            )
        fixed_periods = [
            {
                "payment_date": _py(coupon.date()),
                "amount": coupon.amount(),
                "discount_factor": priced.discount_handle.discount(coupon.date()),
            }
            for coupon in priced.fixed.coupons
        ]
        return {
            "lookback_days": priced.floating.observation_settings.lookback_days,
            "lockout_days": priced.floating.observation_settings.quantlib_lockout_days,
            "floating": floating_periods,
            "fixed": fixed_periods,
            # Pay fixed (leg 0), receive floating (leg 1).
            "fixed_leg_npv": swap.legNPV(0),
            "floating_leg_npv": swap.legNPV(1),
            "npv": swap.NPV(),
        }
    finally:
        ql.Settings.instance().evaluationDate = previous
