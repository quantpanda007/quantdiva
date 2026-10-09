"""Standalone, input-driven IRS pricing from a trade file and a market-data file.

Production path under test: services.pricers.irs_valuation.price_irs and the CLI
scripts/price_irs.py, fed only by examples/irs/*.json. Test fixtures are used
here only to check that the example files carry the same inputs as the existing
TC1/TC3 regression route, and the recorded baselines are imported from the
existing tests (not copied).
"""

from __future__ import annotations

import ast
import copy
import json
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import QuantLib as ql
from conftest import load_tc1, load_usd_sofr_zero_fixture, usd_sofr_conventions
from test_tc1_bloomberg_reconciliation import BASELINE as TC1_BASELINE
from test_tc1_bloomberg_reconciliation import BASELINE_TOLERANCE
from test_tc1_pricing_service_e2e import _tc1_params
from test_tc3_pricing_service_e2e import BASELINE as TC3_BASELINE
from test_tc3_pricing_service_e2e import _load as load_tc3
from test_tc3_pricing_service_e2e import tc3_params

from core.exceptions.errors import PricingError
from instruments.rates.irs.cashflows import CashflowExtractionError
from instruments.rates.irs.pricing_instrument import InvalidIRSParameters
from market.curves.irs_market_snapshot import (
    InvalidMarketData,
    MissingCurveAssignment,
    parse_market_snapshot,
    resolve_market_environment,
)
from services.pricers.irs_valuation import (
    InvalidTradeDocument,
    IRSValuationError,
    build_trade,
    price_irs,
)

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "examples" / "irs"
MARKET_FILE = EXAMPLES / "usd_sofr_2026-03-31.json"
TRADE_FILES = {"TC1": EXAMPLES / "tc1_trade.json", "TC3": EXAMPLES / "tc3_trade.json"}
BASELINES = {"TC1": TC1_BASELINE, "TC3": TC3_BASELINE}
CURVE_ID = "USD-SOFR-490"
NPV_TOL = BASELINE_TOLERANCE["npv"]


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def market() -> dict:
    return _read(MARKET_FILE)


@pytest.fixture(scope="module")
def trades() -> dict:
    return {case_id: _read(path) for case_id, path in TRADE_FILES.items()}


@pytest.fixture(scope="module")
def valuations(trades, market) -> dict:
    return {case_id: price_irs(trade, market) for case_id, trade in trades.items()}


def _shifted(market: dict, shift: float, curve_id: str = CURVE_ID) -> dict:
    """Copy of the market document with a parallel zero-rate shift and no DF checks."""
    doc = copy.deepcopy(market)
    for row in doc["curves"][curve_id]["observations"]:
        row["zero_rate"] += shift
        row.pop("discount_factor")
    return doc


# --- 1. standalone pricing reproduces the recorded baselines -------------------------


@pytest.mark.parametrize("case_id", ["TC1", "TC3"])
def test_standalone_files_reproduce_baselines(valuations, case_id):
    valuation, baseline = valuations[case_id], BASELINES[case_id]
    assert valuation.npv == pytest.approx(baseline["npv"], abs=NPV_TOL)
    assert valuation.fixed_leg_npv == pytest.approx(baseline["fixed_leg_npv"], abs=NPV_TOL)
    assert valuation.floating_leg_npv == pytest.approx(baseline["floating_leg_npv"], abs=NPV_TOL)
    for row in valuation.cashflows:
        if row.leg == "floating":
            n = row.period
            assert row.rate * 100 == pytest.approx(
                baseline[f"floating_p{n}_rate_pct"], abs=BASELINE_TOLERANCE["rate_pct"]
            )
            assert row.discount_factor == pytest.approx(
                baseline[f"p{n}_discount_factor"], abs=BASELINE_TOLERANCE["discount_factor"]
            )


def test_production_path_does_not_import_tests_or_fastapi():
    """price_irs, the snapshot module and the CLI import no test code, fixtures or API."""
    for path in (
        ROOT / "services/pricers/irs_valuation.py",
        ROOT / "market/curves/irs_market_snapshot.py",
        ROOT / "scripts/price_irs.py",
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
        roots = {"tests", "conftest", "api", "fastapi"}
        forbidden = [m for m in modules if m.split(".")[0] in roots or m.startswith("test_")]
        assert not forbidden, f"{path.name} imports {forbidden}"


# --- input files carry the same inputs as the fixture route ---------------------------


def test_example_trades_equal_fixture_route_params(trades):
    case, source, _ = load_tc1()
    assert trades["TC1"] == {"schema_version": 1, "instrument_type": "ois",
                             "params": _tc1_params(case, source)}
    assert trades["TC3"] == {"schema_version": 1, "instrument_type": "ois",
                             "params": tc3_params(load_tc3("cases"))}


def test_example_market_equals_fixture_curve_and_conventions(market):
    fixture = load_usd_sofr_zero_fixture()
    curve = market["curves"][CURVE_ID]
    assert market["valuation_date"] == curve["reference_date"] == fixture["reference_date"]
    assert (curve["currency"], curve["benchmark"]) == (fixture["currency"], fixture["benchmark"])
    assert len(curve["observations"]) == len(fixture["observations"]) == 20
    for row, source in zip(curve["observations"], fixture["observations"], strict=True):
        assert row["tenor"] == source["inferred_tenor"]
        assert Decimal(str(row["zero_rate"])) == Decimal(str(source["zero_rate_percent"])) / 100
        assert row["discount_factor"] == source["discount_factor"]

    spec = parse_market_snapshot(market).curves[CURVE_ID].conventions
    expected = usd_sofr_conventions()
    assert spec.calendar.name() == expected.calendar.name()
    assert spec.day_counter.name() == expected.day_counter.name()
    for field in ("spot_lag_days", "business_day_convention", "end_of_month", "compounding",
                  "interpolation", "front_extrapolation", "allow_extrapolation",
                  "discount_factor_tolerance"):
        assert getattr(spec, field) == getattr(expected, field), field


# --- 2. market data independent of the trade --------------------------------------------


def test_one_market_file_prices_both_trades(valuations):
    assert {v.discount_curve_id for v in valuations.values()} == {CURVE_ID}
    assert {v.forecast_curve_id for v in valuations.values()} == {CURVE_ID}


def test_changing_only_the_market_changes_the_price(trades, market, valuations):
    trade_before = copy.deepcopy(trades["TC3"])
    shifted = price_irs(trades["TC3"], _shifted(market, 0.0001))
    assert trades["TC3"] == trade_before
    assert shifted.npv != pytest.approx(valuations["TC3"].npv, abs=1.0)


def test_distinct_discount_and_forecast_curves(trades, market, valuations):
    """Discount on a +1bp curve, project on the base curve: projected rates stay at
    the base values while discount factors move."""
    doc = _shifted(market, 0.0)
    doc["curves"]["USD-DISC-UP1"] = _shifted(market, 0.0001)["curves"][CURVE_ID]
    doc["assignments"]["USD"]["discount"] = "USD-DISC-UP1"

    resolved = resolve_market_environment(parse_market_snapshot(doc))
    env = resolved.environment
    assert env.discount_curves["USD"] is resolved.curves["USD-DISC-UP1"].handle
    assert env.forecast_curves["USD"] is resolved.curves[CURVE_ID].handle

    valuation = price_irs(trades["TC3"], doc)
    assert (valuation.discount_curve_id, valuation.forecast_curve_id) == ("USD-DISC-UP1", CURVE_ID)
    base = valuations["TC3"].cashflows
    for row, base_row in zip(valuation.cashflows, base, strict=True):
        assert row.rate == pytest.approx(base_row.rate, abs=1e-12)
        assert row.discount_factor < base_row.discount_factor
    assert valuation.npv != pytest.approx(valuations["TC3"].npv, abs=0.01)


# --- 3. configured engine and discount curve -----------------------------------------


@pytest.mark.parametrize("case_id", ["TC1", "TC3"])
def test_engine_and_discount_curve(valuations, market, case_id):
    valuation = valuations[case_id]
    assert (valuation.model, valuation.engine) == ("analytical", "discounting")
    curve = resolve_market_environment(parse_market_snapshot(market)).curves[CURVE_ID].handle
    previous = ql.Settings.instance().evaluationDate
    try:
        ql.Settings.instance().evaluationDate = ql.Date(31, 3, 2026)
        for row in valuation.cashflows:
            d = row.payment_date
            assert row.discount_factor == curve.discount(ql.Date(d.day, d.month, d.year))
    finally:
        ql.Settings.instance().evaluationDate = previous


# --- 4. auditable cashflows -----------------------------------------------------------


@pytest.mark.parametrize("case_id", ["TC1", "TC3"])
def test_cashflows_reconcile_to_npvs(valuations, case_id):
    valuation = valuations[case_id]
    legs = (("fixed", valuation.fixed_leg_npv), ("floating", valuation.floating_leg_npv))
    for leg, total in legs:
        rows = [row.present_value for row in valuation.cashflows if row.leg == leg]
        assert sum(rows) == pytest.approx(total, abs=1e-9)
    assert sum(row.present_value for row in valuation.cashflows) == pytest.approx(
        valuation.npv, abs=1e-9
    )


def test_contractual_maturity_is_preserved(trades, valuations):
    assert build_trade(trades["TC3"]).maturity() == date(2028, 4, 30)
    assert valuations["TC3"].cashflows[-1].accrual_end == date(2028, 4, 28)


def test_evaluation_date_is_restored(trades, market):
    previous = ql.Settings.instance().evaluationDate
    price_irs(trades["TC1"], market)
    assert ql.Settings.instance().evaluationDate == previous


@pytest.fixture
def sentinel_evaluation_date():
    """Set a recognisable evaluation date and restore the original afterwards."""
    previous = ql.Settings.instance().evaluationDate
    sentinel = ql.Date(1, 1, 2030)
    ql.Settings.instance().evaluationDate = sentinel
    yield sentinel
    ql.Settings.instance().evaluationDate = previous


def test_evaluation_date_restored_when_pricing_fails(trades, market, sentinel_evaluation_date):
    """A curve that ends at 18M (no extrapolation) cannot price TC3: PricingService
    sets the valuation date, fails inside the engine, and price_irs restores it."""
    short = copy.deepcopy(market)
    short["curves"][CURVE_ID]["observations"] = short["curves"][CURVE_ID]["observations"][:15]
    with pytest.raises(PricingError, match="past max curve time"):
        price_irs(trades["TC3"], short)
    assert ql.Settings.instance().evaluationDate == sentinel_evaluation_date


def test_evaluation_date_restored_when_cashflow_extraction_fails(
    trades, market, sentinel_evaluation_date
):
    """A fixed coupon paying on the valuation date passes trade validation (payment
    dates are not checked against accrual ends, OI-8), prices (the engine excludes
    it) and is then refused by the cashflow extractor (OI-10)."""
    trade = _edit(trades["TC1"], ("params", "fixed_leg", "periods", 0, "payment_date"),
                  "2026-03-31")
    with pytest.raises(CashflowExtractionError, match="on or before the valuation date"):
        price_irs(trade, market)
    assert ql.Settings.instance().evaluationDate == sentinel_evaluation_date


def test_evaluation_date_unchanged_when_validation_fails(trades, market,
                                                         sentinel_evaluation_date):
    with pytest.raises(InvalidMarketData):
        price_irs(trades["TC1"], _edit(market, ("schema_version",), 2))
    assert ql.Settings.instance().evaluationDate == sentinel_evaluation_date


# --- 6. invalid or missing market data fails; no fallback ---------------------------------


def _edit(doc: dict, path: tuple, value=None, delete: bool = False) -> dict:
    doc = copy.deepcopy(doc)
    target = doc
    for key in path[:-1]:
        target = target[key]
    if delete:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return doc


C = ("curves", CURVE_ID)


@pytest.mark.parametrize(
    "path, value, delete, error, message",
    [
        (("assignments", "USD"), None, True, InvalidMarketData, "at least one currency"),
        (("assignments", "USD", "forecast"), "USD-NONE", False, InvalidMarketData, "unknown curve"),
        (("assignments", "USD", "discount"), None, True, InvalidMarketData, "missing required"),
        (C + ("reference_date",), "2026-04-01", False, InvalidMarketData, "does not match"),
        (C + ("conventions", "calendar"), "US-GOV", False, InvalidMarketData, "calendar"),
        (C + ("conventions", "calendar"), "FD", False, InvalidMarketData, "calendar"),
        (C + ("conventions", "day_count"), "ACT/ACT", False, InvalidMarketData, "day_count"),
        (C + ("conventions", "interpolation"), "cubic", False, InvalidMarketData, "interpolation"),
        (C + ("conventions", "spot_lag_days"), True, False, InvalidMarketData, "integer"),
        (C + ("conventions", "allow_extrapolation"), None, True, InvalidMarketData, "missing"),
        (C + ("observations",), [], False, InvalidMarketData, "non-empty"),
        (C + ("observations", 0, "zero_rate"), 3.70182, False, InvalidMarketData, "percentage"),
        (C + ("observations", 0, "discount_factor"), 0.99, False, InvalidMarketData,
         "contradict"),
        (C + ("observations", 0, "tenor"), "1X", False, InvalidMarketData, "tenor"),
        (("extra",), 1, False, InvalidMarketData, "unknown keys"),
        (("schema_version",), 2, False, InvalidMarketData, "schema_version"),
        (("schema_version",), True, False, InvalidMarketData, "schema_version"),
        (("schema_version",), 1.0, False, InvalidMarketData, "schema_version"),
        (("schema_version",), "1", False, InvalidMarketData, "schema_version"),
        (C + ("observations", 0, "discount_factor"), None, False, InvalidMarketData,
         r"observations\[0\]\.discount_factor: must be a number"),
    ],
)
def test_invalid_market_data_fails(trades, market, path, value, delete, error, message):
    with pytest.raises(error, match=message):
        price_irs(trades["TC1"], _edit(market, path, value, delete))


def test_no_curve_for_trade_currency_fails_without_fallback(trades, market):
    doc = copy.deepcopy(market)
    eur = doc["curves"][CURVE_ID] | {"currency": "EUR"}
    doc["curves"] = {"EUR-CURVE": eur}
    doc["assignments"] = {"EUR": {"discount": "EUR-CURVE", "forecast": "EUR-CURVE"}}
    resolved = resolve_market_environment(parse_market_snapshot(doc))
    assert "USD" not in resolved.environment.discount_curves
    with pytest.raises(MissingCurveAssignment, match="no curve assignment for USD"):
        price_irs(trades["TC1"], doc)


@pytest.mark.parametrize("duplicate", ["usd", "Usd"])
def test_case_insensitive_duplicate_assignments_are_rejected(market, duplicate):
    doc = copy.deepcopy(market)
    doc["assignments"][duplicate] = dict(doc["assignments"]["USD"])
    with pytest.raises(InvalidMarketData, match="both name USD; each currency may be assigned"):
        parse_market_snapshot(doc)


def test_discount_factor_key_is_optional_but_not_nullable(market):
    """Omitting discount_factor skips the check; supplying null is an error."""
    omitted = copy.deepcopy(market)
    omitted["curves"][CURVE_ID]["observations"][0].pop("discount_factor")
    spec = parse_market_snapshot(omitted).curves[CURVE_ID]
    assert spec.market_data.observations[0].discount_factor is None
    assert spec.market_data.observations[1].discount_factor is not None


def test_assignment_to_another_currency_curve_fails(market):
    doc = copy.deepcopy(market)
    doc["curves"]["EUR-CURVE"] = doc["curves"][CURVE_ID] | {"currency": "EUR"}
    doc["assignments"]["USD"]["forecast"] = "EUR-CURVE"
    with pytest.raises(InvalidMarketData, match="is a EUR curve, not USD"):
        parse_market_snapshot(doc)


def test_benchmark_linkage_is_enforced(trades, market):
    doc = _edit(market, C + ("benchmark",), "TERM-SOFR")
    with pytest.raises(IRSValuationError, match="must be projected on a 'SOFR' curve"):
        price_irs(trades["TC1"], doc)
    trade = _edit(trades["TC1"], ("params", "floating_leg", "benchmark"), "USD-LIBOR")
    with pytest.raises(IRSValuationError, match="no curve-benchmark mapping"):
        price_irs(trade, market)


def test_valuation_date_mismatch_fails(trades, market):
    doc = _edit(market, ("valuation_date",), "2026-04-01")
    doc["curves"][CURVE_ID]["reference_date"] = "2026-04-01"
    for row in doc["curves"][CURVE_ID]["observations"]:
        row.pop("discount_factor")
    with pytest.raises(IRSValuationError, match="valuation_date 2026-03-31 does not match"):
        price_irs(trades["TC1"], doc)


@pytest.mark.parametrize(
    "path, value, delete, error",
    [
        (("instrument_type",), "irs", False, InvalidTradeDocument),
        (("params",), None, True, InvalidTradeDocument),
        (("schema_version",), 2, False, InvalidTradeDocument),
        (("schema_version",), True, False, InvalidTradeDocument),
        (("schema_version",), 1.0, False, InvalidTradeDocument),
        (("schema_version",), "1", False, InvalidTradeDocument),
        (("params", "fixed_leg", "fixed_rate"), 5.0, False, InvalidIRSParameters),
        (("params", "maturity_date"), "2027-12-01", False, InvalidIRSParameters),
    ],
)
def test_invalid_trade_document_fails(trades, market, path, value, delete, error):
    with pytest.raises(error):
        price_irs(_edit(trades["TC1"], path, value, delete), market)


# --- 7. command line ------------------------------------------------------------------


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "price_irs.py"), *args],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )


@pytest.mark.parametrize("case_id, trade_id", [("TC1", "SLLSL9RR"), ("TC3", "SLLSL90")])
def test_cli_prices_from_files(tmp_path, valuations, case_id, trade_id):
    output = tmp_path / "result.json"
    run = _cli("--trade", str(TRADE_FILES[case_id]), "--market", str(MARKET_FILE),
               "--output", str(output))
    assert run.returncode == 0, run.stderr
    assert f"Trade {trade_id} (ois, USD)" in run.stdout
    assert f"{valuations[case_id].npv:,.6f}" in run.stdout
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["trade_id"] == trade_id
    assert result["npv"] == pytest.approx(valuations[case_id].npv, abs=1e-12)
    assert len(result["cashflows"]) == len(valuations[case_id].cashflows)


def test_cli_does_not_load_fastapi_or_tests():
    code = (
        "import runpy, sys; sys.argv = ['price_irs.py', '--trade', r'%s', '--market', r'%s']\n"
        "try:\n    runpy.run_path(r'%s', run_name='__main__')\nexcept SystemExit as e:\n"
        "    assert e.code == 0, e.code\n"
        "bad = [m for m in sys.modules if m.split('.')[0] in ('fastapi', 'api', 'conftest')\n"
        "       or m.startswith('test_')]\n"
        "assert not bad, bad\nprint('CLEAN')"
    ) % (TRADE_FILES["TC1"], MARKET_FILE, ROOT / "scripts" / "price_irs.py")
    run = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                         timeout=120)
    assert run.returncode == 0, run.stderr
    assert "CLEAN" in run.stdout


def test_cli_rejects_bad_inputs(tmp_path, market):
    missing = _cli("--trade", str(TRADE_FILES["TC1"]), "--market", str(tmp_path / "none.json"))
    assert missing.returncode == 2 and "cannot read market data file" in missing.stderr

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    bad_json = _cli("--trade", str(TRADE_FILES["TC1"]), "--market", str(broken))
    assert bad_json.returncode == 2 and "is not valid JSON" in bad_json.stderr

    no_usd = tmp_path / "no_usd.json"
    doc = copy.deepcopy(market)
    doc["curves"] = {"EUR-CURVE": doc["curves"][CURVE_ID] | {"currency": "EUR"}}
    doc["assignments"] = {"EUR": {"discount": "EUR-CURVE", "forecast": "EUR-CURVE"}}
    no_usd.write_text(json.dumps(doc), encoding="utf-8")
    unassigned = _cli("--trade", str(TRADE_FILES["TC1"]), "--market", str(no_usd))
    assert unassigned.returncode == 2 and "no curve assignment for USD" in unassigned.stderr
