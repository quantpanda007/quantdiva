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
  (lockoutDays=0); on TC1 the cutoff moves the coupon by ~0.001 bp (open item OI-2).
* The curve is the production zero-curve builder (market/curves/irs_zero_curve.py)
  fed from the committed fixture market_data/2026-03-31/USD/
  2026-03-31-USD-SOFR-zero.json: T+2 spot + tenor pillars, continuous ACT/365F
  zero rates, linear interpolation, one curve for projection and discounting.
  Trade assembly and the curve are shared with the reconciliation tests via
  conftest.py (``tc1_valuation``).
* Period 2 and NPV are covered by test_tc1_bloomberg_reconciliation.py; their
  remaining gap is the open 30-Nov-2027 curve item (OI-1, docs/IRS_OPEN_ITEMS.md).
"""

from __future__ import annotations

from datetime import date

import pytest

# Bloomberg reference values (references/TC1.json, cashflow_leg_2[0]).
BBG_P1_COUPON_PCT = 3.78546
BBG_P1_PAYMENT = 20174.40
# 0.01 bp on the coupon; $0.05 on the payment covers the 5-dp coupon display
# band (+/-$0.027) plus 5-dp zero-rate input rounding.
COUPON_TOLERANCE_PCT = 1e-4
PAYMENT_TOLERANCE = 0.05


@pytest.fixture(scope="module")
def priced(tc1_valuation):
    """Period 1 view of the shared TC1 valuation (same keys as before the refactor)."""
    period = tc1_valuation["floating"][0]
    return {**period, "lookback_days": tc1_valuation["lookback_days"]}


def test_lookback_is_taken_from_bloomberg_source(tc1_documents, priced):
    _, source, _ = tc1_documents
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


def test_period1_reference_values_are_the_bloomberg_oracle(tc1_documents):
    _, _, reference = tc1_documents
    row = reference["source_oracle_sections"]["cashflow_leg_2"]["cashflows"][0]
    assert row["accrual_start"] == "2026-05-31" and row["accrual_end"] == "2027-05-28"
    assert row["equivalent_coupon"] == BBG_P1_COUPON_PCT
    assert row["payment"] == BBG_P1_PAYMENT


def test_period1_coupon_matches_bloomberg(priced):
    assert priced["rate_pct"] == pytest.approx(BBG_P1_COUPON_PCT, abs=COUPON_TOLERANCE_PCT)


def test_period1_payment_matches_bloomberg(priced):
    assert priced["amount"] == pytest.approx(BBG_P1_PAYMENT, abs=PAYMENT_TOLERANCE)
