"""Tests for scripts/irs_reconciliation_report.py: case discovery, status classification,
tolerances, cashflow attribution, output schema and error handling.

The report adds no pricing: every Optima number must be the audit's number. Expected
TC1/TC3 outcomes follow from the documented OI-1 / OI-7 discount-factor residuals
(docs/IRS_OPEN_ITEMS.md); they are not tuned targets.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import QuantLib as ql

ROOT = Path(__file__).resolve().parents[3]
MODULE = "scripts.irs_reconciliation_report"
WATCHED = [ROOT / "tests" / "fixtures" / "bloomberg_irs", ROOT / "examples" / "irs",
           ROOT / "market_data" / "2026-03-31"]
CASE_IDS = [f"TC{i}" for i in range(1, 11)]


def _digest() -> str:
    h = hashlib.sha256()
    for base in WATCHED:
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            h.update(path.relative_to(ROOT).as_posix().encode())
            h.update(path.read_bytes())
    return h.hexdigest()


@pytest.fixture(scope="module")
def module():
    return importlib.import_module(MODULE)


@pytest.fixture(scope="module")
def run(module):
    before = _digest()
    eval_date = ql.Settings.instance().evaluationDate
    audit_result = module.audit.run_audit()
    report = module.build_report(audit_result)
    return {"audit": audit_result, "report": report, "digest_before": before,
            "digest_after": _digest(), "eval_before": eval_date,
            "eval_after": ql.Settings.instance().evaluationDate}


@pytest.fixture(scope="module")
def report(run):
    return run["report"]


@pytest.fixture(scope="module")
def cases(report):
    return {c["case_id"]: c for c in report["cases"]}


# --- discovery and classification ----------------------------------------------------------


def test_all_ten_cases_are_reported_in_order(report):
    assert [c["case_id"] for c in report["cases"]] == CASE_IDS


def test_status_counts_cover_every_case(report):
    counts = report["counts"]
    assert set(counts) == {"PASS", "FAIL", "PARTIAL", "BLOCKED", "ERROR"}
    assert sorted(cid for ids in counts.values() for cid in ids) == sorted(CASE_IDS)
    # 14-Oct-2026: INR/JPY curves and legs, seasoned cashflows and market fixings implemented.
    # TC2 priced with Method A since 14-Oct-2026 (provisional default, OI-17).
    assert counts == {"PASS": ["TC4"],
                      "FAIL": ["TC1", "TC2", "TC3", "TC5", "TC6", "TC7", "TC8", "TC9", "TC10"],
                      "PARTIAL": [], "BLOCKED": [], "ERROR": []}


def test_every_status_is_defined(report, module):
    assert set(report["status_definitions"]) == set(module.STATUSES)
    assert all(report["status_definitions"].values())


@pytest.mark.parametrize("case_id, items", [("TC1", {"OI-1"}), ("TC3", {"OI-1", "OI-7"})])
def test_priced_cases_fail_only_on_documented_open_items(cases, case_id, items):
    case = cases[case_id]
    assert case["status"] == "FAIL" and case["audit_status"] == "priced"
    differing = [r for r in case["cashflows"] if r["row_status"] == "DIFFERENCE"]
    assert differing and all(r["open_item"] for r in differing)
    assert {r["open_item"] for r in differing} == items
    for r in case["cashflows"]:
        if r["open_item"] is None:
            assert r["row_status"] == "RECONCILED" and r["discrepancy_sources"] == []


def test_partial_and_blocked_cases_keep_their_reasons(cases):
    assert cases["TC4"]["status"] == "PASS" and cases["TC4"]["reasons"] == []
    # TC2 is no longer blocked: priced with Method A and reported as a FAIL with its reason
    # (the +5.537 difference is kept visible, not tuned away; TC2-F3, R9).
    tc2 = cases["TC2"]
    assert tc2["status"] == "FAIL" and tc2["audit_status"] == "priced"
    assert tc2["reasons"][0].startswith("npv difference +5.5368")
    assert tc2["trade"]["bloomberg"]["npv"] == -158.91  # reference preserved


# --- no recomputation, no tuning -------------------------------------------------------------


def test_optima_values_are_the_audit_values(run):
    audit_cases = {c["case_id"]: c for c in run["audit"]["cases"]}
    for case in run["report"]["cases"]:
        audit_case = audit_cases[case["case_id"]]
        if audit_case["pricing"] is None:
            continue
        for metric in ("npv", "fixed_leg_npv", "floating_leg_npv"):
            assert case["trade"]["optima"][metric] == audit_case["pricing"][metric]
            assert case["trade"]["difference"][metric] == audit_case["differences"][metric]


def test_unsupported_trade_metrics_are_not_fabricated(cases, module):
    optima = cases["TC1"]["trade"]["optima"]
    for metric in ("par_coupon", "pv01", "dv01", "accrued"):
        assert optima[metric] == module.NOT_COMPUTED
    assert cases["TC1"]["trade"]["bloomberg"]["par_coupon"] is not None


def test_run_leaves_inputs_and_quantlib_state_unchanged(run):
    assert run["digest_after"] == run["digest_before"]
    assert run["eval_after"] == run["eval_before"]


def test_floating_rows_separate_index_rate_spread_and_coupon(run, cases):
    audit_cases = {c["case_id"]: c for c in run["audit"]["cases"]}
    for case_id in ("TC1", "TC3"):
        contractual_spread_pct = audit_cases[case_id]["floating_leg"]["spread_bp"] / 100
        for r in cases[case_id]["cashflows"]:
            assert r["accrual_days"] > 0 and r["day_count_fraction"] > 0
            if r["leg"] == "floating":
                assert r["spread_pct"] == pytest.approx(contractual_spread_pct)
                assert r["index_rate_pct"] + r["spread_pct"] == pytest.approx(r["rate_pct"])
                assert r["bloomberg"]["effective_reset_date"] is not None
            else:
                assert r["spread_pct"] is None and r["index_rate_pct"] is None


# --- tolerances and attribution --------------------------------------------------------------


def test_tolerances_come_from_the_audit(module):
    audit = module.audit
    assert module.TOLERANCES == {"coupon_pct": audit.COUPON_DISPLAY_TOL_PCT,
                                 "discount_factor": audit.DF_DISPLAY_TOL,
                                 "payment": audit.PAYMENT_TOL,
                                 "npv_per_cashflow": audit.PAYMENT_TOL}


def _row(**diff):
    base = {"leg": "floating", "period": 1, "payment_date": "2027-05-28",
            "accrual_start": "2026-05-31", "accrual_end": "2027-05-28", "open_item": None,
            "bloomberg": {"accrual_start": "2026-05-31", "accrual_end": "2027-05-28"},
            "difference": {"rate_bp": 0.0, "amount": 0.0, "discount_factor": 0.0,
                           "present_value": 0.0}}
    base["difference"].update(diff)
    return base


@pytest.mark.parametrize("diff, expected", [
    ({}, []),
    ({"rate_bp": 0.01, "amount": 0.05, "discount_factor": 5e-7}, []),  # at the limits
    ({"rate_bp": 0.02, "amount": 0.3}, ["rate"]),       # a rate error explains the payment
    ({"amount": 0.06}, ["payment"]),                    # payment off with the rate in line
    ({"discount_factor": 6e-7}, ["discounting"]),
    ({"rate_bp": -0.05, "discount_factor": 2.6e-6}, ["rate", "discounting"]),
    ({"rate_bp": None, "amount": 0.06}, ["payment"]),   # Bloomberg shows no coupon
])
def test_discrepancy_sources(module, diff, expected):
    assert module.discrepancy_sources(_row(**diff)) == expected


def test_schedule_mismatch_is_attributed_first(module):
    row = _row(rate_bp=0.5)
    row["bloomberg"]["accrual_start"] = "2026-06-01"
    assert module.discrepancy_sources(row) == ["schedule", "rate"]
    assert module.row_status(row) == "DIFFERENCE"


def test_row_without_bloomberg_counterpart(module):
    row = _row()
    row["bloomberg"], row["difference"] = None, None
    assert module.discrepancy_sources(row) == []
    assert module.row_status(row) == "NO_BLOOMBERG_ROW"


def _priced_case(npv_diff=0.0, rows=None):
    rows = rows if rows is not None else [_row(), dict(_row(), leg="fixed")]
    return {"case_id": "TCX", "status": "priced", "error": None, "blockers": [],
            "limitations": [], "cashflows": rows,
            "differences": {"npv": npv_diff, "fixed_leg_npv": 0.0, "floating_leg_npv": npv_diff}}


def test_priced_case_within_tolerance_passes(module):
    assert module.classify(_priced_case(npv_diff=0.05)) == ("PASS", [])


def test_npv_tolerance_scales_with_cashflow_count(module):
    status, reasons = module.classify(_priced_case(npv_diff=0.11))
    assert status == "FAIL"
    assert reasons == ["npv difference +0.1100 exceeds tolerance 0.10",
                       "floating_leg_npv difference +0.1100 exceeds tolerance 0.05"]


def test_one_cashflow_outside_tolerance_fails_even_when_npv_agrees(module):
    case = _priced_case(rows=[_row(discount_factor=1e-6), dict(_row(), leg="fixed")])
    status, reasons = module.classify(case)
    assert status == "FAIL" and reasons == ["floating P1 2027-05-28: discounting"]


def test_priced_case_without_cashflows_does_not_pass(module):
    assert module.classify(_priced_case(rows=[]))[0] == "FAIL"


def test_error_blocked_partial_mapping(module):
    error = {"status": "error", "error": {"stage": "s", "type": "T", "message": "m"}}
    assert module.classify(error) == ("ERROR", ["s: T: m"])
    blocked = {"status": "blocked", "blockers": [{"code": "C", "detail": "d"}]}
    assert module.classify(blocked) == ("BLOCKED", ["C: d"])
    partial = {"status": "partially_audited", "limitations": [{"code": "L", "detail": "d"}]}
    assert module.classify(partial) == ("PARTIAL", ["L: d"])
    assert module.classify({"status": "unexpected"})[0] == "ERROR"


def test_percentage_difference_is_omitted_for_zero_reference(module):
    assert module._pct(1.0, 0.0) is None and module._pct(None, 5.0) is None
    assert module._pct(-1.0, -200.0) == pytest.approx(-0.5)


def test_bloomberg_internal_inconsistency_is_flagged_not_reconciled(module):
    flag = module._bloomberg_consistency(
        {"npv": -388.06, "fixed_leg_npv": -755.74, "floating_leg_npv": 427.02})
    assert flag["consistent"] is False and flag["difference"] == pytest.approx(-59.34)


def test_error_case_is_reported_and_counted(module, run):
    audit_result = copy.deepcopy(run["audit"])
    tc3 = next(c for c in audit_result["cases"] if c["case_id"] == "TC3")
    tc3.update(status="error", pricing=None, differences=None, cashflows=None,
               error={"stage": "pricing with price_irs", "type": "RuntimeError",
                      "message": "injected"})
    report = module.build_report(audit_result)
    assert report["counts"]["ERROR"] == ["TC3"]
    assert report["counts"]["FAIL"] == ["TC1", "TC2", "TC5", "TC6", "TC7", "TC8", "TC9", "TC10"]


# --- output --------------------------------------------------------------------------------


def test_written_report_schema(module, report, tmp_path):
    target = tmp_path / "report"
    written = module.write_report(target, report)
    names = {p.relative_to(target).as_posix() for p in written}
    assert names == {"reconciliation.json", "summary.md", "summary.csv",
                     *(f"cashflows/{c}.csv" for c in CASE_IDS)}
    data = json.loads((target / "reconciliation.json").read_text(encoding="utf-8"))
    assert data["report_schema_version"] == module.REPORT_SCHEMA_VERSION
    assert [c["case_id"] for c in data["cases"]] == CASE_IDS
    with open(target / "summary.csv", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [r["case_id"] for r in rows] == CASE_IDS
    assert tuple(rows[0]) == module.SUMMARY_COLUMNS
    with open(target / "cashflows" / "TC3.csv", newline="", encoding="utf-8") as handle:
        tc3 = list(csv.DictReader(handle))
    assert tuple(tc3[0]) == module.CASHFLOW_COLUMNS and len(tc3) == 8
    assert {r["row_status"] for r in tc3} == {"RECONCILED", "DIFFERENCE"}
    with open(target / "cashflows" / "TC2.csv", newline="", encoding="utf-8") as handle:
        tc2 = list(csv.DictReader(handle))
    assert len(tc2) == 16 and all(r["payment"] and r["bbg_payment"] for r in tc2)
    md = (target / "summary.md").read_text(encoding="utf-8")
    assert "**Counts:** PASS 1, FAIL 9, PARTIAL 0, BLOCKED 0, ERROR 0" in md


def test_write_report_never_overwrites(module, report, tmp_path):
    target = tmp_path / "exists"
    target.mkdir()
    with pytest.raises(FileExistsError):
        module.write_report(target, report)


def test_cli_refuses_existing_or_protected_directory(module, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(module.audit, "run_audit", lambda: pytest.fail("audit must not run"))
    assert module.main(["--output-dir", str(tmp_path)]) == 2
    assert module.main(["--output-dir", str(ROOT / "market_data" / "report")]) == 2
    assert "protected directory" in capsys.readouterr().err


def test_cli_exit_code_reflects_error_cases(module, run, monkeypatch, capsys):
    audit_result = copy.deepcopy(run["audit"])
    audit_result["cases"][0].update(status="error", pricing=None, differences=None,
                                    cashflows=None,
                                    error={"stage": "x", "type": "E", "message": "m"})
    monkeypatch.setattr(module.audit, "run_audit", lambda: audit_result)
    assert module.main([]) == 1
    assert "ERROR 1" in capsys.readouterr().out


def test_cli_end_to_end(tmp_path):
    target = tmp_path / "out"
    proc = subprocess.run([sys.executable, "-m", MODULE, "--output-dir", str(target)],
                          cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr
    assert "PASS 1 | FAIL 9 | PARTIAL 0 | BLOCKED 0 | ERROR 0" in proc.stdout
    assert (target / "reconciliation.json").is_file()
