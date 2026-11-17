"""IRS HTTP endpoints (api/v1/endpoints/irs_pricing.py) against the approved baselines.

The path under test is the one the frontend uses: an input-workbook sheet is read by
``POST /pricing/irs/workbook`` (the existing Excel reader), the returned trade inputs are
sent as JSON to ``POST /pricing/irs`` (normalize -> price_normalized -> price_irs_engine),
and the response is compared with ``tests/fixtures/irs_expected_outputs/TC<N>.json`` using
the expected-output suite's own comparison and tolerances. No expected value is changed.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("multipart")
from fastapi.testclient import TestClient  # noqa: E402

from api.app import app  # noqa: E402
from scripts.irs_expected_output_suite import CaseResult, compare, expected_path  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
WORKBOOK = ROOT / "examples" / "irs" / "Optima_IRS_Test_Case_Inputs_v4.xlsx"
SHEETS = [f"TC{i:03d}" for i in range(1, 11)]

client = TestClient(app)


def _sheet_inputs(sheet):
    with WORKBOOK.open("rb") as fh:
        r = client.post("/api/v1/pricing/irs/workbook",
                        files={"file": (WORKBOOK.name, fh)}, data={"sheet": sheet})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sheet"] == sheet
    return body["trade_inputs"]


def _as_suite_outputs(res):
    """API response -> the expected-output suite's ``outputs`` shape."""
    cashflows, settled = [], []
    for leg_key, leg in (("fixed_leg", "fixed"), ("floating_leg", "floating")):
        for row in res[leg_key]:
            if row["status"] == "Settled":
                settled.append({"leg": leg, "side": row["side"], "period": row["period"],
                                "payment_date": row["payment_date"]})
                continue
            cashflows.append({
                "leg": leg, "side": row["side"], "period": row["period"],
                "accrual_start": row["accrual_start"], "accrual_end": row["accrual_end"],
                "payment_date": row["payment_date"], "notional": row["notional"],
                "day_count_fraction": row["dcf"], "rate": row["rate"], "amount": row["amount"],
                "discount_factor": row["df"], "present_value": row["pv"]})
    return {"npv": res["npv"], "fixed_leg_npv": res["fixed_leg_npv"],
            "floating_leg_npv": res["floating_leg_npv"], "cashflows": cashflows,
            "settled": settled}


@pytest.mark.parametrize("sheet", SHEETS)
def test_workbook_sheet_priced_through_api_matches_baseline(sheet):
    case = f"TC{int(sheet[2:])}"
    inputs = _sheet_inputs(sheet)
    r = client.post("/api/v1/pricing/irs", json=inputs)
    assert r.status_code == 200, r.text
    res = r.json()
    expected_doc = json.loads(expected_path(case).read_text(encoding="utf-8"))
    assert res["trade_id"] == expected_doc["trade_id"]
    assert res["currency"] == expected_doc["currency"]
    assert res["valuation_date"] == expected_doc["valuation_date"]
    result = CaseResult(case, "PASS")
    compare(_as_suite_outputs(res), expected_doc["expected"], result)
    assert not result.failures, result.failures
    assert result.checks > 0
    # the response's net rows add the legs per payment date; totals are the engine's
    projected = [n for n in res["net"] if n["status"] == "Projected"]
    assert sum(n["net_pv"] for n in projected) == pytest.approx(res["npv"], abs=1e-6)


def test_tc2_response_carries_the_provisional_method_a_note():
    res = client.post("/api/v1/pricing/irs", json=_sheet_inputs("TC002")).json()
    assert any("PROVISIONAL" in n and "R9" in n for n in res["notes"])


def test_tc4_lists_the_settled_period_and_the_fixings_file():
    res = client.post("/api/v1/pricing/irs", json=_sheet_inputs("TC004")).json()
    assert res["settled_periods"] == 2           # period 1 of each leg
    assert "fixings_2026-03-31.json" in res["market_files"]
    assert [r["status"] for r in res["fixed_leg"]][0] == "Settled"


def test_input_problems_return_422_with_every_issue():
    inputs = _sheet_inputs("TC001")
    inputs["fixed_leg"]["rate_percent"] = None
    inputs["floating_leg"]["day_count"] = "ACT/999"
    r = client.post("/api/v1/pricing/irs", json=inputs)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["error"] == "input_validation"
    joined = "\n".join(detail["issues"])
    assert "fixed_leg.rate_percent" in joined and "floating_leg.day_count" in joined


def test_wrong_market_file_reference_is_reported_not_overridden():
    inputs = _sheet_inputs("TC004")
    inputs["market_data"]["fixings_source_file"] = None   # TC4 needs the 31-Mar fixing
    r = client.post("/api/v1/pricing/irs", json=inputs)
    assert r.status_code == 422
    assert "fixings_source_file" in "\n".join(r.json()["detail"]["issues"])


def test_missing_market_data_is_a_market_data_error():
    inputs = copy.deepcopy(_sheet_inputs("TC001"))
    inputs["trade"]["valuation_date"] = "2026-04-01"
    inputs["market_data"]["snapshot_folder"] = None
    inputs["market_data"]["curve_source_file"] = "usd_sofr_2026-04-01.json"
    r = client.post("/api/v1/pricing/irs", json=inputs)
    assert r.status_code == 422
    assert r.json()["detail"]["error"] in ("market_data", "input_validation")


def _workbook_values(content_or_path):
    """Every cell value per sheet, except the two that name the run (Input, Generated)."""
    import io
    from openpyxl import load_workbook

    src = io.BytesIO(content_or_path) if isinstance(content_or_path, bytes) else content_or_path
    wb = load_workbook(src)
    out = {}
    for ws in wb.worksheets:
        rows = []
        for row in ws.iter_rows(values_only=True):
            if ws.title == "Summary" and row and row[0] in ("Input", "Generated (UTC)"):
                continue
            rows.append(row)
        out[ws.title] = rows
    wb.close()
    return out


@pytest.mark.parametrize("sheet", SHEETS)
def test_report_is_the_command_line_results_workbook(sheet, tmp_path):
    """POST /pricing/irs/report == scripts.price_irs_workbook --output, cell for cell."""
    from scripts.price_irs_workbook import main as cli

    r = client.post("/api/v1/pricing/irs/report", json=_sheet_inputs(sheet))
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    case = json.loads(expected_path(f"TC{int(sheet[2:])}").read_text(encoding="utf-8"))
    assert f'filename="{case["trade_id"]}_{case["valuation_date"]}.xlsx"' in \
        r.headers["content-disposition"]
    out = tmp_path / f"{sheet}.xlsx"
    assert cli(["--workbook", str(WORKBOOK), "--sheet", sheet, "--output", str(out)]) == 0
    assert _workbook_values(r.content) == _workbook_values(out)


def test_report_errors_are_json_like_pricing():
    inputs = _sheet_inputs("TC001")
    inputs["fixed_leg"]["rate_percent"] = None
    r = client.post("/api/v1/pricing/irs/report", json=inputs)
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "input_validation"


def test_market_files_lists_prepared_snapshots_and_fixings():
    r = client.get("/api/v1/pricing/irs/market-files",
                   params={"valuation_date": "2026-03-31", "currency": "inr"})
    assert r.status_code == 200
    assert r.json() == {"valuation_date": "2026-03-31", "currency": "INR",
                        "curves": [{"curve": "INR OIS",
                                    "curve_source_file": "inr_mibor_2026-03-31.json"}],
                        "fixings_files": ["fixings_2026-03-31.json"]}
    empty = client.get("/api/v1/pricing/irs/market-files",
                       params={"valuation_date": "2030-01-01", "currency": "USD"}).json()
    assert empty["curves"] == [] and empty["fixings_files"] == []
    bad = client.get("/api/v1/pricing/irs/market-files",
                     params={"valuation_date": "31/03/2026", "currency": "USD"})
    assert bad.status_code == 422


def test_curve_shows_the_snapshot_the_engine_uses():
    r = client.get("/api/v1/pricing/irs/curve",
                   params={"valuation_date": "2026-03-31", "currency": "USD"})
    assert r.status_code == 200
    body = r.json()
    assert body["file"] == "usd_sofr_2026-03-31.json"
    (curve,) = body["curves"]
    assert curve["curve_id"] == "USD-SOFR-490" and curve["roles"] == ["discount", "forecast"]
    snapshot = json.loads((ROOT / "market_data" / "2026-03-31" / "USD" /
                           "usd_sofr_2026-03-31.json").read_text())["curves"]["USD-SOFR-490"]
    assert [p["tenor"] for p in curve["pillars"]] == [o["tenor"] for o in snapshot["observations"]]
    assert [p["zero_rate"] for p in curve["pillars"]] == [o["zero_rate"] for o in snapshot["observations"]]
    for p in curve["pillars"]:   # the engine curve reproduces the snapshot's check DFs
        assert abs(p["discount_factor"] - p["snapshot_discount_factor"]) <= 1e-6
    missing = client.get("/api/v1/pricing/irs/curve",
                         params={"valuation_date": "2030-01-01", "currency": "USD"})
    assert missing.status_code == 404


def test_workbook_lists_sheets_and_rejects_bad_uploads():
    with WORKBOOK.open("rb") as fh:
        body = client.post("/api/v1/pricing/irs/workbook",
                           files={"file": (WORKBOOK.name, fh)}).json()
    assert body["sheets"] == SHEETS and body["trade_inputs"] is None
    with WORKBOOK.open("rb") as fh:
        r = client.post("/api/v1/pricing/irs/workbook",
                        files={"file": (WORKBOOK.name, fh)}, data={"sheet": "NOPE"})
    assert r.status_code == 422
    r = client.post("/api/v1/pricing/irs/workbook",
                    files={"file": ("x.xlsx", b"not a workbook")})
    assert r.status_code == 422


def test_workbook_listing_closes_the_workbook(monkeypatch):
    """An open workbook keeps its file locked on Windows, and the temporary folder could
    not be removed; the listing must close what it opens."""
    import openpyxl

    opened = []
    real = openpyxl.load_workbook

    def spy(*args, **kwargs):
        wb = real(*args, **kwargs)
        closed = {"closed": False}
        original_close = wb.close

        def close():
            closed["closed"] = True
            original_close()

        wb.close = close
        opened.append(closed)
        return wb

    monkeypatch.setattr(openpyxl, "load_workbook", spy)
    with WORKBOOK.open("rb") as fh:
        r = client.post("/api/v1/pricing/irs/workbook", files={"file": (WORKBOOK.name, fh)})
    assert r.status_code == 200
    assert opened and all(o["closed"] for o in opened)


def test_workbook_upload_survives_an_undeletable_temporary_file(monkeypatch):
    """Windows: a file still held open elsewhere cannot be deleted; cleanup must not
    turn a successful read into a server error."""
    import shutil

    real_rmtree = shutil.rmtree

    def locked(path, ignore_errors=False, **kwargs):
        if not ignore_errors:
            raise PermissionError("[WinError 32] file in use")
        return real_rmtree(path, ignore_errors=True)

    monkeypatch.setattr(shutil, "rmtree", locked)
    assert _sheet_inputs("TC001")["trade"]["trade_id"] == "SLLSL9RR"


def test_old_layout_workbook_is_reported_not_a_server_error():
    import io
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.title = "TC001"
    wb.active["A1"] = "OPTIMA | IRS TEST CASE INPUTS"
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post("/api/v1/pricing/irs/workbook",
                    files={"file": ("old.xlsx", buf.getvalue())}, data={"sheet": "TC001"})
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "workbook"


def test_generic_single_endpoint_still_rejects_irs():
    r = client.post("/api/v1/pricing/single", json={
        "instrument": {"type": "ois", "params": {}},
        "market_data": {"pricing_date": "2026-03-31"}})
    assert r.status_code in (400, 422)
