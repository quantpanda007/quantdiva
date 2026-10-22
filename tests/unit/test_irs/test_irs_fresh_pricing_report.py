"""The TC1/TC3 pricing report script reproduces the end-to-end test results.

Expected values are imported from the existing TC1 and TC3 tests (recorded
baselines and documented Bloomberg differences); nothing is hardcoded here.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import QuantLib as ql
from test_tc1_bloomberg_reconciliation import BASELINE as TC1_BASELINE
from test_tc1_bloomberg_reconciliation import KNOWN_DIFFERENCES as TC1_KNOWN_DIFFERENCES
from test_tc3_pricing_service_e2e import BASELINE as TC3_BASELINE
from test_tc3_pricing_service_e2e import KNOWN_DIFFERENCES as TC3_KNOWN_DIFFERENCES

# Validation-phase test (reads Bloomberg fixtures): excluded from the default run;
# run with `pytest -m validation`.
pytestmark = pytest.mark.validation

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "irs_fresh_pricing_report.py"
EXPECTED = {
    "TC1": ("SLLSL9RR", TC1_BASELINE, TC1_KNOWN_DIFFERENCES),
    "TC3": ("SLLSL90", TC3_BASELINE, TC3_KNOWN_DIFFERENCES),
}


@pytest.fixture(scope="module")
def report_module():
    name = "irs_fresh_pricing_report"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve their module through sys.modules
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(name, None)


@pytest.fixture(scope="module")
def reports(report_module):
    previous = ql.Settings.instance().evaluationDate
    reports = {report.case_id: report for report in report_module.run()}
    assert ql.Settings.instance().evaluationDate == previous  # restored by the script
    return reports


def test_reports_both_trades(reports):
    assert sorted(reports) == ["TC1", "TC3"]
    for case_id, (trade_id, _, _) in EXPECTED.items():
        assert reports[case_id].trade_id == trade_id
        assert reports[case_id].currency == "USD"


@pytest.mark.parametrize("case_id", sorted(EXPECTED))
@pytest.mark.parametrize("metric", ["fixed_leg_npv", "floating_leg_npv", "npv"])
def test_optima_values_equal_the_recorded_baselines(reports, case_id, metric):
    _, baseline, _ = EXPECTED[case_id]
    assert reports[case_id].optima[metric] == pytest.approx(baseline[metric], abs=1e-6)


@pytest.mark.parametrize("case_id", sorted(EXPECTED))
@pytest.mark.parametrize("metric", ["fixed_leg_npv", "floating_leg_npv", "npv"])
def test_bloomberg_differences_equal_the_documented_ones(reports, case_id, metric):
    _, _, known = EXPECTED[case_id]
    expected, tolerance = known[metric]
    assert reports[case_id].differences[metric] == pytest.approx(expected, abs=tolerance)


def test_legs_sum_to_total(reports):
    for report in reports.values():
        legs = report.optima["fixed_leg_npv"] + report.optima["floating_leg_npv"]
        assert legs == pytest.approx(report.optima["npv"], abs=1e-9)


def test_formatted_output_lists_each_trade(report_module, reports):
    text = report_module.format_report([reports["TC1"], reports["TC3"]])
    for case_id, (trade_id, _, _) in EXPECTED.items():
        assert f"{case_id}  trade {trade_id}  currency USD" in text
    for label in ("Fixed-leg NPV", "Floating-leg NPV", "Total NPV", "Optima - BBG"):
        assert label in text
    assert text.count("Cashflows (Optima vs Bloomberg") == 2


# --- cashflow section -------------------------------------------------------------


@pytest.mark.parametrize("case_id, periods", [("TC1", 2), ("TC3", 4)])
def test_cashflow_rows_cover_both_legs(reports, case_id, periods):
    rows = reports[case_id].cashflows
    assert [row.leg for row in rows] == ["fixed"] * periods + ["floating"] * periods
    assert set(reports[case_id].bloomberg_cashflows) == {(row.leg, row.period) for row in rows}


@pytest.mark.parametrize("case_id", sorted(EXPECTED))
def test_cashflow_pvs_sum_to_reported_leg_npvs(reports, case_id):
    report = reports[case_id]
    for leg in ("fixed", "floating"):
        total = sum(row.present_value for row in report.cashflows if row.leg == leg)
        assert total == pytest.approx(report.optima[f"{leg}_leg_npv"], abs=1e-9)
    assert sum(row.present_value for row in report.cashflows) == pytest.approx(
        report.optima["npv"], abs=1e-9
    )


def test_known_difference_tags_are_shown(report_module, reports):
    text = report_module.format_report([reports["TC1"], reports["TC3"]])
    tagged = [line for line in text.splitlines() if line.rstrip().endswith(("OI-1", "OI-7"))]
    # TC1 floating P2, TC3 floating P3 (OI-1) and P4 (OI-7)
    assert len(tagged) == 3
    assert reports["TC1"].tags[("floating", 2)] == "OI-1"
    assert reports["TC3"].tags[("floating", 3)] == "OI-1"
    assert reports["TC3"].tags[("floating", 4)] == "OI-7"
    assert sum(line.rstrip().endswith("DF") for line in text.splitlines()) == 3
