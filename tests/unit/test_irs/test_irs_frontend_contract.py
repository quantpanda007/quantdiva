"""The IRS frontend module (frontend/static/instruments/rates/irs.js) stays in step with
the backend input contract and the frontend loading architecture. Static checks only:
no browser needed (the browser tests are tests/frontend/test_irs_browser.py)."""

from __future__ import annotations

import re
from pathlib import Path

from services.irs_inputs import normalizer as n
from services.irs_inputs.contract import RESET_ROW_KEYS, SCHEDULE_ROW_KEYS, SECTION_KEYS

ROOT = Path(__file__).resolve().parents[3]
STATIC = ROOT / "frontend" / "static"
IRS_JS = (STATIC / "instruments" / "rates" / "irs.js").read_text(encoding="utf-8")
HTML = (STATIC / "optima.html").read_text(encoding="utf-8")


def _js_block(name: str) -> str:
    m = re.search(rf"const {name} = (\{{.*?\n\}});", IRS_JS, re.S)
    assert m, name
    return m.group(1)


def _options():
    block = _js_block("IRS_OPTIONS")
    out = {}
    for key, body in re.findall(r"(\w+):\s*\[(.*?)\]", block, re.S):
        out[key] = re.findall(r"'([^']*)'", body)
    return out


def test_select_options_are_exactly_the_normalizer_labels():
    o = _options()
    assert o["currencies"] == list(n.CURRENCIES)
    assert o["directions"] == list(n.DIRECTIONS)
    assert o["paymentFrequencies"] == list(n.PAYMENT_FREQUENCIES)
    assert o["dayCounts"] == list(n.DAY_COUNTS)
    assert o["businessDayConventions"] == list(n.BUSINESS_DAY_CONVENTIONS)
    assert o["calendars"] == list(n.CALENDARS)
    assert o["benchmarks"] == list(n.BENCHMARK_LABELS)
    assert o["indexTenors"] == list(n.INDEX_TENORS)
    assert o["resetFrequencies"] == list(n.RESET_FREQUENCIES)
    assert o["rateTimings"] == list(n.RATE_TIMINGS)
    assert o["lookbackTypes"] == list(n.LOOKBACK_TYPES)
    assert o["compounding"] == list(n.COMPOUNDING)
    assert o["spreadTreatments"] == list(n.SPREAD_TREATMENTS)
    assert o["fixingCalendars"] == list(n.FIXING_CALENDARS)
    assert o["termCompounding"] == list(n.TERM_COMPOUNDING)
    assert o["observationMethods"] == list(n.OBSERVATION_METHODS)
    assert o["principalExchanges"] == list(n.PRINCIPAL_EXCHANGES)
    assert o["amortisationTypes"] == list(n.AMORTISATION_TYPES)
    assert o["curves"] == list(n.CURVES)
    assert o["interpolations"] == list(n.INTERPOLATIONS)


def test_field_map_covers_every_contract_key_once():
    pairs = re.findall(r"(\w+): \['(\w+)', '(\w+)'\]", _js_block("IRS_FIELD_MAP"))
    mapped = sorted((section, key) for _, section, key in pairs)
    expected = sorted((section, key) for section, keys in SECTION_KEYS.items()
                      for key in keys if key != "schedule")
    assert mapped == expected
    assert len({f for f, _, _ in pairs}) == len(pairs)


def test_table_columns_are_the_contract_row_keys():
    for const, keys, table in (("IRS_SCHEDULE_COLUMNS", SCHEDULE_ROW_KEYS, "irs-schedule-table"),
                               ("IRS_RESET_COLUMNS", RESET_ROW_KEYS, "irs-resets-table")):
        m = re.search(rf"const {const} = \[(.*?)\];", IRS_JS, re.S)
        cols = re.findall(r"id: '(\w+)'", m.group(1))
        assert sorted(cols) == sorted(keys) and len(cols) == len(keys)
        head = re.search(rf'<table[^>]*id="{table}"[^>]*>\s*<thead><tr>(.*?)</tr>', HTML, re.S)
        assert head and head.group(1).count("<th>") == len(cols) + 1   # + remove-row column


def test_every_mapped_field_and_option_list_is_on_the_irs_page():
    page = HTML[HTML.index('id="page-irs"'):HTML.index("<!-- /page-irs -->")]
    fields = re.findall(r"(\w+): \['\w+', '\w+'\]", _js_block("IRS_FIELD_MAP"))
    for field in fields:
        assert f'id="irs-{field}"' in page, field
    options = _options()
    for key in re.findall(r'data-opts="(\w+)"', page):
        assert key in options, key
    # page selects start without hardcoded options (filled from IRS_OPTIONS, blank first)
    assert not re.search(r'<select[^>]*data-opts="\w+"[^>]*>\s*<option', page)


def test_no_mock_pricing_values_on_the_irs_page():
    page = HTML[HTML.index('id="page-irs"'):HTML.index("<!-- /page-irs -->")]
    for mock in ("-7,955", "31,978", "24,023", "63.96", "64.67", "3.65240", "0.999088",
                 "TC1 Bloomberg", "Bloomberg reference"):
        assert mock not in page, mock


def test_module_is_registered_and_uses_the_irs_endpoint():
    assert "INSTRUMENT_REGISTRY['irs'] = irs;" in IRS_JS
    assert "apiEndpoint: '/pricing/irs'" in IRS_JS
    # no pricing in the frontend: the only arithmetic on results is display formatting
    for forbidden in ("Math.exp", "Math.log", "Math.pow", "discount_factor *"):
        assert forbidden not in IRS_JS


def test_script_loading_order_follows_the_architecture():
    srcs = re.findall(r'<script src="/static/([^"]+)"></script>', HTML)
    schema, base = srcs.index("schema/schema_master.js"), srcs.index("instruments/_base.js")
    registry, core = srcs.index("optima_registry.js"), srcs.index("optima_core.js")
    instruments = [i for i, s in enumerate(srcs)
                   if s.startswith("instruments/") and s != "instruments/_base.js"]
    assert schema < base < min(instruments) and max(instruments) < registry < core
    assert "instruments/rates/irs.js" in srcs and "instruments/fx/fx_forward.js" in srcs


def test_irs_page_is_opened_through_the_registry_and_no_curve_upload_path():
    assert "workspacePage: 'page-irs'" in IRS_JS
    core = (STATIC / "optima_core.js").read_text(encoding="utf-8")
    assert "price-with-curves" not in core and "openIrsPage" not in core
    assert "pageModule?.workspacePage" in core
