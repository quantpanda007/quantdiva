"""TC1 Period 1 regression against Bloomberg (QuantLib 1.43 baseline).

Period 1 accrues from Sunday 31-May-2026, a SOFR fixing holiday. QuantLib
<= 1.42.1 drops that day's interest (-1.05 bp / -$56 on this coupon); 1.43
fixes it (QuantLib PR #2556). This test pins the observation schedule and the
Bloomberg Period 1 equivalent coupon and payment.

Scope and assumptions (deliberately narrow):
* Trade terms come from tests/fixtures/bloomberg_irs/cases/TC1.json, except the
  lookback, which is read from the Bloomberg source (source/TC1.json
  ``leg_2.days_before_accrual`` = 0). The case fixture records 1; that
  discrepancy is known and is not changed here.
* Legs, swap and discounting engine are Optima's production builders, unchanged.
  The production mapping keeps Bloomberg's 1-day rate cutoff as metadata
  (lockoutDays=0); on TC1 the cutoff moves the coupon by ~0.001 bp.
* The curve is a test-only oracle built from the Bloomberg zero-rate export
  (tests/fixtures/bloomberg_irs/curves/2026-03-31-USD-SOFR-zero.json): T+2 spot
  + tenor pillars, continuous ACT/365F zero rates, linear interpolation, one
  curve for projection and discounting. It is not a production curve.
* Period 2 is not asserted: its remaining 0.05 bp / $0.73 gap is the open
  30-Nov-2027 curve-interpolation item, tracked separately.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import QuantLib as ql

from core.enums.definitions import DayCountConvention, Frequency
from core.types.value_objects import Money
from instruments.rates.irs.domain import IRSLegKind, IRSLegTerms, ObservationConventions
from instruments.rates.irs.engine import attach_discounting_engine
from instruments.rates.irs.fixed_leg import build_fixed_leg
from instruments.rates.irs.floating_leg import build_floating_leg
from instruments.rates.irs.instrument import assemble_quantlib_irs
from instruments.rates.irs.quantlib_schedule import translate_leg_schedule
from instruments.rates.irs.schedule import CouponPeriod, LegSchedule
from market.curves.irs_market_data import QuantLibDiscountCurve

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests/fixtures/bloomberg_irs"

# Bloomberg reference values (references/TC1.json, cashflow_leg_2[0]).
BBG_P1_COUPON_PCT = 3.78546
BBG_P1_PAYMENT = 20174.40
# 0.01 bp on the coupon; $0.05 on the payment covers the 5-dp coupon display
# band (+/-$0.027) plus 5-dp zero-rate input rounding.
COUPON_TOLERANCE_PCT = 1e-4
PAYMENT_TOLERANCE = 0.05


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _ql_date(value: str) -> ql.Date:
    d = date.fromisoformat(value)
    return ql.Date(d.day, d.month, d.year)


def _py(value: ql.Date) -> date:
    return date(value.year(), value.month(), value.dayOfMonth())


@pytest.fixture(scope="module")
def tc1():
    case = _json(FIXTURES / "cases/TC1.json")
    source = _json(FIXTURES / "source/TC1.json")
    reference = _json(FIXTURES / "references/TC1.json")
    curve_data = _json(FIXTURES / "curves/2026-03-31-USD-SOFR-zero.json")
    return case, source, reference, curve_data


@pytest.fixture(scope="module")
def priced(tc1):
    case, source, _, curve_data = tc1
    trade = case["trade"]
    reference_date = _ql_date(trade["valuation_date"])

    previous = ql.Settings.instance().evaluationDate
    ql.Settings.instance().evaluationDate = reference_date
    try:
        # --- test-only oracle curve -------------------------------------------
        calendar = ql.UnitedStates(ql.UnitedStates.SOFR)
        spot = calendar.advance(reference_date, 2, ql.Days)
        rows = curve_data["observations"]
        pillars = [
            calendar.advance(spot, ql.Period(row["inferred_tenor"]), ql.ModifiedFollowing, False)
            for row in rows
        ]
        assert [p.ISO() for p in pillars] == [row["pillar_date"] for row in rows]
        zeros = [row["zero_rate_percent"] / 100.0 for row in rows]
        term_structure = ql.ZeroCurve(
            [reference_date] + pillars,
            [zeros[0]] + zeros,
            ql.Actual365Fixed(),
            calendar,
            ql.Linear(),
            ql.Continuous,
        )
        handle = ql.YieldTermStructureHandle(term_structure)

        # --- trade from the canonical case (lookback from Bloomberg source) ----
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
            floating_terms, schedule, trade["currency"], forwarding_curve=handle
        )
        instrument = assemble_quantlib_irs(fixed, floating)
        attach_discounting_engine(instrument, QuantLibDiscountCurve(None, term_structure, handle))

        coupon = floating.coupons[0]
        result = {
            "coupon": coupon,
            "fixing_dates": [_py(d) for d in coupon.fixingDates()],
            "value_dates": [_py(d) for d in coupon.valueDates()],
            "interest_dates": [_py(d) for d in coupon.interestDates()],
            "dt": list(coupon.dt()),
            "rate_pct": coupon.rate() * 100.0,
            "amount": coupon.amount(),
            "accrual_days": coupon.accrualDays(),
            "lookback_days": floating.observation_settings.lookback_days,
            "npv": instrument.quantlib_instrument.NPV(),
        }
    finally:
        ql.Settings.instance().evaluationDate = previous
    return result


def test_lookback_is_taken_from_bloomberg_source(tc1, priced):
    _, source, _, _ = tc1
    assert source["leg_2"]["days_before_accrual"] == 0
    assert priced["lookback_days"] == 0


def test_period1_has_249_fixings_covering_all_362_accrual_days(priced):
    assert len(priced["fixing_dates"]) == 249
    assert priced["accrual_days"] == 362
    assert sum(priced["dt"]) * 360.0 == pytest.approx(362.0, abs=1e-9)


def test_period1_first_observation_accrues_sunday_at_friday_fixing(priced):
    assert priced["fixing_dates"][0] == date(2026, 5, 29)
    assert priced["value_dates"][0:2] == [date(2026, 5, 29), date(2026, 6, 1)]
    assert priced["interest_dates"][0:2] == [date(2026, 5, 31), date(2026, 6, 1)]
    assert priced["dt"][0] * 360.0 == pytest.approx(1.0, abs=1e-12)
    assert priced["fixing_dates"][1] == date(2026, 6, 1)


def test_period1_last_observation(priced):
    # Production keeps the 1-day cutoff as metadata (lockoutDays=0), so the last
    # observation is the Thursday fixing for Thursday->Friday.
    assert priced["fixing_dates"][-1] == date(2027, 5, 27)
    assert priced["value_dates"][-2:] == [date(2027, 5, 27), date(2027, 5, 28)]
    assert priced["interest_dates"][-2:] == [date(2027, 5, 27), date(2027, 5, 28)]
    assert priced["dt"][-1] * 360.0 == pytest.approx(1.0, abs=1e-12)


def test_period1_reference_values_are_the_bloomberg_oracle(tc1):
    _, _, reference, _ = tc1
    row = reference["source_oracle_sections"]["cashflow_leg_2"]["cashflows"][0]
    assert row["accrual_start"] == "2026-05-31" and row["accrual_end"] == "2027-05-28"
    assert row["equivalent_coupon"] == BBG_P1_COUPON_PCT
    assert row["payment"] == BBG_P1_PAYMENT


def test_period1_coupon_matches_bloomberg(priced):
    assert priced["rate_pct"] == pytest.approx(BBG_P1_COUPON_PCT, abs=COUPON_TOLERANCE_PCT)


def test_period1_payment_matches_bloomberg(priced):
    assert priced["amount"] == pytest.approx(BBG_P1_PAYMENT, abs=PAYMENT_TOLERANCE)
