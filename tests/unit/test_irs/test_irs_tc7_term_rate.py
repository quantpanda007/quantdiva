"""TC7 (SLLSL9SI, CHF SF0006M): CHF curve 234 snapshot, term-rate fallback leg and
end-to-end pricing through price_irs.

Bloomberg references come from the TC7 fixture (re-export of 14-Oct-2026) and from
the SWPM screenshots of 13-Oct-2026 (Curves tab for curve 234; Resets tab). They
are comparison targets only; nothing here feeds them into pricing, except the
explicit mechanics test, which applies Bloomberg's own reset rates to check the
flat-compounding arithmetic in isolation.

The SF0006M fallback projection is PROVISIONAL (see TERM_BENCHMARKS): its pinned
residuals against the Resets tab document the gap, they are not targets.
"""

from __future__ import annotations

import copy
import json
import math
from datetime import date
from pathlib import Path

import pytest
import QuantLib as ql

from instruments.rates.irs.pricing_instrument import FreshOISTrade, InvalidIRSParameters
from instruments.rates.irs.term_rate_leg import (
    TERM_BENCHMARKS,
    TermRateFixingRequired,
    fallback_rate,
    flat_compounded_amount,
)
from market.curves.irs_market_snapshot import parse_market_snapshot, resolve_market_environment
from scripts import build_chf_curve_snapshot as chf_snapshot
from services.pricers.irs_valuation import build_trade, price_irs
from services.pricers.pricing_service import PricingService

ROOT = Path(__file__).resolve().parents[3]
TRADE = ROOT / "examples" / "irs" / "tc7_trade.json"
SNAPSHOT = ROOT / "market_data" / "2026-03-31" / "CHF" / "chf_saron_2026-03-31.json"
SOURCE = ROOT / "tests" / "fixtures" / "bloomberg_irs" / "source" / "TC7.json"
VALUATION = ql.Date(31, 3, 2026)

# SWPM Curves tab, curve 234 (screenshot): Zero Rate column, percent.
CURVE_234_ZERO_PCT = {"1W": -0.05698, "1M": -0.05584, "6M": -0.02795, "12M": 0.07725,
                      "18M": 0.14799, "2Y": 0.15701, "5Y": 0.31410, "10Y": 0.55674}
# SWPM Resets tab (screenshot): reset date -> reset rate, percent.
RESETS_TAB_PCT = {"2026-08-28": 0.21366, "2027-02-25": 0.33654, "2027-08-27": 0.28763}
# Observed QuantLib 1.43 result with the provisional fallback, pinned so that a change
# is noticed. NOT a Bloomberg target.
# 14-Oct-2026: IBOR period starts 1 EN business day after the reset date (TC2 evidence),
# so the first window starts 01-Sep-2026 (31-Aug-2026 is a UK holiday); was 31-Aug.
TC7_OBSERVED = {"npv": -388.37520, "fixed_leg_npv": -756.37602, "floating_leg_npv": 368.00082}


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def bloomberg():
    trade = _json(SOURCE)["trade"]
    return {"valuation": trade["valuation_results"], "cashflows": trade["cashflows"]}


@pytest.fixture(scope="module")
def priced():
    before = ql.Settings.instance().evaluationDate
    valuation = price_irs(_json(TRADE), _json(SNAPSHOT))
    instrument = build_trade(_json(TRADE))
    environment = resolve_market_environment(parse_market_snapshot(_json(SNAPSHOT))).environment
    try:
        PricingService().price(instrument=instrument, market_env=environment,
                               model_type="analytical", engine_type="discounting")
    finally:
        ql.Settings.instance().evaluationDate = before
    return {"valuation": valuation, "leg": instrument.last_built.receive_leg,
            "eval_before": before, "eval_after": ql.Settings.instance().evaluationDate,
            "saron_fixings": len(ql.Saron().timeSeries())}


# --- CHF curve 234 ---------------------------------------------------------------------------


def test_snapshot_file_is_exactly_the_generator_output():
    assert SNAPSHOT.read_text(encoding="utf-8").replace("\r\n", "\n") == chf_snapshot.to_text(
        chf_snapshot.build_document())


def test_tenors_follow_the_curve_234_term_list():
    tenors = [o["tenor"] for o in _json(SNAPSHOT)["curves"]["CHF-SARON-234"]["observations"]]
    assert tenors == (["1W", "2W"] + [f"{m}M" for m in range(1, 13)] + ["18M"]
                      + [f"{y}Y" for y in range(2, 11)])
    with pytest.raises(ValueError):
        chf_snapshot.tenor_for_offset(45)


def test_curve_reproduces_supplied_dfs_and_bloomberg_zero_rates():
    resolved = resolve_market_environment(parse_market_snapshot(_json(SNAPSHOT)))
    curve = resolved.curves["CHF-SARON-234"]
    # The builder already rejects any supplied DF further than 1e-6 from its pillar.
    zeros = {o.tenor: float(o.zero_rate) * 100 for o in curve.market_data.observations}
    for tenor, expected in CURVE_234_ZERO_PCT.items():
        # Six-decimal DFs limit the derived short-end zeros to about 0.02 bp.
        assert zeros[tenor] == pytest.approx(expected, abs=3e-4), tenor


def test_payment_date_dfs_against_bloomberg(bloomberg, priced):
    rows = {(r.leg, r.payment_date.isoformat()): r for r in priced["valuation"].cashflows}
    for row in bloomberg["cashflows"]["floating_leg"]["cashflows"]:
        ours = rows[("floating", row["pay_date"])].discount_factor
        # 31-Aug-27 agrees to display precision; 31-Jul-28 differs by -2.3e-6 (curve
        # interpolation past the 2Y pillar, same order as TC2's past-18M residuals).
        tolerance = 5e-7 if row["pay_date"] == "2027-08-31" else 3e-6
        assert ours == pytest.approx(row["discount"], abs=tolerance), row["pay_date"]


# --- term-rate mechanics ---------------------------------------------------------------------


def test_flat_compounding_with_bloomberg_reset_rates_reproduces_bloomberg_payments(bloomberg):
    """Mechanics only: Bloomberg's own reset rates in, Bloomberg's payments out."""
    s = 0.002
    p1, _ = flat_compounded_amount(
        52000.0, (RESETS_TAB_PCT["2026-08-28"] / 100, RESETS_TAB_PCT["2027-02-25"] / 100),
        (179 / 360, 186 / 360), s)
    p2, _ = flat_compounded_amount(26000.0, (RESETS_TAB_PCT["2027-08-27"] / 100,), (335 / 360,), s)
    payments = [r["payment"] for r in bloomberg["cashflows"]["floating_leg"]["cashflows"]]
    assert p1 == pytest.approx(payments[0], abs=0.005)
    assert p2 == pytest.approx(payments[1], abs=0.005)


def test_flat_compounding_does_not_compound_the_spread():
    total, parts = flat_compounded_amount(100.0, (0.10, 0.10), (0.5, 0.5), 0.02)
    assert parts == pytest.approx((6.0, 6.0 + 6.0 * 0.10 * 0.5))
    assert total == pytest.approx(12.3)


def test_observation_windows_end_on_bloomberg_effective_reset_dates(bloomberg, priced):
    last_windows = [p.resets[-1].observation_end.isoformat() for p in priced["leg"].period_details]
    expected = [r["effective_reset_date"]
                for r in bloomberg["cashflows"]["floating_leg"]["cashflows"]]
    assert last_windows == expected == ["2027-08-24", "2028-02-25"]


def test_rate_period_starts_one_fixing_day_after_the_reset(priced):
    """28-Aug-2026 + 1 EN business day is 01-Sep-2026 (31-Aug-2026 is a UK holiday)."""
    resets = [r for p in priced["leg"].period_details for r in p.resets]
    assert [r.rate_start.isoformat() for r in resets] == ["2026-09-01", "2027-02-26",
                                                         "2027-08-31"]
    assert resets[0].observation_start.isoformat() == "2026-08-28"
    assert all(r.source == "projected" for r in resets)


def test_provisional_fallback_against_resets_tab(priced):
    resets = [r for p in priced["leg"].period_details for r in p.resets]
    assert [r.reset_date.isoformat() for r in resets] == list(RESETS_TAB_PCT)
    residual_bp = [(r.reset_rate * 100 - RESETS_TAB_PCT[r.reset_date.isoformat()]) * 100
                   for r in resets]
    # Pinned residuals of the PROVISIONAL fallback (0.0741% adjustment): -0.05, -0.05, -0.01 bp
    # (first reset was -0.18 bp before the window-start rule of 14-Oct-2026).
    assert residual_bp == pytest.approx([-0.054, -0.052, -0.014], abs=0.005)
    assert all(r.spread_adjustment == pytest.approx(0.000741) for r in resets)
    assert "PROVISIONAL" in TERM_BENCHMARKS["SF0006M"].status


def test_fallback_window_before_valuation_needs_fixings():
    handle = ql.YieldTermStructureHandle(ql.FlatForward(VALUATION, 0.01, ql.Actual365Fixed()))
    previous = ql.Settings.instance().evaluationDate
    ql.Settings.instance().evaluationDate = VALUATION
    try:
        with pytest.raises(TermRateFixingRequired, match="historical fixings"):
            fallback_rate(TERM_BENCHMARKS["SF0006M"], handle, date(2026, 3, 31))
        rate, *_ = fallback_rate(TERM_BENCHMARKS["SF0006M"], handle, date(2026, 6, 30))
        assert math.isfinite(rate)
    finally:
        ql.Settings.instance().evaluationDate = previous


# --- end-to-end -------------------------------------------------------------------------------


def test_tc7_prices_through_the_production_workflow(priced, bloomberg):
    v = priced["valuation"]
    assert (v.discount_curve_id, v.forecast_curve_id) == ("CHF-SARON-234", "CHF-SARON-234")
    for metric in ("npv", "fixed_leg_npv", "floating_leg_npv"):
        assert getattr(v, metric) == pytest.approx(TC7_OBSERVED[metric], abs=1e-4)
    # Known differences against Bloomberg, explained by the provisional reset rates
    # (floating) and the 31-Jul-28 DF (fixed): not within tolerance, reported as FAIL.
    assert v.npv - bloomberg["valuation"]["npv"] == pytest.approx(-0.315, abs=0.002)
    assert v.fixed_leg_npv - bloomberg["cashflows"]["fixed_leg"]["npv"] == pytest.approx(
        0.004, abs=0.002)
    assert v.floating_leg_npv - bloomberg["cashflows"]["floating_leg"]["npv"] == pytest.approx(
        -0.309, abs=0.002)


def test_cashflow_rows_carry_spread_and_equivalent_coupon(priced, bloomberg):
    floating = [r for r in priced["valuation"].cashflows if r.leg == "floating"]
    assert [r.spread for r in floating] == [0.002, 0.002]
    for row, detail in zip(floating, priced["leg"].period_details):
        assert row.rate == pytest.approx(detail.equivalent_rate)
        assert row.amount == pytest.approx(sum(r.amount for r in detail.resets))
    fixed = [r for r in priced["valuation"].cashflows if r.leg == "fixed"]
    assert [round(r.amount, 2) for r in fixed] == [-520.00, -238.33]  # Bloomberg, exactly


def test_pricing_restores_shared_state(priced):
    assert priced["eval_after"] == priced["eval_before"]
    assert priced["saron_fixings"] == 0


# --- trade validation -------------------------------------------------------------------------


def _params():
    return copy.deepcopy(_json(TRADE)["params"])


def _reject(params, match):
    with pytest.raises(InvalidIRSParameters, match=match):
        FreshOISTrade.from_params(params)


def test_reset_date_must_match_the_fixing_calendar():
    params = _params()
    # 30-Aug-2027 is a Swiss business day but a UK holiday: one EN day back is 27-Aug.
    params["floating_leg"]["periods"][1]["resets"][0]["reset_date"] = "2027-08-30"
    _reject(params, "not a EN business day")


def test_sub_periods_must_be_contiguous():
    params = _params()
    params["floating_leg"]["periods"][0]["resets"][1]["start"] = "2027-03-01"
    params["floating_leg"]["periods"][0]["resets"][1]["reset_date"] = "2027-02-26"
    _reject(params, "contiguously")


@pytest.mark.parametrize("field, value, match", [
    ("leverage", 2.0, "support 1 only"),
    ("benchmark", "SF0003M", "no term-rate definition"),
    ("benchmark_tenor", "3M", "benchmark, not"),
])
def test_unsupported_leg_terms_are_rejected(field, value, match):
    params = _params()
    params["floating_leg"][field] = value
    _reject(params, match)


def test_compounding_none_requires_one_reset_per_period():
    params = _params()
    params["floating_leg"]["term_rate"]["compounding"] = "none"
    _reject(params, "one reset per period")


def test_unknown_keys_and_fixing_calendars_are_rejected():
    params = _params()
    params["floating_leg"]["observation"] = {}
    _reject(params, "unknown keys")
    params = _params()
    params["floating_leg"]["term_rate"]["fixing_calendar"] = "TE"
    _reject(params, "not supported")
