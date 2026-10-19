"""Internal expected-output suite: the ten IRS cases against the Optima regression baseline.

The expected outputs (tests/fixtures/irs_expected_outputs) were captured from this same
implementation at validation_phase1: these tests detect changes, they are not independent
validation and do not involve Bloomberg (scripts/irs_reconciliation_report.py does).

Run all ten cases:  python -m pytest tests/unit/test_irs/test_irs_expected_outputs.py -q
"""

from __future__ import annotations

import builtins
import json
from pathlib import Path

import pytest

from scripts import irs_expected_output_suite as suite

CASES = suite.CASES


@pytest.mark.parametrize("case", CASES)
def test_case_reproduces_its_expected_outputs(case):
    result = suite.run_case(case)
    assert result.status == "PASS", result.failures or result.detail
    assert result.fields_compared == ["npv", "fixed_leg_npv", "floating_leg_npv", "cashflows",
                                      "settled"]
    doc = json.loads(suite.expected_path(case).read_text(encoding="utf-8"))
    assert result.checks >= 3 + 9 * len(doc["expected"]["cashflows"])


@pytest.mark.parametrize("case", CASES)
def test_baseline_provenance_is_stated_and_not_independent(case):
    doc = json.loads(suite.expected_path(case).read_text(encoding="utf-8"))
    prov = doc["provenance"]
    assert prov["kind"] == "optima_regression_baseline" and prov["independent"] is False
    assert "NOT independent" in prov["statement"] and "NOT Bloomberg" in prov["statement"]
    assert prov["checkpoint"] == "validation_phase1"
    assert prov["inputs"]["trade_file"]["path"] == f"examples/irs/{case.lower()}_trade.json"
    assert doc["case_id"] == case and doc["expected"]["cashflows"]


def test_suite_never_reads_bloomberg_fixtures(monkeypatch):
    opened = []
    real_open = builtins.open

    def recording(file, *args, **kwargs):
        opened.append(str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", recording)
    monkeypatch.setattr(Path, "read_text",
                        lambda self, *a, **k: (opened.append(str(self)),
                                               real_open(self, encoding="utf-8").read())[1])
    for case in CASES:
        assert suite.run_case(case).status == "PASS"
    assert opened and not any("bloomberg_irs" in p for p in opened)


# --- status logic: each status is produced by real execution ------------------------------


def _baseline(tmp_path: Path, case: str, mutate=None) -> Path:
    doc = json.loads(suite.expected_path(case).read_text(encoding="utf-8"))
    if mutate:
        mutate(doc)
    folder = tmp_path / "expected"
    folder.mkdir(exist_ok=True)
    (folder / f"{case}.json").write_text(json.dumps(doc), encoding="utf-8")
    return folder


def test_npv_beyond_tolerance_fails(tmp_path):
    folder = _baseline(tmp_path, "TC1", lambda d: d["expected"].update(
        npv=d["expected"]["npv"] + 2 * suite.TOLERANCES["currency"]))
    result = suite.run_case("TC1", folder)
    assert result.status == "FAIL" and result.failures[0].startswith("npv:")


def test_difference_within_tolerance_passes(tmp_path):
    def nudge(doc):
        doc["expected"]["npv"] += 0.5 * suite.TOLERANCES["currency"]
        doc["expected"]["cashflows"][0]["rate"] += 0.5 * suite.TOLERANCES["rate"]
    assert suite.run_case("TC1", _baseline(tmp_path, "TC1", nudge)).status == "PASS"


@pytest.mark.parametrize("field, delta", [("amount", 1e-5), ("discount_factor", 1e-10),
                                          ("rate", 1e-10), ("day_count_fraction", 1e-10)])
def test_cashflow_field_beyond_tolerance_fails(tmp_path, field, delta):
    folder = _baseline(tmp_path, "TC4", lambda d: d["expected"]["cashflows"][2].update(
        {field: d["expected"]["cashflows"][2][field] + delta}))
    result = suite.run_case("TC4", folder)
    assert result.status == "FAIL"
    assert any(f" {field}: " in f for f in result.failures)


def test_changed_date_and_missing_row_fail(tmp_path):
    def mutate(doc):
        doc["expected"]["cashflows"][0]["accrual_end"] = "2099-01-01"
        doc["expected"]["cashflows"].pop()
    result = suite.run_case("TC7", _baseline(tmp_path, "TC7", mutate))
    assert result.status == "FAIL"
    assert any("accrual_end" in f for f in result.failures)
    assert any("produced but not expected" in f for f in result.failures)


def test_settled_cashflows_are_compared(tmp_path):
    folder = _baseline(tmp_path, "TC4", lambda d: d["expected"].update(settled=[]))
    result = suite.run_case("TC4", folder)
    assert result.status == "FAIL" and any("settled" in f for f in result.failures)


def test_changed_inputs_since_capture_fail(tmp_path):
    folder = _baseline(tmp_path, "TC1", lambda d: d["provenance"]["inputs"]["trade_file"].update(
        sha256="0" * 64))
    result = suite.run_case("TC1", folder)
    assert result.status == "FAIL" and "input files differ" in result.failures[0]


def test_missing_expected_file_is_blocked(tmp_path):
    result = suite.run_case("TC3", tmp_path)
    assert result.status == "BLOCKED" and "no expected-output file" in result.detail


def test_file_without_expected_values_is_blocked(tmp_path):
    folder = _baseline(tmp_path, "TC3", lambda d: d.update(expected={}))
    result = suite.run_case("TC3", folder)
    assert result.status == "BLOCKED" and "holds no expected values" in result.detail


def test_pricing_exception_is_error():
    def broken(case):
        raise RuntimeError("injected pricing failure")
    result = suite.run_case("TC5", pricer=broken)
    assert result.status == "ERROR" and "injected pricing failure" in result.detail


def test_partial_expected_values_compare_only_what_is_present(tmp_path):
    def keep_npv_only(doc):
        doc["expected"] = {"npv": doc["expected"]["npv"]}
    result = suite.run_case("TC6", _baseline(tmp_path, "TC6", keep_npv_only))
    assert result.status == "PASS" and result.fields_compared == ["npv"] and result.checks == 1


# --- baseline protection and reporting ----------------------------------------------------


def test_capture_never_silently_replaces_a_baseline(tmp_path):
    folder = _baseline(tmp_path, "TC1")
    with pytest.raises(FileExistsError):
        suite.capture(["TC1"], folder)
    with pytest.raises(ValueError, match="requires a reason"):
        suite.capture(["TC1"], folder, overwrite=True)
    original = (folder / "TC1.json").read_text(encoding="utf-8")
    suite.capture(["TC1"], folder, overwrite=True, reason="test recapture")
    doc = json.loads((folder / "TC1.json").read_text(encoding="utf-8"))
    assert doc["provenance"]["recapture_reason"] == "test recapture"
    assert doc["expected"] == json.loads(original)["expected"]  # same code, same outputs


def test_cli_reports_every_case_and_writes_results(tmp_path, capsys):
    assert suite.main(["run", "--output-dir", str(tmp_path / "out")]) == 0
    out = capsys.readouterr().out
    assert "PASS 10 | FAIL 0 | BLOCKED 0 | ERROR 0" in out
    assert "NOT independent validation, NOT Bloomberg" in out
    data = json.loads((tmp_path / "out" / "expected_output_results.json").read_text(
        encoding="utf-8"))
    assert data["baseline"]["independent"] is False and len(data["results"]) == 10


def test_cli_exit_code_is_nonzero_when_a_case_does_not_pass(tmp_path, capsys):
    folder = _baseline(tmp_path, "TC1", lambda d: d["expected"].update(npv=0.0))
    assert suite.main(["run", "--case", "TC1", "--expected-dir", str(folder)]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_bloomberg_reconciliation_is_untouched():
    """The separate Bloomberg report keeps its own tolerances and statuses."""
    from scripts import irs_reconciliation_report as report
    assert report.TOLERANCES == {"coupon_pct": 0.0001, "discount_factor": 5e-07,
                                 "npv_per_cashflow": 0.05, "payment": 0.05}
    assert report.STATUSES == ("PASS", "FAIL", "PARTIAL", "BLOCKED", "ERROR")
