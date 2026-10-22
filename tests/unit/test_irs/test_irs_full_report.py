"""Tests for the detailed ten-case report: derived inputs read from the production-built
swaps (scripts/irs_case_audit.py), diagnostic reconciliation and the evidence register
(scripts/irs_reconciliation_report.py, scripts/irs_evidence_register.py).

Optima numbers must come from the production path; diagnostics must be identities on
those numbers; the register must cover every out-of-tolerance cashflow of the run.
Expected TC7 values are the trace of 14-Oct-2026 (docs/IRS_OPEN_ITEMS.md OI-13); they
are observed values, not tuned targets.
"""

from __future__ import annotations

import csv
import hashlib
import importlib
import json
import re
from pathlib import Path

import pytest
import QuantLib as ql
from test_irs_tc7_term_rate import RESETS_TAB_PCT

# Validation-phase test (reads Bloomberg fixtures): excluded from the default run;
# run with `pytest -m validation`.
pytestmark = pytest.mark.validation

ROOT = Path(__file__).resolve().parents[3]
CASE_IDS = [f"TC{i}" for i in range(1, 11)]
WATCHED = [ROOT / "tests" / "fixtures" / "bloomberg_irs", ROOT / "examples" / "irs",
           ROOT / "market_data" / "2026-03-31"]
# TC2 priced with Method A since 14-Oct-2026 (provisional default, OI-17).
PRICED_OR_PARTIAL = {"TC1", "TC2", "TC3", "TC4", "TC5", "TC6", "TC7", "TC8", "TC9", "TC10"}


def _digest() -> str:
    h = hashlib.sha256()
    for base in WATCHED:
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            h.update(path.relative_to(ROOT).as_posix().encode())
            h.update(path.read_bytes())
    return h.hexdigest()


@pytest.fixture(scope="module")
def module():
    return importlib.import_module("scripts.irs_reconciliation_report")


@pytest.fixture(scope="module")
def run(module):
    before = _digest()
    eval_date = ql.Settings.instance().evaluationDate
    audit_result = module.audit.run_audit()
    report = module.build_report(audit_result)
    report["observation_methods"] = module.observation_method_comparisons(audit_result)  # as main
    return {"audit": audit_result, "report": report, "digest_before": before,
            "digest_after": _digest(), "eval_before": eval_date,
            "eval_after": ql.Settings.instance().evaluationDate}


@pytest.fixture(scope="module")
def report(run):
    return run["report"]


@pytest.fixture(scope="module")
def cases(report):
    return {c["case_id"]: c for c in report["cases"]}


@pytest.fixture(scope="module")
def audit_cases(run):
    return {c["case_id"]: c for c in run["audit"]["cases"]}


# --- derived inputs ---------------------------------------------------------------------------


def test_derived_inputs_only_for_priced_or_partial_cases(audit_cases):
    for case_id, case in audit_cases.items():
        if case_id in PRICED_OR_PARTIAL:
            assert case["derived_inputs"]["rows"], case_id
        else:
            assert case["derived_inputs"] is None, case_id


@pytest.mark.parametrize("case_id", sorted(PRICED_OR_PARTIAL))
def test_derived_inputs_are_tied_to_the_engine(audit_cases, case_id):
    derived = audit_cases[case_id]["derived_inputs"]
    check = derived["engine_check"]
    assert check["future_cashflow_pv_matches_engine"]
    if audit_cases[case_id]["status"] == "priced":
        assert check["rebuild_matches_price_irs"]
        assert check["price_irs_npv"] == audit_cases[case_id]["pricing"]["npv"]
    for row in derived["rows"]:
        if row["item"] == "discount_factor":
            assert row["detail"]["rebuilt_matches_curve"], (case_id, row["payment_date"])


def test_tc7_derived_resets_match_the_production_leg(audit_cases):
    rows = audit_cases["TC7"]["derived_inputs"]["rows"]
    resets = {r["detail"]["reset_date"]: r["value"] for r in rows if r["item"] == "reset_rate"}
    assert list(resets) == list(RESETS_TAB_PCT)
    residual_bp = [(resets[d] - RESETS_TAB_PCT[d]) * 100 for d in RESETS_TAB_PCT]
    assert residual_bp == pytest.approx([-0.054, -0.052, -0.014], abs=0.005)
    windows = [r["value"] for r in rows if r["item"] == "observation_window"]
    assert windows == ["2026-08-28 -> 2027-02-25", "2027-02-24 -> 2027-08-24",
                       "2027-08-27 -> 2028-02-25"]
    assert all("OI-12" in r["basis"] for r in rows if r["item"] == "reset_rate")


@pytest.mark.parametrize("case_id", ["TC1", "TC3", "TC4", "TC6", "TC10"])
def test_sofr_observation_windows_end_on_bloomberg_effective_reset_dates(report, case_id):
    case = next(c for c in report["cases"] if c["case_id"] == case_id)
    windows = [r for r in case["analysis"]["derived_inputs"] if r["item"] == "observation_window"]
    assert windows
    assert all(r["difference"] == "same date" for r in windows), [
        (r["payment_date"], r["difference"]) for r in windows]


def test_tc4_paid_cashflows_are_excluded_not_estimated(audit_cases):
    rows = audit_cases["TC4"]["derived_inputs"]["rows"]
    excluded = [r for r in rows if r["item"] == "excluded_cashflow"]
    assert {(r["leg"], r["payment_date"]) for r in excluded} == {
        ("fixed", "2026-03-31"), ("floating", "2026-03-31")}
    assert all(r["value"] is None for r in excluded)
    window = next(r for r in rows if r["item"] == "observation_window"
                  and r["payment_date"] == "2026-06-30")
    assert window["detail"]["valuation_date_fixing"] and window["detail"]["historical_fixings"] == 0
    assert {(s["leg"], s["payment_date"]) for s in audit_cases["TC4"]["settled"]} == {
        ("fixed", "2026-03-31"), ("floating", "2026-03-31")}


def test_tc8_historical_reset_comes_from_market_data(audit_cases):
    rows = audit_cases["TC8"]["derived_inputs"]["rows"]
    first = next(r for r in rows if r["item"] == "reset_rate" and r["period"] == 1)
    assert first["value"] == pytest.approx(5.36) and first["detail"]["source"] == "fixing"
    assert "trade record" in first["basis"]


# --- diagnostics ---------------------------------------------------------------------------------


def test_every_pv_difference_decomposes_exactly(cases):
    rows = [r for c in cases.values() for r in c["analysis"]["compared_cashflows"]
            if r.get("decomposition")]
    # TC1 4, TC2 16, TC3 8, TC4 8, TC5 4, TC6 6, TC7 4, TC8 6, TC9 16, TC10 4
    assert len(rows) == 76
    assert all(r["decomposition"]["identity_holds"] for r in rows)


@pytest.mark.parametrize("case_id", sorted(PRICED_OR_PARTIAL))
def test_cashflows_close_to_leg_npvs_and_npv(cases, case_id):
    recon = cases[case_id]["analysis"]["leg_reconciliation"]
    assert recon["optima_closes"]
    for leg in recon["legs"].values():
        assert leg["pv_difference"] == pytest.approx(
            leg["amount_effect"] + leg["discount_factor_effect"]
            + leg["bloomberg_display_residual"], abs=1e-6)


def test_tc7_reset_attribution(cases):
    attribution = cases["TC7"]["analysis"]["reset_attribution"]
    assert [s["npv_effect"] for s in attribution["steps"]] == pytest.approx(
        [-0.13846, -0.14026, -0.03311], abs=5e-5)
    assert attribution["total_npv_effect"] == pytest.approx(-0.31183, abs=5e-5)
    assert cases["TC7"]["trade"]["difference"]["npv"] == pytest.approx(-0.31520, abs=5e-5)
    # Bloomberg's resets in the production flat compounding reproduce Bloomberg's payments.
    assert attribution["payments_with_bloomberg_resets"] == pytest.approx(
        {"1": 251.29, "2": 117.98}, abs=0.005)
    assert attribution["npv_with_bloomberg_resets"] == pytest.approx(-388.06, abs=0.005)
    assert "not used" in attribution["bloomberg_source"]


def test_attribution_only_where_bloomberg_resets_exist(cases):
    assert [c for c, rec in cases.items() if rec["analysis"]["reset_attribution"]] == [
        "TC7", "TC8", "TC9"]


@pytest.mark.parametrize("case_id, bloomberg_npv", [("TC8", -139514.98), ("TC9", -61820.75)])
def test_inr_payments_reproduce_bloomberg_with_its_resets(cases, case_id, bloomberg_npv):
    """With Bloomberg's own reset rates the production payment calculation reproduces
    Bloomberg's NPV: the INR differences are in the projected resets only."""
    attribution = cases[case_id]["analysis"]["reset_attribution"]
    assert attribution["npv_with_bloomberg_resets"] == pytest.approx(bloomberg_npv, abs=0.06)


def test_tc4_passes_through_the_production_extractor(cases):
    analysis = cases["TC4"]["analysis"]
    assert cases["TC4"]["status"] == "PASS"
    assert analysis["cashflow_source"].startswith("production extractor")
    assert all(r["row_status"] == "RECONCILED" for r in analysis["compared_cashflows"])


# --- evidence register ---------------------------------------------------------------------------


def test_register_covers_every_out_of_tolerance_cashflow(cases):
    register = importlib.import_module("scripts.irs_evidence_register")
    for case_id, rec in cases.items():
        for f in rec["analysis"]["findings"]:
            assert f["classification"] in register.CLASSIFICATIONS, (case_id, f["id"])


def test_register_is_consistent(cases):
    register = importlib.import_module("scripts.irs_evidence_register")
    docs = (ROOT / "docs" / "IRS_OPEN_ITEMS.md").read_text(encoding="utf-8")
    defined = set(re.findall(r"^## (OI-\d+):", docs, flags=re.M))
    referenced = set()
    for findings in register.FINDINGS.values():
        for f in findings:
            assert f["classification"] in register.CLASSIFICATIONS
            referenced |= set(re.findall(r"OI-\d+", f["open_item"] or ""))
    for q in register.EVIDENCE_REQUESTS:
        assert set(q["cases"]) <= set(CASE_IDS)
        referenced |= set(re.findall(r"OI-\d+", q["open_item"] or ""))
    assert referenced <= defined
    ids = [q["id"] for q in register.EVIDENCE_REQUESTS]
    assert len(ids) == len(set(ids))
    assert set(register.CASE_NOTES) == set(CASE_IDS)
    # No request re-asks a settled question: TC2's notional (OI-11) or the 0.0741% (OI-12).
    text = " ".join(q["request"] for q in register.EVIDENCE_REQUESTS)
    assert "notional" not in text and "0.0741" not in text


def test_supplementary_references_equal_the_pinned_screenshot_values():
    register = importlib.import_module("scripts.irs_evidence_register")
    assert register.SUPPLEMENTARY_BLOOMBERG_REFERENCES["TC7"]["reset_rate_pct"] == RESETS_TAB_PCT


def test_every_blocked_case_has_blockers_and_a_next_action(module, report):
    rows = {r["request_id"]: r for r in module.missing_input_rows(report)}
    for rec in report["cases"]:
        if rec["status"] != "BLOCKED":
            continue
        blocked = [f for f in rec["analysis"]["findings"] if f["classification"] == "Blocked"]
        assert blocked and all(f["next_action"] and "{" not in f["next_action"] for f in blocked)
        assert rows[f"{rec['case_id']}-next"]["request"]


def test_latest_index_is_not_used_by_pricing_code():
    """SME, 14-Oct-2026: latest_index does not determine the TC7 resets; no override logic."""
    for base in ("instruments", "market", "services"):
        for path in (ROOT / base).rglob("*.py"):
            assert "latest_index" not in path.read_text(encoding="utf-8"), path


# --- outputs -------------------------------------------------------------------------------------


def test_full_report_files_and_schemas(module, report, tmp_path):
    target = tmp_path / "full"
    written = module.write_full_report(target, report)
    names = {p.relative_to(target).as_posix() for p in written}
    assert names == {"reconciliation.json", "summary.md", "summary.csv", "case_comparison.csv",
                     "cashflow_reconciliation.csv", "derived_inputs.csv", "missing_inputs.csv",
                     "tc2_observation_methods.csv",
                     *(f"cashflows/{c}.csv" for c in CASE_IDS),
                     *(f"cases/{c}.md" for c in CASE_IDS)}

    def read(name):
        with open(target / name, newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    comparison = read("case_comparison.csv")
    assert [r["case_id"] for r in comparison] == CASE_IDS  # each case exactly once
    assert tuple(comparison[0]) == module.CASE_COMPARISON_COLUMNS
    for r in comparison:
        if r["status"] == "BLOCKED":  # never an Optima value for an unpriced case
            assert r["optima_npv"] == "" and r["optima_par_coupon"] == "" and r["bloomberg_npv"]
        else:
            assert r["optima_par_coupon"] == module.NOT_COMPUTED
    cashflows = read("cashflow_reconciliation.csv")
    assert tuple(cashflows[0]) == module.CASHFLOW_RECONCILIATION_COLUMNS
    assert {r["case_id"] for r in cashflows} == set(CASE_IDS)
    derived = read("derived_inputs.csv")
    assert tuple(derived[0]) == module.DERIVED_INPUT_COLUMNS
    assert {r["case_id"] for r in derived} == PRICED_OR_PARTIAL
    missing = read("missing_inputs.csv")
    assert tuple(missing[0]) == module.MISSING_INPUT_COLUMNS
    data = json.loads((target / "reconciliation.json").read_text(encoding="utf-8"))
    assert data["report_schema_version"] == module.REPORT_SCHEMA_VERSION == 2
    assert all("analysis" in c for c in data["cases"])
    md = (target / "summary.md").read_text(encoding="utf-8")
    assert "reset rates were not trade inputs" in md
    assert "(none in this run)" in md  # no out-of-tolerance cashflow left unclassified
    assert "**Counts:** PASS 1, FAIL 9, PARTIAL 0, BLOCKED 0, ERROR 0" in md
    assert "TC2 SARON observation dates: priced with Method A" in md
    assert "operational assumption" in md and "+5.5368" in md and "R9" in md
    tc2 = (target / "cases" / "TC2.md").read_text(encoding="utf-8")
    assert "## SARON observation-date methods (TC2)" in tc2
    assert "needs SARON 2026-01-29 -> 2026-03-30" in tc2 and "-158.91" in tc2
    assert {r["observation_method"] for r in comparison if r["case_id"] == "TC2"} == {
        "contractual_accrual"}
    assert {r["observation_method"] for r in comparison if r["case_id"] == "TC7"} == {
        "reset_date_fallback"}
    tc7 = (target / "cases" / "TC7.md").read_text(encoding="utf-8")
    assert "Reset-rate attribution (diagnostic)" in tc7 and "R1" in tc7


def test_full_report_never_overwrites(module, report, tmp_path):
    target = tmp_path / "exists"
    target.mkdir()
    with pytest.raises(FileExistsError):
        module.write_full_report(target, report)


def test_report_run_leaves_inputs_and_quantlib_state_unchanged(run):
    assert run["digest_after"] == run["digest_before"]
    assert run["eval_after"] == run["eval_before"]
    assert len(ql.Sofr().timeSeries()) == 0 and len(ql.Saron().timeSeries()) == 0


def test_environment_info_records_versions(module):
    env = module.environment_info(["--output-dir", "x"])
    assert env["quantlib"] == ql.__version__ and env["python"]
    assert env["command"].endswith("--output-dir x")


# --- source conflicts and value provenance ----------------------------------------------------


def test_source_conflicts_are_reported(module, report, tmp_path):
    register = importlib.import_module("scripts.irs_evidence_register")
    ids = [c["id"] for c in register.SOURCE_CONFLICTS]
    assert len(ids) == len(set(ids)) and report["source_conflicts"] == register.SOURCE_CONFLICTS
    target = tmp_path / "conflicts"
    module.write_full_report(target, report)
    md = (target / "summary.md").read_text(encoding="utf-8")
    assert "## Source conflicts" in md and all(f"| {i} |" in md for i in ids)
    assert "## Reading the values" in md


def test_open_questions_reflect_current_evidence():
    audit = importlib.import_module("scripts.irs_case_audit")
    text = " ".join(audit.OPEN_QUESTIONS)
    assert "latest_index is not used for these resets" in text
    assert "R6" in text and "SARON fixings" in text
    assert "SF0006M (CHF)" not in text and "JPY and INR curves" not in text
