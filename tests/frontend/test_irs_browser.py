"""IRS workspace and FX Forward regression in a headless browser against the real API.

* the registry loads every SCHEMA instrument, IRS included, without page errors;
* the IRS registry module opens its three-tab workspace page; fields show/hide by leg
  type; the Market Data tab shows the engine's curve read-only;
* each input-workbook sheet loaded in the UI is sent to POST /pricing/irs exactly as the
  existing Excel reader reads it, and the displayed result is the engine's, equal to the
  approved baseline;
* validation and service errors are shown;
* the FX Forward workspace still renders, maps and prices as before.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[2]
WORKBOOK = ROOT / "examples" / "irs" / "Optima_IRS_Test_Case_Inputs_v4.xlsx"
BASELINES = ROOT / "tests" / "fixtures" / "irs_expected_outputs"
SHEETS = [f"TC{i:03d}" for i in range(1, 11)]


def _visible(page, fid):
    return page.evaluate(f"irs._isApplicable(document.getElementById('irs-{fid}'))")


def _open_irs(page):
    page.evaluate("openWorkspace('irs')")
    page.wait_for_selector("#page-irs.active")


def _tab(page, name):
    page.click(f".irs-top-tab[data-top-tab='{name}']")


def _load_sheet(page, sheet):
    page.set_input_files("#irs-wb-file", str(WORKBOOK))
    page.wait_for_function("document.querySelectorAll('#irs-wb-sheet option').length > 1")
    page.select_option("#irs-wb-sheet", sheet)
    page.wait_for_function("(document.getElementById('irs-wb-status').textContent || '').startsWith('Loaded')")


def _price(page):
    page.click("#irs-economic-terms .irs-btn-primary")
    page.wait_for_function("document.getElementById('irs-pricing-results').style.display !== 'none'"
                           " && document.getElementById('irs-results-body').innerHTML.length > 0")


def _reader_inputs(page, sheet):
    """The trade inputs the backend's Excel reader returns for a sheet (reference)."""
    import httpx
    base = page.url.split("/?")[0].rstrip("/")
    with WORKBOOK.open("rb") as fh:
        r = httpx.post(base + "/api/v1/pricing/irs/workbook",
                       files={"file": (WORKBOOK.name, fh)}, data={"sheet": sheet})
    return r.json()["trade_inputs"]


def _same(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and \
            not isinstance(a, bool) and not isinstance(b, bool):
        return float(a) == float(b)
    return a == b


def test_registry_loads_every_schema_instrument(page):
    missing = page.evaluate("Object.keys(SCHEMA).filter(k => !INSTRUMENT_REGISTRY[k])")
    assert missing == []
    assert page.evaluate("INSTRUMENT_REGISTRY.irs.workspacePage") == "page-irs"
    assert page.evaluate("INSTRUMENT_REGISTRY.irs.apiEndpoint") == "/pricing/irs"
    assert page.page_errors == []


def test_irs_opens_the_three_tab_workspace(page):
    _open_irs(page)
    assert page.evaluate("document.querySelector('.page.active').id") == "page-irs"
    tabs = page.evaluate("[...document.querySelectorAll('#page-irs .irs-top-tab')].map(t => t.textContent.trim())")
    assert tabs == ["Economic Terms", "Amortization Schedule", "Market Data & Pricing Results"]
    assert page.is_visible("#irs-economic-terms") and not page.is_visible("#irs-market-pricing")
    _tab(page, "irs-amortization-schedule")
    assert page.is_visible("#irs-schedule-table") and not page.is_visible("#irs-economic-terms")
    _tab(page, "irs-market-pricing")
    assert page.is_visible(".irs-market-table") and not page.is_visible("#irs-pricing-results")
    # nothing pre-selected; no results before pricing
    assert page.evaluate("[...document.querySelectorAll('#page-irs select[data-opts]')].every(s => s.value === '')")
    assert page.page_errors == []


def test_floating_leg_fields_follow_the_leg_type(page):
    _open_irs(page)
    assert not _visible(page, "rate_timing") and not _visible(page, "fixing_calendar")
    page.select_option("#irs-index_tenor", "1D")
    assert _visible(page, "rate_timing") and not _visible(page, "fixing_calendar")
    page.select_option("#irs-index_tenor", "6M")
    page.select_option("#irs-benchmark", "INR OIS")
    assert _visible(page, "fixing_calendar") and not _visible(page, "rate_timing")
    assert not _visible(page, "observation_method")
    page.select_option("#irs-benchmark", "SF0006M (SARON fallback)")
    assert _visible(page, "observation_method")
    page.select_option("#irs-fixed_direction", "Pay")
    assert page.input_value("#irs-float_direction") == "Receive"
    page.select_option("#irs-fixed_direction", "Receive")
    assert page.input_value("#irs-float_direction") == "Pay"


def test_market_tab_shows_the_engine_curve_read_only(page):
    _open_irs(page)
    page.fill("#irs-valuation_date", "2026-03-31")
    page.select_option("#irs-currency", "CHF")
    page.wait_for_function("document.querySelectorAll('#irs-curve-rows tr').length > 5")
    assert "CHF-SARON-234" in page.input_value("#irs-mkt-forward")
    assert page.evaluate("document.querySelectorAll('#irs-curve-rows input').length") == 0
    assert "Bloomberg curve 234" in page.input_value("#irs-data-source")


@pytest.mark.parametrize("sheet", SHEETS)
def test_workbook_sheet_priced_from_the_ui_matches_baseline(page, sheet):
    _open_irs(page)
    _load_sheet(page, sheet)
    with page.expect_request("**/api/v1/pricing/irs") as req_info:
        _price(page)
    sent = json.loads(req_info.value.post_data)
    assert _same(sent, _reader_inputs(page, sheet)), "UI request differs from the Excel reader"
    assert page.is_visible("#irs-pricing-results")       # results in the Market Data tab
    shown = float(page.get_attribute(".irs-headline .irs-primary .irs-result-value", "data-value"))
    expected = json.loads((BASELINES / f"TC{int(sheet[2:])}.json").read_text())["expected"]
    assert abs(shown - expected["npv"]) <= 1e-6
    fixed_rows = page.evaluate("document.querySelectorAll('#irs-fixed-leg tbody tr:not(.irs-total)').length")
    assert fixed_rows == len([c for c in expected["cashflows"] if c["leg"] == "fixed"]) + \
        len([s for s in expected["settled"] if s["leg"] == "fixed"])
    assert page.page_errors == []


def test_results_workbook_downloads_automatically_and_on_request(page):
    _open_irs(page)
    _load_sheet(page, "TC001")
    with page.expect_download() as auto:
        _price(page)
    assert auto.value.suggested_filename == "SLLSL9RR_2026-03-31.xlsx"
    page.wait_for_function("(document.getElementById('irs-download-status').textContent || '')"
                           ".startsWith('Excel downloaded')")
    with page.expect_download() as again:
        page.click("#irs-download-btn")
    from openpyxl import load_workbook
    with open(again.value.path(), "rb") as fh:
        wb = load_workbook(fh)
    assert wb.sheetnames == ["Summary", "Fixed Leg", "Floating Leg", "Net Cashflow"]
    npv = next(r[1] for r in wb["Summary"].iter_rows(values_only=True) if r[0] == "Swap NPV")
    expected = json.loads((BASELINES / "TC1.json").read_text())["expected"]["npv"]
    assert abs(npv - expected) <= 1e-6


def test_hidden_and_empty_fields_are_sent_as_null(page):
    _open_irs(page)
    _load_sheet(page, "TC001")          # overnight leg
    body = page.evaluate("irs.buildRequest()")
    assert body["floating_leg"]["fixing_calendar"] is None
    assert body["floating_leg"]["observation_method"] is None
    assert body["resets"]["schedule"] == []
    page.fill("#irs-spread_bp", "")
    assert page.evaluate("irs.buildRequest()")["floating_leg"]["spread_bp"] is None   # never 0


def test_reset_hides_results(page):
    _open_irs(page)
    _load_sheet(page, "TC003")
    _price(page)
    page.click("#irs-market-pricing .irs-btn-secondary")
    assert not page.is_visible("#irs-pricing-results")


def test_validation_errors_are_listed(page):
    _open_irs(page)
    _price(page)
    text = page.text_content("#irs-pricing-results")
    assert "Input problems" in text and "trade.trade_id" in text and "fixed_leg.rate_percent" in text


def test_unreachable_service_is_reported(page):
    _open_irs(page)
    _load_sheet(page, "TC001")
    page.route("**/api/v1/pricing/irs", lambda r: r.abort())
    _price(page)
    assert "could not be reached" in page.text_content("#irs-pricing-results")
    assert page.input_value("#irs-trade_id") == "SLLSL9RR"     # inputs kept


def test_fx_forward_workspace_unchanged(page):
    page.evaluate("openWorkspace('fx_forward')")
    page.wait_for_selector("#f-strike")
    ids = page.evaluate("[...document.querySelectorAll('#ws-grouped-fields [id^=\"f-\"]')].map(e => e.id)")
    assert ids == ["f-optima_id", "f-client_name", "f-transaction_ref", "f-contract_type",
                   "f-cpty_a_name", "f-cpty_a_direction", "f-cpty_b_name", "f-cpty_b_direction",
                   "f-strike", "f-ccy_pair", "f-notional_1_position", "f-notional_1_ccy",
                   "f-notional_1_amount", "f-notional_2_position", "f-notional_2_ccy",
                   "f-notional_2_amount", "f-spot", "f-rate", "f-foreign_rate", "f-forward_curve",
                   "f-forward_rate", "f-discount_curve", "f-discount_factor", "f-premium",
                   "f-transaction_date", "f-effective_date", "f-reporting_date", "f-maturity_date"]
    payload = page.evaluate("collectPayload()")
    assert payload["instrument"] == {"type": "fx_forward", "params": {
        "strike": 86.88, "ccy_pair": "USDINR", "notional": 10000000, "direction": "sell",
        "delivery_date": "2027-07-29", "expiry": "2027-07-29"}}
    assert payload["market_data"]["underlyings"] == {"USDINR": {"spot": 85.47, "vol": 0.25,
                                                                "div_yield": 0}}
    page.fill("#f-transaction_ref", "L01SFWD000130")
    with page.expect_request("**/api/v1/pricing/single"):
        page.click("#btn-price")
    page.wait_for_function("$('ws-fx-results').style.display !== 'none'")
    assert page.evaluate("document.querySelector('.page.active').id") == "page-workspace"
    assert page.page_errors == []
