"""INR (TC5, TC8, TC9), JPY (TC6, TC10), CHF TC2 and market fixings: curve bootstraps,
term-rate and TONA legs, seasoned handling (docs/IRS_OPEN_ITEMS.md OI-10, OI-11,
OI-15, OI-16).

Bloomberg values are validation references only. Pinned residuals are observed values
(14-Oct-2026), not tuned targets.
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
    RESET_DATE_FALLBACK,
    TERM_BENCHMARKS,
    TermRateFixingRequired,
    fallback_rate,
)
from market.curves.irs_fixings import overnight_fixings_applied
from market.curves.irs_market_snapshot import (
    InvalidMarketData,
    parse_market_snapshot,
    resolve_market_environment,
)
from scripts import build_ois_curve_snapshots as curves_generator
from scripts import build_trade_inputs as trades_generator
from scripts.irs_case_audit import load_market_document, read_bloomberg
from scripts.irs_observation_methods import with_method
from services.pricers.irs_valuation import price_irs

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "examples" / "irs"
VALUATION = ql.Date(31, 3, 2026)


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _q(value: str) -> ql.Date:
    d = date.fromisoformat(value)
    return ql.Date(d.day, d.month, d.year)


@pytest.fixture(scope="module")
def market():
    return load_market_document()


@pytest.fixture(scope="module")
def environment(market):
    previous = ql.Settings.instance().evaluationDate
    ql.Settings.instance().evaluationDate = VALUATION
    try:
        yield resolve_market_environment(parse_market_snapshot(market)).environment
    finally:
        ql.Settings.instance().evaluationDate = previous


@pytest.fixture(scope="module")
def priced(market):
    before = ql.Settings.instance().evaluationDate
    out = {c: price_irs(_json(EXAMPLES / f"{c.lower()}_trade.json"), market)
           for c in ("TC5", "TC6", "TC8", "TC9", "TC10")}
    assert ql.Settings.instance().evaluationDate == before
    return out


def _bloomberg_rows(case):
    return {(r["leg"], r["pay_date"]): r for r in read_bloomberg(case)["cashflows"]}


# --- generated inputs ---------------------------------------------------------------------


@pytest.mark.parametrize("currency", ["INR", "JPY"])
def test_curve_snapshots_are_the_generator_output(currency):
    """Committed snapshot = fresh bootstrap: structure and text fields exactly, zero rates
    within 1e-12 (the bootstrap differs by ~1e-17 between Windows and Linux)."""
    definition = curves_generator.DEFINITIONS[currency]
    generated = curves_generator.build_document(definition)
    stored = json.loads((ROOT / definition.output).read_text(encoding="utf-8"))
    assert curves_generator.same_document(stored, generated)
    assert curves_generator.ZERO_RATE_TOLERANCE == 1e-12


def test_snapshot_comparison_rejects_real_differences():
    doc = curves_generator.build_document(curves_generator.DEFINITIONS["INR"])
    obs = doc["curves"]["INR-MIBOR-OIS"]["observations"]
    nudged = json.loads(json.dumps(doc))
    nudged["curves"]["INR-MIBOR-OIS"]["observations"][8]["zero_rate"] += 4e-17
    assert curves_generator.same_document(nudged, doc)  # platform noise
    nudged["curves"]["INR-MIBOR-OIS"]["observations"][8]["zero_rate"] += 1e-10
    assert not curves_generator.same_document(nudged, doc)  # a real change
    renamed = json.loads(json.dumps(doc))
    renamed["curves"]["INR-MIBOR-OIS"]["observations"][0]["tenor"] = "2M"
    assert not curves_generator.same_document(renamed, doc)
    assert len(obs) > 8


@pytest.mark.validation  # reads Bloomberg fixtures
@pytest.mark.parametrize("case", trades_generator.CASES)
def test_trade_inputs_are_exactly_the_generator_output(case):
    text = trades_generator.to_text(trades_generator.BUILDERS[case]())
    path = EXAMPLES / f"{case.lower()}_trade.json"
    assert path.read_text(encoding="utf-8").replace("\r\n", "\n") == text


def test_tc2_trade_input_uses_the_settled_notional_basis():
    params = _json(EXAMPLES / "tc2_trade.json")["params"]
    assert [p["notional"] for p in params["floating_leg"]["periods"]][:2] == [20000, 17500]


# --- curves ----------------------------------------------------------------------------------


@pytest.mark.validation  # reads Bloomberg fixtures
@pytest.mark.parametrize("currency, cases, tolerance", [
    ("INR", ("TC5", "TC8", "TC9"), 5e-7),
    ("JPY", ("TC6", "TC10"), 1.1e-6),
])
def test_ois_curves_reproduce_bloomberg_trade_discount_factors(environment, currency, cases,
                                                               tolerance):
    curve = environment.discount_curves[currency]
    for case in cases:
        for row in read_bloomberg(case)["cashflows"]:
            assert curve.discount(_q(row["pay_date"])) == pytest.approx(
                row["discount_factor"], abs=tolerance), (case, row["pay_date"])


@pytest.mark.parametrize("currency", ["INR", "JPY"])
def test_production_curve_equals_the_quantlib_bootstrap(environment, currency):
    previous = ql.Settings.instance().evaluationDate
    ql.Settings.instance().evaluationDate = VALUATION
    try:
        bootstrap, _ = curves_generator.bootstrap(curves_generator.DEFINITIONS[currency])
        production = environment.discount_curves[currency]
        for k in range(1, 1800, 7):
            day = VALUATION + k
            assert production.discount(day) == pytest.approx(bootstrap.discount(day), abs=1e-14)
    finally:
        ql.Settings.instance().evaluationDate = previous


@pytest.mark.validation  # reads Bloomberg fixtures
def test_supplied_discount_factors_are_not_the_trade_curve(environment):
    """The supplied DF columns differ from Bloomberg's trade DFs; kept as references only."""
    inr = _json(ROOT / "market_data" / "2026-03-31" / "INR" / "market_data.json")
    supplied_1y = next(o["discount_factor"] for o in inr["observations"]
                       if o["date"] == "2027-03-31")
    bloomberg = _bloomberg_rows("TC9")[("fixed", "2027-03-31")]["discount_factor"]
    assert supplied_1y == 0.940889 and bloomberg == 0.941231
    assert environment.discount_curves["INR"].discount(_q("2027-03-31")) == pytest.approx(
        bloomberg, abs=5e-7)


def test_jpy_390_day_row_is_the_15m_quote():
    rows = curves_generator.source_rows(curves_generator.DEFINITIONS["JPY"])
    assert [r[0] for r in rows if r[3] == date(2027, 4, 25)] == ["15M"]


# --- term-rate legs ------------------------------------------------------------------------


@pytest.mark.validation  # reads Bloomberg fixtures
def test_tc5_first_period_reproduces_bloomberg(priced):
    row = next(r for r in priced["TC5"].cashflows
               if r.leg == "floating" and r.period == 1)
    assert row.amount == pytest.approx(
        _bloomberg_rows("TC5")[("floating", "2027-06-30")]["payment"], abs=0.01)


@pytest.mark.validation  # reads Bloomberg fixtures
def test_tc8_uses_the_historical_fixing_and_matches_the_first_two_periods(priced):
    bbg = _bloomberg_rows("TC8")
    rows = [r for r in priced["TC8"].cashflows if r.leg == "floating"]
    assert rows[0].rate == pytest.approx(0.0536 + 0.005)  # fixing + 50 bp margin
    for r in rows[:2]:
        assert r.amount == pytest.approx(bbg[("floating", r.payment_date.isoformat())]["payment"],
                                         abs=0.01)


@pytest.mark.validation  # reads Bloomberg fixtures
def test_irswof_full_6m_resets_against_bloomberg(priced):
    """Provisional IRSWOF rule: every full 6M reset within 0.3 bp of Bloomberg."""
    for case, full in (("TC8", ("2026-08-28",)),
                       ("TC9", ("2026-09-29", "2027-03-30", "2027-09-29"))):
        bbg = {r["reset_date"]: r["reset_rate_pct"] for r in read_bloomberg(case)["cashflows"]
               if r.get("reset_date")}
        spread = {"TC8": 0.005, "TC9": 0.005}[case]
        for r in priced[case].cashflows:
            if r.leg != "floating":
                continue
            reset = next(x["reset_date"] for x in read_bloomberg(case)["cashflows"]
                         if x["leg"] == "floating" and x["pay_date"] == r.payment_date.isoformat())
            if reset in full:
                assert ((r.rate - spread) * 100 - bbg[reset]) * 100 == pytest.approx(0, abs=0.3)


@pytest.mark.validation  # reads Bloomberg fixtures
def test_irswof_short_reset_periods_are_a_known_difference(priced):
    """Pinned (unresolved, OI-15): Bloomberg is 23-39 bp below the 6M forward for every
    reset period shorter than 6M."""
    cases = {("TC5", "2027-09-30"): 22.8, ("TC8", "2027-03-31"): 23.2,
             ("TC9", "2026-09-30"): 38.8, ("TC9", "2028-05-31"): 28.2}
    for (case, pay), expected_bp in cases.items():
        row = next(r for r in priced[case].cashflows
                   if r.leg == "floating" and r.payment_date.isoformat() == pay)
        b = _bloomberg_rows(case)[("floating", pay)]
        # TC8's rows show the reset rate, not the coupon: add the 50 bp margin.
        bbg = b["rate_pct"] if b["rate_pct"] is not None else b["reset_rate_pct"] + 0.5
        assert (row.rate * 100 - bbg) * 100 == pytest.approx(expected_bp, abs=0.1), (case, pay)


@pytest.mark.validation  # reads Bloomberg fixtures
@pytest.mark.parametrize("case, tolerance_bp", [("TC6", 0.02), ("TC10", 0.005)])
def test_tona_coupons_against_bloomberg(priced, case, tolerance_bp):
    bbg = _bloomberg_rows(case)
    for r in priced[case].cashflows:
        if r.leg == "floating":
            b = bbg[("floating", r.payment_date.isoformat())]["rate_pct"]
            assert (r.rate * 100 - b) * 100 == pytest.approx(0, abs=tolerance_bp)


@pytest.mark.validation  # reads Bloomberg fixtures
@pytest.mark.parametrize("case", ["TC5", "TC6", "TC8", "TC9", "TC10"])
def test_cashflows_close_to_the_engine_npv(priced, case):
    v = priced[case]
    assert sum(r.present_value for r in v.cashflows) == pytest.approx(v.npv, abs=1e-6)
    assert v.fixed_leg_npv + v.floating_leg_npv == pytest.approx(v.npv, abs=1e-6)


# --- TC2 ---------------------------------------------------------------------------------------
# TC2's trade file selects Method A (OI-17). The tests below are about Method B
# (reset_date_fallback, preserved and selectable), so they select it explicitly.


def _tc2_method_b():
    return with_method(_json(EXAMPLES / "tc2_trade.json"), RESET_DATE_FALLBACK)



def test_tc2_needs_saron_fixings_for_period_1(market):
    with pytest.raises(Exception, match="SARON daily fixings"):
        price_irs(_tc2_method_b(), market)


@pytest.mark.validation  # reads Bloomberg fixtures
def test_tc2_fixing_rule_reproduces_bloomberg_effective_reset_dates(environment):
    """Source reset date + 1 EN business day starts the 6M IBOR period: every observable
    window ends on Bloomberg's effective reset date and the rate matches the coupon."""
    source = _json(ROOT / "tests" / "fixtures" / "bloomberg_irs" / "source" / "TC2.json")
    reference = _json(ROOT / "tests" / "fixtures" / "bloomberg_irs" / "references" / "TC2.json")
    oracle = reference["source_oracle_sections"]
    rows = next(oracle[k] for k in ("cashflow_leg_1", "cashflow_leg_2")
                if "Float" in oracle[k]["leg"])["cashflows"]
    uk = ql.UnitedKingdom()
    previous = ql.Settings.instance().evaluationDate
    ql.Settings.instance().evaluationDate = VALUATION
    try:
        for amort, row in list(zip(source["leg_2"]["amortization"], rows))[1:]:
            start = uk.advance(_q(amort["reset_date"]), 1, ql.Days)
            rfr, _, _, end = fallback_rate(TERM_BENCHMARKS["SF0006M"],
                                           environment.forecast_curves["CHF"],
                                           date(start.year(), start.month(), start.dayOfMonth()))
            assert end.isoformat() == row["effective_reset_date"]
            index_pct = (rfr + 0.000741) * 100
            bloomberg_index_pct = row["equivalent_coupon"] - 0.10  # coupon minus 10 bp margin
            assert (index_pct - bloomberg_index_pct) * 100 == pytest.approx(0, abs=0.2)
    finally:
        ql.Settings.instance().evaluationDate = previous


@pytest.mark.validation  # reads Bloomberg fixtures
def test_tc2_period_1_window_and_its_open_one_day_difference(environment):
    """OI-11 / TC2-F2 / R8: under the current rule P1's full observation window is
    29-Jan-2026 -> 30-Jul-2026, while Bloomberg's effective reset date is 29-Jul-2026.
    The difference is recorded, not fixed: this test fails if the convention changes."""
    start = ql.UnitedKingdom().advance(ql.Date(30, 1, 2026), 1, ql.Days)  # reset + 1 EN
    assert start == ql.Date(2, 2, 2026)
    cal, day, synthetic = ql.Switzerland(), ql.Date(29, 1, 2026), {}
    while day < VALUATION:  # SYNTHETIC history so the window can be evaluated
        if cal.isBusinessDay(day):
            synthetic[date(day.year(), day.month(), day.dayOfMonth())] = 0.0
        day += 1
    previous = ql.Settings.instance().evaluationDate
    ql.Settings.instance().evaluationDate = VALUATION
    try:
        with overnight_fixings_applied({"SARON": synthetic}):
            _, ibor_end, obs_start, obs_end = fallback_rate(
                TERM_BENCHMARKS["SF0006M"], environment.forecast_curves["CHF"], date(2026, 2, 2))
    finally:
        ql.Settings.instance().evaluationDate = previous
    assert ibor_end == date(2026, 8, 3)  # Sun 02-Aug rolled Modified Following
    assert (obs_start, obs_end) == (date(2026, 1, 29), date(2026, 7, 30))
    reference = _json(ROOT / "tests" / "fixtures" / "bloomberg_irs" / "references" / "TC2.json")
    first = reference["source_oracle_sections"]["cashflow_leg_2"]["cashflows"][0]
    assert first["effective_reset_date"] == "2026-07-29"  # one Swiss business day earlier


@pytest.mark.parametrize("first, last, missing", [
    ((2026, 1, 29), (2026, 3, 30), None),
    ((2026, 1, 28), (2026, 3, 30), None),  # an extra earlier fixing is ignored
    ((2026, 1, 30), (2026, 3, 30), "January 29th, 2026"),
    ((2026, 1, 29), (2026, 3, 27), "March 30th, 2026"),
])
def test_tc2_historical_saron_range_is_exactly_29_jan_to_30_mar(market, first, last, missing):
    """R3: the production path needs SARON for every Swiss business day 29-Jan-2026 ->
    30-Mar-2026 (SYNTHETIC values, test only); 31-Mar-2026 onwards is projected."""
    doc = copy.deepcopy(market)
    cal, day, end, synthetic = ql.Switzerland(), ql.Date(*reversed(first)), \
        ql.Date(*reversed(last)), {}
    while day <= end:
        if cal.isBusinessDay(day):
            synthetic[day.ISO()] = -0.0005
        day += 1
    doc["fixings"]["SARON"] = {"provenance": "synthetic test values", "values": synthetic}
    if missing is None:
        result = price_irs(_tc2_method_b(), doc)
        assert len([r for r in result.cashflows if r.leg == "floating"]) == 8
    else:
        with pytest.raises(Exception, match=missing):
            price_irs(_tc2_method_b(), doc)
    assert len(ql.Saron().timeSeries()) == 0  # history restored either way


def test_tc2_prices_once_saron_fixings_are_supplied(market):
    """Capability check with SYNTHETIC SARON fixings (test only, never in market data):
    the fallback compounds supplied history and projects the rest."""
    doc = copy.deepcopy(market)
    cal = ql.Switzerland()
    day, synthetic = ql.Date(20, 1, 2026), {}
    while day < VALUATION:
        if cal.isBusinessDay(day):
            synthetic[day.ISO()] = -0.0005
        day += 1
    doc["fixings"]["SARON"] = {"provenance": "synthetic test values", "values": synthetic}
    result = price_irs(_tc2_method_b(), doc)
    assert len([r for r in result.cashflows if r.leg == "floating"]) == 8
    assert len(ql.Saron().timeSeries()) == 0  # history restored


# --- fixings and validation ---------------------------------------------------------------------


def test_fixing_after_the_valuation_date_is_rejected(market):
    doc = copy.deepcopy(market)
    doc["fixings"]["SOFR"]["values"]["2026-04-01"] = 0.037
    with pytest.raises(InvalidMarketData, match="after the valuation date"):
        parse_market_snapshot(doc)


def test_overnight_fixings_are_restored_after_use():
    before = len(ql.Sofr().timeSeries())
    with overnight_fixings_applied({"SOFR": {date(2026, 3, 31): 0.0368}}):
        assert ql.Sofr().fixing(VALUATION) == pytest.approx(0.0368)
    assert len(ql.Sofr().timeSeries()) == before


def test_term_rate_fixing_required_when_window_precedes_valuation(environment):
    previous = ql.Settings.instance().evaluationDate
    ql.Settings.instance().evaluationDate = VALUATION
    try:
        with pytest.raises(TermRateFixingRequired, match="historical fixings are required"):
            fallback_rate(TERM_BENCHMARKS["SF0006M"], environment.forecast_curves["CHF"],
                          date(2026, 2, 2))
    finally:
        ql.Settings.instance().evaluationDate = previous


def test_reset_after_its_sub_period_start_is_rejected():
    params = copy.deepcopy(_json(EXAMPLES / "tc9_trade.json")["params"])
    params["floating_leg"]["periods"][0]["resets"][0]["reset_date"] = "2026-07-01"
    with pytest.raises(InvalidIRSParameters, match="resets fix in advance"):
        FreshOISTrade.from_params(params)
