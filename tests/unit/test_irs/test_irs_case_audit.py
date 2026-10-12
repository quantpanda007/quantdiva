"""Tests for scripts/irs_case_audit.py: classification, results and output of the
ten-case Bloomberg audit.

Expected TC1/TC3 values come from the existing baselines and known-difference
tables (imported here, in the tests only; the audit script itself never imports
test modules). TC4 values are an observed QuantLib 1.43 engine result kept as a
regression pin; they are not Bloomberg reconciliation targets.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import QuantLib as ql
import test_tc1_bloomberg_reconciliation as tc1_reconciliation
from test_tc1_bloomberg_reconciliation import BASELINE as TC1_BASELINE
from test_tc1_bloomberg_reconciliation import KNOWN_DIFFERENCES as TC1_KNOWN
from test_tc3_pricing_service_e2e import BASELINE as TC3_BASELINE
from test_tc3_pricing_service_e2e import KNOWN_DIFFERENCES as TC3_KNOWN
from test_tc3_pricing_service_e2e import tc3_params

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "irs_case_audit.py"
MODULE = "scripts.irs_case_audit"
MARKET_DATA = ROOT / "market_data" / "2026-03-31"
WATCHED = [ROOT / "tests" / "fixtures" / "bloomberg_irs", ROOT / "examples" / "irs", MARKET_DATA]

# Observed QuantLib 1.43 engine result for TC4 (partially audited), kept only as a
# regression pin so that an engine change is noticed. NOT a Bloomberg
# reconciliation target: TC4 is not reconciled to Bloomberg.
TC4_QL143_ENGINE_OBSERVATION = {"npv": -4648.43988008, "fixed_leg_npv": -22362.4881479,
                                "floating_leg_npv": 17714.0482678}

EXPECTED_BLOCKERS = {
    "TC2": {"NO_CURVE_ASSIGNMENT", "UNSUPPORTED_BENCHMARK", "UNSUPPORTED_FLOATING_LEG",
            "UNSUPPORTED_CALENDAR"},
    "TC5": {"NO_CURVE_ASSIGNMENT", "UNSUPPORTED_BENCHMARK", "UNSUPPORTED_FLOATING_LEG",
            "UNSUPPORTED_CALENDAR"},
    "TC6": {"NO_CURVE_ASSIGNMENT", "UNSUPPORTED_BENCHMARK", "UNSUPPORTED_CALENDAR"},
    "TC7": {"NO_CURVE_ASSIGNMENT", "UNSUPPORTED_BENCHMARK", "UNSUPPORTED_FLOATING_LEG",
            "UNSUPPORTED_CALENDAR"},
    "TC8": {"NO_CURVE_ASSIGNMENT", "UNSUPPORTED_BENCHMARK", "UNSUPPORTED_FLOATING_LEG",
            "UNSUPPORTED_CALENDAR", "NEEDS_FIXINGS"},
    "TC9": {"NO_CURVE_ASSIGNMENT", "UNSUPPORTED_BENCHMARK", "UNSUPPORTED_FLOATING_LEG",
            "UNSUPPORTED_CALENDAR"},
    "TC10": {"NO_CURVE_ASSIGNMENT", "UNSUPPORTED_BENCHMARK", "UNSUPPORTED_CALENDAR"},
}


def _digest() -> str:
    h = hashlib.sha256()
    for base in WATCHED:
        if base.exists():
            for path in sorted(p for p in base.rglob("*") if p.is_file()):
                h.update(path.relative_to(ROOT).as_posix().encode())
                h.update(path.read_bytes())
    return h.hexdigest()


@pytest.fixture(scope="module")
def module():
    return importlib.import_module(MODULE)


@pytest.fixture(scope="module")
def run(module):
    before = {"digest": _digest(), "evaluation_date": ql.Settings.instance().evaluationDate}
    result = module.run_audit()
    after = {"digest": _digest(), "evaluation_date": ql.Settings.instance().evaluationDate,
             "sofr_fixings": len(ql.Sofr().timeSeries())}
    return {"result": result, "before": before, "after": after}


@pytest.fixture(scope="module")
def result(run):
    return run["result"]


@pytest.fixture(scope="module")
def cases(result):
    return {c["case_id"]: c for c in result["cases"]}


# --- classification ----------------------------------------------------------------


def test_all_ten_cases_are_classified(result):
    assert [c["case_id"] for c in result["cases"]] == [f"TC{i}" for i in range(1, 11)]
    assert result["summary"] == {
        "priced": ["TC1", "TC3"],
        "partially_audited": ["TC4"],
        "blocked": ["TC2", "TC5", "TC6", "TC7", "TC8", "TC9", "TC10"],
        "error": [],
    }
    assert all(c["error"] is None for c in result["cases"])


@pytest.mark.parametrize("case_id", sorted(EXPECTED_BLOCKERS))
def test_blocked_cases_report_exact_blockers_and_are_not_priced(cases, case_id):
    case = cases[case_id]
    codes = {b["code"] for b in case["blockers"]}
    market_code = ("MARKET_DATA_NOT_CURVE_READY"
                   if (MARKET_DATA / case["currency"] / "market_data.json").exists()
                   else "NO_MARKET_DATA")
    assert codes == EXPECTED_BLOCKERS[case_id] | {market_code}
    assert case["status"] == "blocked"
    for key in ("trade_input", "pricing", "differences", "cashflows"):
        assert case[key] is None
    assert all(b["detail"] for b in case["blockers"])


@pytest.mark.parametrize("case_id", ["TC1", "TC3", "TC4"])
def test_supported_cases_have_no_blockers(cases, case_id):
    assert cases[case_id]["blockers"] == []
    assert cases[case_id]["market_data"]["snapshot_assignment"] == {
        "discount": "USD-SOFR-490", "forecast": "USD-SOFR-490"}


# --- priced cases: TC1, TC3 ------------------------------------------------------------


@pytest.mark.parametrize("case_id, baseline, known", [("TC1", TC1_BASELINE, TC1_KNOWN),
                                                      ("TC3", TC3_BASELINE, TC3_KNOWN)])
def test_priced_cases_match_baselines_and_known_differences(cases, case_id, baseline, known):
    case = cases[case_id]
    assert case["status"] == "priced" and case["pricing"]["path"] == "price_irs"
    for metric in ("npv", "fixed_leg_npv", "floating_leg_npv"):
        assert case["pricing"][metric] == pytest.approx(baseline[metric], abs=1e-6)
        expected, tolerance = known[metric]
        assert case["differences"][metric] == pytest.approx(expected, abs=tolerance)


@pytest.mark.parametrize("case_id, rows", [("TC1", 4), ("TC3", 8)])
def test_priced_cashflows_reconcile_and_tag_open_items(cases, case_id, rows):
    case = cases[case_id]
    assert len(case["cashflows"]) == rows
    for leg in ("fixed", "floating"):
        total = sum(r["present_value"] for r in case["cashflows"] if r["leg"] == leg)
        assert total == pytest.approx(case["pricing"][f"{leg}_leg_npv"], abs=1e-6)
    for row in case["cashflows"]:
        assert row["bloomberg"] is not None
        # Only the documented OI-1 / OI-7 dates fall outside display tolerance.
        assert row["within_display_tolerance"] == (row["open_item"] is None)


# --- partially audited: TC4 ---------------------------------------------------------------


def test_tc4_reports_engine_result_and_extraction_limitation_separately(cases):
    case = cases["TC4"]
    assert case["status"] == "partially_audited"
    assert case["cashflows"] is None  # no cashflow table is produced or rebuilt
    (limitation,) = case["limitations"]
    assert limitation["code"] == "CASHFLOW_EXTRACTION_REFUSED"
    assert "pays on 2026-03-31, on or before the valuation date" in limitation["detail"]
    assert "production engine" in case["pricing"]["path"]
    assert (case["pricing"]["engine"], case["pricing"]["model"]) == ("discounting", "analytical")
    for metric, value in TC4_QL143_ENGINE_OBSERVATION.items():
        assert case["pricing"][metric] == pytest.approx(value, abs=1e-6)
    legs = case["pricing"]["fixed_leg_npv"] + case["pricing"]["floating_leg_npv"]
    assert legs == pytest.approx(case["pricing"]["npv"], abs=1e-6)
    assert case["features"]["payment_on_valuation_date"] is True


def test_tc4_latest_index_is_reported_as_a_hypothesis_only(cases):
    case = cases["TC4"]
    (h,) = case["hypotheses"]
    assert h["status"] == "tested" and h["label"].startswith("hypothesis")
    assert h["latest_index_pct"] == 3.68 and h["period"] == 2
    assert h["residual_bp_forecast"] == pytest.approx(-0.0319, abs=5e-4)
    assert abs(h["residual_bp_with_latest_index"]) < 0.001
    assert abs(h["residual_payment_with_latest_index"]) < 0.01
    assert h["fixings_removed"] is True
    # The hypothesis does not feed the reported price.
    assert case["pricing"]["npv"] == pytest.approx(TC4_QL143_ENGINE_OBSERVATION["npv"], abs=1e-6)


# --- observations and evidence -----------------------------------------------------------


def test_data_quality_observations(cases):
    assert any("not on the payment scale" in o for o in cases["TC1"]["observations"])
    assert any("differs from fixed + floating" in o for o in cases["TC7"]["observations"])
    for case_id in ("TC4", "TC10"):
        assert any("latest_index" in o and "unconfirmed" in o
                   for o in cases[case_id]["observations"])
    assert cases["TC3"]["observations"] == []


def test_usd_discount_factor_evidence(result):
    evidence = result["evidence"]["usd_discount_factors"]
    assert len(evidence) == 8
    outside = {e["payment_date"]: e["open_item"] for e in evidence
               if not e["within_display_tolerance"]}
    assert outside == {"2027-11-30": "OI-1", "2028-04-28": "OI-7"}
    assert all(e["bloomberg_values_agree"] for e in evidence)


def test_market_data_cross_check(result):
    checks = result["evidence"]["market_data_display_date_cross_check"]
    if not (MARKET_DATA / "INR" / "market_data.json").exists():
        pytest.skip("INR market_data file not present")
    inr = [c for c in checks if c["currency"] == "INR"]
    assert {c["case_id"] for c in inr} == {"TC8", "TC9"}
    assert not any(c["agree_within_display_tolerance"] for c in inr)


# --- output and side effects ----------------------------------------------------------


def test_output_is_deterministic_and_json_ready(module, result):
    text = module.to_json(result)
    assert text == module.to_json(module.run_audit())
    parsed = json.loads(text)
    assert parsed["audit_schema_version"] == 1
    assert parsed["valuation_date"] == "2026-03-31"
    assert "timestamp" not in text


def test_audit_has_no_side_effects(run):
    assert run["after"]["digest"] == run["before"]["digest"]  # fixtures and inputs untouched
    assert run["after"]["evaluation_date"] == run["before"]["evaluation_date"]
    assert run["after"]["sofr_fixings"] == 0


def test_summary_text(module, result):
    text = module.format_summary(result)
    for case_id in result["summary"]["blocked"]:
        assert f"{case_id} (" in text
    assert "HYPOTHESIS (Bloomberg applies latest_index" in text
    assert "limitation CASHFLOW_EXTRACTION_REFUSED" in text


# --- inputs and independence from test modules ------------------------------------------


def test_tc4_trade_input_matches_existing_mapper(cases):
    path = ROOT / "examples" / "irs" / "tc4_trade.json"
    case = json.loads((ROOT / "tests" / "fixtures" / "bloomberg_irs" / "cases" / "TC4.json")
                      .read_text(encoding="utf-8"))
    expected = {"schema_version": 1, "instrument_type": "ois", "params": tc3_params(case)}
    assert json.loads(path.read_text(encoding="utf-8")) == expected
    assert cases["TC4"]["trade_input"] == "examples/irs/tc4_trade.json"


def test_audit_tolerances_match_tc1_reconciliation(module):
    for name in ("COUPON_DISPLAY_TOL_PCT", "DF_DISPLAY_TOL", "PAYMENT_TOL"):
        assert getattr(module, name) == getattr(tc1_reconciliation, name), name


def test_script_source_has_no_test_imports_or_sys_path_mutation():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
        elif isinstance(node, ast.Attribute) and node.attr == "path":
            assert not (isinstance(node.value, ast.Name) and node.value.id == "sys"), \
                f"sys.path referenced at line {node.lineno}"
    for name in imported:
        parts = name.split(".")
        assert parts[0] not in {"tests", "conftest", "pytest", "importlib"}, name
        assert not any(p.startswith("test_") for p in parts), name
    assert "tc3_params" not in SCRIPT.read_text(encoding="utf-8")


def test_running_the_audit_loads_no_test_or_api_modules():
    code = (
        "import importlib, json, sys\n"
        "path_before = list(sys.path)\n"
        f"m = importlib.import_module({MODULE!r})\n"
        "m.run_audit()\n"
        "bad = sorted(n for n in sys.modules if n.split('.')[0] in "
        "{'pytest', '_pytest', 'tests', 'conftest', 'api'} "
        "or any(p.startswith('test_') for p in n.split('.')))\n"
        "print(json.dumps({'bad': bad, 'sys_path_changed': sys.path != path_before}))\n"
    )
    run = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                         text=True, timeout=300)
    assert run.returncode == 0, run.stderr
    report = json.loads(run.stdout.strip().splitlines()[-1])
    assert report == {"bad": [], "sys_path_changed": False}


# --- unexpected per-case failures and shared state ----------------------------------------

TC3_TRADE_ID = "SLLSL90"


def test_unexpected_case_failure_is_recorded_as_error(module, monkeypatch):
    real_price_irs = module.price_irs

    def failing_for_tc3(trade_doc, market_doc):
        if trade_doc["params"]["trade_id"] == TC3_TRADE_ID:
            raise RuntimeError("injected pricing failure")
        return real_price_irs(trade_doc, market_doc)

    monkeypatch.setattr(module, "price_irs", failing_for_tc3)
    result = module.run_audit()
    by_id = {c["case_id"]: c for c in result["cases"]}
    tc3 = by_id["TC3"]
    assert tc3["status"] == "error" and tc3["blockers"] == []  # not a missing-input blocker
    assert tc3["error"] == {"stage": "pricing with price_irs", "type": "RuntimeError",
                            "message": "injected pricing failure"}
    assert tc3["pricing"] is None and tc3["cashflows"] is None
    assert result["summary"]["error"] == ["TC3"]
    assert result["summary"]["priced"] == ["TC1"]
    assert result["summary"]["partially_audited"] == ["TC4"]
    assert by_id["TC1"]["error"] is None and by_id["TC4"]["error"] is None
    assert "ERROR during pricing with price_irs: RuntimeError: injected pricing failure" \
        in module.format_summary(result)
    json.loads(module.to_json(result))

    # The CLI reports case errors through a non-zero exit code.
    monkeypatch.setattr(module, "run_audit", lambda: result)
    assert module.main([]) == 1


@pytest.mark.parametrize("corruption", ["evaluation_date", "fixing"])
def test_shared_state_corruption_aborts_the_audit(module, monkeypatch, corruption):
    original_date = ql.Settings.instance().evaluationDate

    def corrupting(trade_doc, market_doc):
        if corruption == "evaluation_date":
            ql.Settings.instance().evaluationDate = ql.Date(1, 1, 2001)
        else:
            ql.Sofr().addFixing(ql.Date(30, 3, 2026), 0.0368)
        raise RuntimeError("failure after corrupting shared state")

    monkeypatch.setattr(module, "price_irs", corrupting)
    try:
        with pytest.raises(module.SharedStateCorrupted, match="TC1 left QuantLib state changed"):
            module.run_audit()
    finally:
        ql.Settings.instance().evaluationDate = original_date
        ql.Sofr().clearFixings()


def test_cli_stops_with_exit_3_on_shared_state_corruption(module, monkeypatch, capsys):
    def corrupted():
        raise module.SharedStateCorrupted("TC1 left QuantLib state changed")

    monkeypatch.setattr(module, "run_audit", corrupted)
    assert module.main([]) == 3
    assert "audit stopped" in capsys.readouterr().err


# --- --json output protection ---------------------------------------------------------------


def _symlink(link: Path, target: Path, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError) as exc:  # e.g. Windows without symlink privilege
        pytest.skip(f"cannot create symlinks here: {exc}")


@pytest.fixture
def no_audit(module, monkeypatch):
    """A refused path must be rejected before any pricing runs."""

    def must_not_run():
        raise AssertionError("run_audit called for a refused output path")

    monkeypatch.setattr(module, "run_audit", must_not_run)


def _assert_refused(module, capsys, raw: str) -> str:
    assert module.main(["--json", raw]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: output path") or "output directory" in err
    return err


def test_refuses_to_overwrite_existing_file(module, capsys, tmp_path, no_audit):
    existing = tmp_path / "audit.json"
    existing.write_text("keep me", encoding="utf-8")
    assert "already exists" in _assert_refused(module, capsys, str(existing))
    assert existing.read_text(encoding="utf-8") == "keep me"


def test_refuses_existing_directory_and_missing_parent(module, capsys, tmp_path, no_audit):
    assert "already exists" in _assert_refused(module, capsys, str(tmp_path))
    missing = tmp_path / "no_such_dir" / "audit.json"
    assert "does not exist" in _assert_refused(module, capsys, str(missing))
    assert not missing.parent.exists()


@pytest.mark.parametrize("relative", [
    "tests/fixtures/audit.json",
    "tests/fixtures/bloomberg_irs/audit.json",
    "examples/audit.json",
    "examples/irs/audit.json",
    "market_data/audit.json",
    "market_data/2026-03-31/audit.json",
    "scripts/../examples/irs/audit.json",  # alternative spelling
])
def test_refuses_protected_source_directories(module, capsys, monkeypatch, no_audit, relative):
    target = (ROOT / relative).resolve()
    if not target.parent.is_dir():
        pytest.skip(f"{target.parent} not present")
    for raw in (str(ROOT / relative), relative):  # absolute and relative to the repo root
        monkeypatch.chdir(ROOT)
        assert "protected directory" in _assert_refused(module, capsys, raw)
        assert not target.exists()


def test_refuses_existing_source_file_via_alternative_path(module, capsys, monkeypatch,
                                                          no_audit):
    monkeypatch.chdir(ROOT / "scripts")
    before = (ROOT / "examples" / "irs" / "tc1_trade.json").read_bytes()
    _assert_refused(module, capsys, "../examples/irs/tc1_trade.json")
    assert (ROOT / "examples" / "irs" / "tc1_trade.json").read_bytes() == before


def test_refuses_symlink_to_reference_file(module, capsys, tmp_path, no_audit):
    fixture = ROOT / "tests" / "fixtures" / "bloomberg_irs" / "cases" / "TC1.json"
    before = fixture.read_bytes()
    link = tmp_path / "audit.json"
    _symlink(link, fixture)
    assert "symbolic link" in _assert_refused(module, capsys, str(link))
    assert fixture.read_bytes() == before


def test_refuses_dangling_symlink_into_examples(module, capsys, tmp_path, no_audit):
    target = ROOT / "examples" / "irs" / "audit_from_link.json"
    link = tmp_path / "audit.json"
    _symlink(link, target)
    assert "symbolic link" in _assert_refused(module, capsys, str(link))
    assert not target.exists()


def test_refuses_path_through_symlinked_directory(module, capsys, tmp_path, no_audit):
    linked_dir = tmp_path / "linked"
    _symlink(linked_dir, ROOT / "examples", directory=True)
    assert "protected directory" in _assert_refused(
        module, capsys, str(linked_dir / "irs" / "audit.json"))
    assert not (ROOT / "examples" / "irs" / "audit.json").exists()


# --- CLI ------------------------------------------------------------------------------------


def test_cli_writes_identical_json_on_repeated_runs(module, result, tmp_path):
    outputs = []
    for name in ("first.json", "second.json"):
        output = tmp_path / name
        run = subprocess.run([sys.executable, "-m", MODULE, "--json", str(output)], cwd=ROOT,
                             capture_output=True, text=True, timeout=300)
        assert run.returncode == 0, run.stderr
        assert "Priced: TC1, TC3 | partially audited: TC4" in run.stdout
        assert "| error: -" in run.stdout
        outputs.append(output.read_bytes())
    assert outputs[0] == outputs[1]
    assert outputs[0] == module.to_json(result).encode("utf-8")  # same as in-process
    assert json.loads(outputs[0])["summary"]["priced"] == ["TC1", "TC3"]
