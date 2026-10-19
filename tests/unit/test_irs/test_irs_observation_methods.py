"""SARON observation-date methods for SF0006M fallback legs (OI-17).

Method A (``contractual_accrual``): SARON over each contractual accrual sub-period, no
observation shift. TC2's PROVISIONAL operational default (14-Oct-2026); no shift is an
operational assumption because the trade data has none; not SME-confirmed.
Method B (``reset_date_fallback``): the previous behaviour, preserved unchanged; the default
when a trade does not set the key (TC7 and every other trade).

Values pinned here are QuantLib 1.43 observations of the production path. They are not
Bloomberg reconciliations and nothing is tuned to Bloomberg: TC2 under Method A differs from
Bloomberg's NPV by +5.537 (TC2-F3), and that difference must stay visible.
"""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import pytest
import QuantLib as ql

from instruments.rates.irs.pricing_instrument import FreshOISTrade, InvalidIRSParameters
from instruments.rates.irs.term_rate_leg import (
    CONTRACTUAL_ACCRUAL,
    CONTRACTUAL_ACCRUAL_SHIFT_DAYS,
    DEFAULT_OBSERVATION_METHOD,
    RESET_DATE_FALLBACK,
)
from scripts import irs_observation_methods as methods
from scripts.irs_case_audit import load_market_document
from services.pricers.irs_valuation import price_irs

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "examples" / "irs"
BLOOMBERG_TC2_NPV = -158.91

# Production observations, QuantLib 1.43 (not Bloomberg targets).
TC2_METHOD_A_NPV = -153.37323685
TC2_METHOD_A_FLOATING = 67.22942893
TC2_FIXED = -220.60266578
TC7_NPV = -388.375203074  # Method B by default: must not move

TC2_ACCRUALS = [
    ("2026-04-30", "2026-07-31"), ("2026-07-31", "2026-10-30"), ("2026-10-30", "2027-01-29"),
    ("2027-01-29", "2027-04-30"), ("2027-04-30", "2027-07-30"), ("2027-07-30", "2027-10-29"),
    ("2027-10-29", "2028-01-31"), ("2028-01-31", "2028-02-29"),
]
# Method B windows (reset + 1 EN bd, 6M Modified Following, - 2 Swiss bd); P1 needs fixings.
TC2_METHOD_B_WINDOWS = [
    None,
    "2026-04-28 -> 2026-10-28", "2026-07-27 -> 2027-01-27", "2026-10-28 -> 2027-04-28",
    "2027-01-27 -> 2027-07-27", "2027-04-27 -> 2027-10-27", "2027-07-27 -> 2028-01-27",
    "2027-08-27 -> 2028-02-25",
]


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def market():
    return load_market_document()


@pytest.fixture(scope="module")
def comparison(market):
    return methods.compare("TC2", market)


def _tc2(method=None):
    doc = _json(EXAMPLES / "tc2_trade.json")
    return doc if method is None else methods.with_method(doc, method)


# --- configuration ---------------------------------------------------------------------------


def test_tc2_is_configured_with_method_a_and_the_default_is_method_b():
    assert _tc2()["params"]["floating_leg"]["term_rate"]["observation_dates"] == \
        CONTRACTUAL_ACCRUAL
    assert DEFAULT_OBSERVATION_METHOD == RESET_DATE_FALLBACK
    assert CONTRACTUAL_ACCRUAL_SHIFT_DAYS == 0  # operational assumption, OI-17
    tc7 = _json(EXAMPLES / "tc7_trade.json")
    assert "observation_dates" not in tc7["params"]["floating_leg"]["term_rate"]
    assert FreshOISTrade.from_params(tc7["params"]).floating_term_rate.observation_method == \
        RESET_DATE_FALLBACK


def test_tc7_is_unchanged_under_the_default_method(market):
    assert price_irs(_json(EXAMPLES / "tc7_trade.json"), market).npv == \
        pytest.approx(TC7_NPV, abs=1e-6)


def test_unknown_method_is_rejected():
    doc = _tc2()
    doc["params"]["floating_leg"]["term_rate"]["observation_dates"] = "accrual"
    with pytest.raises(InvalidIRSParameters, match="observation_dates"):
        FreshOISTrade.from_params(doc["params"])


def test_method_a_is_rejected_for_a_projected_term_benchmark():
    doc = _json(EXAMPLES / "tc8_trade.json")  # IRSWOF
    doc["params"]["floating_leg"]["term_rate"]["observation_dates"] = CONTRACTUAL_ACCRUAL
    with pytest.raises(InvalidIRSParameters, match="RFR-fallback benchmarks only"):
        FreshOISTrade.from_params(doc["params"])


# --- observation dates -----------------------------------------------------------------------


def test_tc2_p1_window_under_each_method(comparison):
    p1 = comparison["periods"][0]
    assert p1["accrual"] == "2026-04-30 -> 2026-07-31" and p1["reset_date"] == "2026-01-30"
    assert p1["a_observation"] == "2026-04-30 -> 2026-07-31"  # contractual dates, no shift
    assert p1["b_observation"] == "needs SARON 2026-01-29 -> 2026-03-30"
    assert p1["bloomberg_effective_reset_date"] == "2026-07-29"
    b1 = comparison["methods"][RESET_DATE_FALLBACK]["periods"][0]
    assert b1["computable"] is False and "SARON 2026-01-29 onwards" in b1["reason"]


def test_all_tc2_periods_under_both_methods(comparison):
    a_rows = comparison["methods"][CONTRACTUAL_ACCRUAL]["periods"]
    assert [(r["accrual_start"], r["accrual_end"]) for r in a_rows] == TC2_ACCRUALS
    for r in a_rows:  # Method A: window = contractual sub-period, reset date not used
        assert r["computable"]
        assert (r["observation_start"], r["observation_end"]) == (r["accrual_start"],
                                                                  r["accrual_end"])
        assert r["ibor_period"] == "-"
    for c, expected in zip(comparison["periods"], TC2_METHOD_B_WINDOWS):
        if expected is not None:
            assert c["b_observation"] == expected
            assert c["b_end_matches_bloomberg"]  # P2-P8
    assert not comparison["periods"][0]["b_end_matches_bloomberg"]  # P1: R8, kept visible
    assert not any(c["a_end_matches_bloomberg"] for c in comparison["periods"])


# --- rates, cashflows and NPV ----------------------------------------------------------------


def test_method_a_prices_tc2_and_its_bloomberg_difference_stays_visible(comparison):
    a = comparison["methods"][CONTRACTUAL_ACCRUAL]
    assert a["npv"] == pytest.approx(TC2_METHOD_A_NPV, abs=1e-6)
    assert a["floating_leg_npv"] == pytest.approx(TC2_METHOD_A_FLOATING, abs=1e-6)
    assert a["fixed_leg_npv"] == pytest.approx(TC2_FIXED, abs=1e-6)
    assert comparison["bloomberg"]["npv"] == BLOOMBERG_TC2_NPV
    assert comparison["npv_vs_bloomberg"][CONTRACTUAL_ACCRUAL] == pytest.approx(5.5368, abs=1e-4)


def test_method_a_period_amounts_are_the_production_cashflows(comparison):
    for row in comparison["methods"][CONTRACTUAL_ACCRUAL]["periods"]:
        assert row["amount"] == pytest.approx(row["production_amount"], abs=1e-9)


def test_differences_between_the_methods(comparison):
    diffs = [c["a_minus_b_coupon_bp"] for c in comparison["periods"]]
    assert diffs[0] is None  # Method B P1 not computable
    assert [round(d, 2) for d in diffs[1:]] == [4.09, 7.05, 2.80, 2.36, 0.78, -5.49, -2.76]
    b_vs_bbg = [(c["b_coupon_pct"] - c["bloomberg_coupon_pct"]) * 100
                for c in comparison["periods"][1:]]
    assert max(abs(d) for d in b_vs_bbg) < 0.15  # Method B reproduces P2-P8 coupons
    a_vs_bbg = [(c["a_coupon_pct"] - c["bloomberg_coupon_pct"]) * 100
                for c in comparison["periods"]]
    assert min(a_vs_bbg) == pytest.approx(-5.51, abs=0.01)
    assert max(a_vs_bbg) == pytest.approx(6.92, abs=0.01)
    t = comparison["common_period_totals"]
    assert t["common_periods"] == [2, 3, 4, 5, 6, 7, 8]
    assert t["a_floating_pv_common"] == pytest.approx(60.3475, abs=1e-4)
    assert t["b_floating_pv_common"] == pytest.approx(55.0119, abs=1e-4)
    assert t["a_minus_b_floating_pv_common"] == pytest.approx(5.3356, abs=1e-4)
    assert t["bloomberg_floating_pv_common"] == pytest.approx(55.18, abs=1e-9)


# --- historical fixings ----------------------------------------------------------------------


def test_method_b_still_needs_the_historical_saron_fixings(market, comparison):
    with pytest.raises(Exception, match="SARON 2026-01-29 onwards"):
        price_irs(_tc2(RESET_DATE_FALLBACK), market)
    b = comparison["methods"][RESET_DATE_FALLBACK]
    assert b["npv"] is None and "historical fixings are required" in b["reason"]
    assert comparison["npv_vs_bloomberg"][RESET_DATE_FALLBACK] is None


def test_method_a_needs_no_historical_fixings(market):
    doc = copy.deepcopy(market)
    doc["fixings"].pop("SARON", None)
    assert price_irs(_tc2(CONTRACTUAL_ACCRUAL), doc).npv == pytest.approx(TC2_METHOD_A_NPV,
                                                                           abs=1e-6)
    first_observation = date(2026, 4, 30)
    assert first_observation > date(2026, 3, 31)


def test_method_b_with_synthetic_fixings_is_a_capability_check_only(market):
    """SYNTHETIC SARON values (test only, never market data, never a validation claim):
    Method B prices once P1's history exists, and differs from Method A."""
    doc = copy.deepcopy(market)
    cal, day, synthetic = ql.Switzerland(), ql.Date(29, 1, 2026), {}
    while day < ql.Date(31, 3, 2026):
        if cal.isBusinessDay(day):
            synthetic[day.ISO()] = -0.0005
        day += 1
    doc["fixings"]["SARON"] = {"provenance": "synthetic test values", "values": synthetic}
    b = price_irs(_tc2(RESET_DATE_FALLBACK), doc)
    a = price_irs(_tc2(CONTRACTUAL_ACCRUAL), doc)
    assert a.npv == pytest.approx(TC2_METHOD_A_NPV, abs=1e-6)  # A does not use them
    assert abs(b.npv - a.npv) > 1.0
    assert len(ql.Saron().timeSeries()) == 0  # history restored


def test_comparison_markdown_labels_the_methods(comparison):
    text = "\n".join(methods.to_markdown(comparison))
    assert "Method A (contractual_accrual, provisional default)" in text
    assert "operational assumption" in text and "Not SME-confirmed" in text
    assert "not computable" in text and "R3" in text and "R9" in text and "-158.91" in text
