"""
Reusable Dash components.

Provides consistent UI building blocks across all pages.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import dash_bootstrap_components as dbc
from dash import html, dcc


# ═══════════════════════════════════════════════════════════════════
# Sidebar Navigation
# ═══════════════════════════════════════════════════════════════════

NAV_ITEMS = [
    {"id": "dashboard", "label": "◉ Dashboard",     "href": "/"},
    {"id": "pricer",    "label": "⚡ Pricer",        "href": "/pricer"},
    {"id": "risk",      "label": "⚠ Risk Lab",       "href": "/risk"},
    {"id": "portfolio", "label": "📋 Portfolio",      "href": "/portfolio"},
    {"id": "market",    "label": "📈 Market Tools",   "href": "/market"},
    {"id": "registry",  "label": "▦ Registry",       "href": "/registry"},
]


def sidebar():
    """Fixed sidebar with navigation links."""
    return html.Div(className="sidebar", children=[
        # Brand
        html.Div(className="sidebar-brand", children=[
            html.Div("Q", className="sidebar-logo"),
            html.Div([
                html.Div("QuantPricer", className="sidebar-title"),
                html.Div("v0.2.0", className="sidebar-version"),
            ]),
        ]),

        # Nav links
        html.Div(className="sidebar-nav", id="sidebar-nav", children=[
            dcc.Link(
                item["label"],
                href=item["href"],
                className="sidebar-link",
                id=f"nav-{item['id']}",
            )
            for item in NAV_ITEMS
        ]),

        # Footer
        html.Div(
            "QuantLib Pricing Platform",
            style={
                "position": "absolute", "bottom": 0, "left": 0, "right": 0,
                "padding": "16px 20px", "borderTop": "1px solid var(--border)",
                "fontSize": "10px", "color": "var(--text-muted)",
            },
        ),
    ])


# ═══════════════════════════════════════════════════════════════════
# Form Helpers
# ═══════════════════════════════════════════════════════════════════

def form_field(label: str, control, field_id: str = ""):
    """Labeled form field."""
    return html.Div(style={"marginBottom": "14px"}, children=[
        html.Label(label, className="form-label"),
        control,
    ])


def text_input(id: str, value: str = "", placeholder: str = "", type: str = "text"):
    """Styled text/number input."""
    return dbc.Input(
        id=id, value=value, placeholder=placeholder, type=type,
        className="form-control",
        style={"background": "var(--bg)", "color": "var(--text)"},
    )


def dropdown(id: str, options: list, value: str = None, placeholder: str = "Select..."):
    """Styled dropdown."""
    return dcc.Dropdown(
        id=id,
        options=[{"label": o if isinstance(o, str) else o.get("label", o.get("value")),
                  "value": o if isinstance(o, str) else o.get("value")}
                 for o in options],
        value=value,
        placeholder=placeholder,
        clearable=False,
        style={"background": "var(--bg)"},
    )


# ═══════════════════════════════════════════════════════════════════
# Instrument Form (hardcoded fields per type — Phase 1)
# ═══════════════════════════════════════════════════════════════════

INSTRUMENT_FIELDS = {
    "vanilla_option": [
        ("trade_id",      "text",   "VAN-001"),
        ("underlying",    "text",   "AAPL"),
        ("strike",        "number", "185"),
        ("expiry",        "text",   "2026-01-15"),
        ("option_type",   "select", ["call", "put"]),
        ("exercise_type", "select", ["european", "american", "bermudan"]),
        ("currency",      "text",   "USD"),
    ],
    "barrier_option": [
        ("trade_id",      "text",   "BAR-001"),
        ("underlying",    "text",   "AAPL"),
        ("strike",        "number", "185"),
        ("expiry",        "text",   "2026-01-15"),
        ("option_type",   "select", ["call", "put"]),
        ("barrier_type",  "select", ["down_out", "down_in", "up_out", "up_in"]),
        ("barrier_level", "number", "160"),
        ("rebate",        "number", "0"),
    ],
    "digital_option": [
        ("trade_id",     "text",   "DIG-001"),
        ("underlying",   "text",   "AAPL"),
        ("strike",       "number", "185"),
        ("expiry",       "text",   "2026-01-15"),
        ("option_type",  "select", ["call", "put"]),
        ("digital_type", "select", ["cash_or_nothing", "asset_or_nothing"]),
        ("cash_payoff",  "number", "100"),
    ],
    "asian_option": [
        ("trade_id",        "text",   "ASIAN-001"),
        ("underlying",      "text",   "AAPL"),
        ("strike",          "number", "185"),
        ("expiry",          "text",   "2026-01-15"),
        ("option_type",     "select", ["call", "put"]),
        ("average_type",    "select", ["arithmetic", "geometric"]),
        ("strike_type",     "select", ["fixed", "floating"]),
        ("averaging_start", "text",   "2025-01-15"),
        ("fixing_frequency","select", ["daily", "weekly", "monthly", "quarterly"]),
    ],
    "lookback_option": [
        ("trade_id",    "text",   "LB-001"),
        ("underlying",  "text",   "AAPL"),
        ("expiry",      "text",   "2026-01-15"),
        ("option_type", "select", ["call", "put"]),
        ("strike_type", "select", ["fixed", "floating"]),
    ],
    "irs": [
        ("trade_id",            "text",   "IRS-001"),
        ("notional",            "number", "1000000"),
        ("currency",            "text",   "USD"),
        ("start_date",          "text",   "2025-01-15"),
        ("end_date",            "text",   "2030-01-15"),
        ("fixed_rate",          "number", "0.04"),
        ("direction",           "select", ["pay", "receive"]),
        ("fixed_leg_frequency", "select", ["semiannual", "annual", "quarterly"]),
        ("float_leg_frequency", "select", ["quarterly", "semiannual", "monthly"]),
        ("float_index_tenor",   "select", ["3M", "6M", "1M"]),
    ],
    "bond": [
        ("trade_id",         "text",   "BOND-001"),
        ("face_value",       "number", "100"),
        ("coupon_rate",      "number", "0.05"),
        ("issue_date",       "text",   "2024-01-15"),
        ("maturity_date",    "text",   "2034-01-15"),
        ("coupon_frequency", "select", ["semiannual", "annual", "quarterly"]),
        ("day_count",        "select", ["ACT/ACT", "30/360", "ACT/360", "ACT/365"]),
        ("currency",         "text",   "USD"),
    ],
    "fra": [
        ("trade_id",          "text",   "FRA-001"),
        ("notional",          "number", "1000000"),
        ("currency",          "text",   "USD"),
        ("start_date",        "text",   "2025-04-15"),
        ("end_date",          "text",   "2025-07-15"),
        ("fixed_rate",        "number", "0.045"),
        ("direction",         "select", ["pay", "receive"]),
        ("float_index_tenor", "select", ["3M", "6M", "1M"]),
        ("day_count",         "select", ["ACT/360", "ACT/365", "30/360"]),
    ],
    "cap_floor": [
        ("trade_id",          "text",   "CAP-001"),
        ("notional",          "number", "1000000"),
        ("currency",          "text",   "USD"),
        ("start_date",        "text",   "2025-01-15"),
        ("end_date",          "text",   "2030-01-15"),
        ("strike",            "number", "0.05"),
        ("cap_or_floor",      "select", ["cap", "floor"]),
        ("float_frequency",   "select", ["quarterly", "semiannual", "monthly"]),
        ("float_index_tenor", "select", ["3M", "6M", "1M"]),
        ("vol",               "number", "0.20"),
    ],
    "swaption": [
        ("trade_id",            "text",   "SWPN-001"),
        ("notional",            "number", "1000000"),
        ("currency",            "text",   "USD"),
        ("expiry_date",         "text",   "2026-01-15"),
        ("swap_end",            "text",   "2031-01-15"),
        ("strike",              "number", "0.04"),
        ("swaption_type",       "select", ["payer", "receiver"]),
        ("fixed_leg_frequency", "select", ["semiannual", "annual", "quarterly"]),
        ("float_leg_frequency", "select", ["quarterly", "semiannual", "monthly"]),
        ("float_index_tenor",   "select", ["3M", "6M", "1M"]),
        ("settlement_type",     "select", ["physical", "cash"]),
        ("vol",                 "number", "0.20"),
    ],
    "cds": [
        ("trade_id",          "text",   "CDS-001"),
        ("notional",          "number", "10000000"),
        ("currency",          "text",   "USD"),
        ("start_date",        "text",   "2025-01-15"),
        ("maturity_date",     "text",   "2030-01-15"),
        ("spread",            "number", "0.01"),
        ("direction",         "select", ["buy", "sell"]),
        ("recovery_rate",     "number", "0.40"),
        ("hazard_rate",       "number", "0.02"),
        ("payment_frequency", "select", ["quarterly", "semiannual", "annual"]),
    ],
}

NUMERIC_FIELDS = {
    "strike", "barrier_level", "rebate", "cash_payoff",
    "notional", "fixed_rate", "face_value", "coupon_rate", "vol",
    "spread", "recovery_rate", "hazard_rate",
}


def build_instrument_form(instrument_type: str, page: str = "pricer"):
    """Build form fields for a given instrument type.

    Args:
        instrument_type: e.g. 'vanilla_option'
        page: page prefix to avoid ID collisions ('pricer', 'risk', 'pf')
    """
    fields = INSTRUMENT_FIELDS.get(instrument_type, [])
    children = []

    for name, ftype, default in fields:
        label = name.replace("_", " ").upper()
        fid = {"type": f"{page}-inst-field", "field": name}

        if ftype == "select":
            ctrl = dcc.Dropdown(
                id=fid,
                options=[{"label": o, "value": o} for o in default],
                value=default[0] if default else None,
                clearable=False,
                style={"background": "var(--bg)"},
            )
        elif ftype == "number":
            ctrl = dbc.Input(
                id=fid, value=str(default), type="number",
                className="form-control",
                style={"background": "var(--bg)", "color": "var(--text)"},
            )
        else:
            ctrl = dbc.Input(
                id=fid, value=str(default), type="text",
                className="form-control",
                style={"background": "var(--bg)", "color": "var(--text)"},
            )

        children.append(
            dbc.Col(form_field(label, ctrl), width=6)
        )

    return dbc.Row(children)


def collect_instrument_params(instrument_type: str, *input_values) -> Dict[str, Any]:
    """
    Collect values from the dynamic instrument form into a params dict.

    Call this in a callback with the appropriate Input list.
    """
    fields = INSTRUMENT_FIELDS.get(instrument_type, [])
    params = {}
    for i, (name, ftype, _) in enumerate(fields):
        val = input_values[i] if i < len(input_values) else None
        if name in NUMERIC_FIELDS and val is not None:
            try:
                val = float(val)
            except (ValueError, TypeError):
                val = 0.0
        params[name] = val
    return params


# ═══════════════════════════════════════════════════════════════════
# Market Data Form
# ═══════════════════════════════════════════════════════════════════

def market_data_form(prefix: str = "mkt"):
    """Market data input panel."""
    return html.Div([
        html.Div("MARKET DATA", className="panel-header"),
        dbc.Row([
            dbc.Col(form_field("Pricing Date", text_input(f"{prefix}-pricing-date", "2025-01-15")), width=6),
            dbc.Col(form_field("Risk-Free Rate", text_input(f"{prefix}-rate", "0.045", type="number")), width=6),
        ]),
        dbc.Row([
            dbc.Col(form_field("Spot Price", text_input(f"{prefix}-spot", "185", type="number")), width=4),
            dbc.Col(form_field("Volatility", text_input(f"{prefix}-vol", "0.25", type="number")), width=4),
            dbc.Col(form_field("Div Yield", text_input(f"{prefix}-div", "0.005", type="number")), width=4),
        ]),
    ])


def collect_market_data(pricing_date, rate, spot, vol, div_yield, underlying="AAPL"):
    """Build market_data dict from form values.

    For rates instruments (IRS, Bond) where underlying may be empty,
    we use 'USD' as the key and still provide spot/vol even though
    the rates engine only needs the discount curve.
    """
    # Default underlying for rates instruments
    if not underlying or underlying.strip() == "":
        underlying = "USD"

    return {
        "pricing_date": pricing_date or "2025-01-15",
        "underlyings": {
            underlying: {
                "spot": float(spot or 100),
                "vol": float(vol or 0.2),
                "div_yield": float(div_yield or 0),
            }
        },
        "rate": float(rate or 0.05),
    }


# ═══════════════════════════════════════════════════════════════════
# Result Display Components
# ═══════════════════════════════════════════════════════════════════

def npv_card(result: Dict) -> html.Div:
    """NPV result display."""
    npv = result.get("npv", 0)
    trade_id = result.get("trade_id", "")
    model = result.get("model", "")
    engine = result.get("engine", "")
    elapsed = result.get("elapsed_ms", 0)

    return html.Div(className="npv-card", children=[
        html.Div(className="npv-header", children=[
            html.Div("NET PRESENT VALUE", className="npv-label"),
            html.Div(f"${npv:,.4f}", className="npv-value"),
            html.Div(
                f"{trade_id} · {model} · {engine} · {elapsed}ms",
                className="npv-meta",
            ),
        ]),
    ])


def greeks_display(greeks: Dict) -> html.Div:
    """Greeks grid display — adapts for equity vs rates measures."""
    if not greeks:
        return html.Div()

    # Separate equity greeks from rates measures
    equity_keys = {"delta", "gamma", "vega", "theta", "rho"}
    rates_keys = {"dv01", "duration", "convexity"}

    has_equity = any(k in greeks for k in equity_keys if greeks.get(k) is not None)
    has_rates = any(k in greeks for k in rates_keys if greeks.get(k) is not None)

    # Format helpers
    FORMATS = {
        "dv01": lambda v: f"{v*10000:.4f} bp",  # display in bps
        "duration": lambda v: f"{v:.4f} yrs",
        "convexity": lambda v: f"{v:.2f}",
    }
    LABELS = {
        "dv01": "DV01",
        "duration": "MOD DURATION",
        "convexity": "CONVEXITY",
        "delta": "DELTA",
        "gamma": "GAMMA",
        "vega": "VEGA",
        "theta": "THETA",
        "rho": "RHO",
    }

    sections = []

    if has_equity:
        cells = []
        for name in ["delta", "gamma", "vega", "theta", "rho"]:
            val = greeks.get(name)
            if val is None and name not in greeks:
                continue
            if val is not None:
                css = "greek-positive" if val >= 0 else "greek-negative"
                display = f"{val:.6f}"
            else:
                css = "greek-na"
                display = "N/A"
            cells.append(html.Div(className="greek-cell", children=[
                html.Div(LABELS.get(name, name.upper()), className="greek-name"),
                html.Div(display, className=f"greek-value {css}"),
            ]))
        if cells:
            sections.append(
                html.Div("GREEKS", className="panel-header",
                         style={"padding": "16px 28px 0"})
            )
            sections.append(html.Div(className="greeks-grid", children=cells))

    if has_rates:
        cells = []
        for name in ["dv01", "duration", "convexity", "rho", "theta"]:
            val = greeks.get(name)
            if val is None and name not in greeks:
                continue
            if val is not None:
                css = "greek-positive" if val >= 0 else "greek-negative"
                fmt = FORMATS.get(name)
                display = fmt(val) if fmt else f"{val:.6f}"
            else:
                css = "greek-na"
                display = "N/A"
            cells.append(html.Div(className="greek-cell", children=[
                html.Div(LABELS.get(name, name.upper()), className="greek-name"),
                html.Div(display, className=f"greek-value {css}"),
            ]))
        if cells:
            label = "RATES SENSITIVITIES" if not has_equity else "RATES MEASURES"
            sections.append(
                html.Div(label, className="panel-header",
                         style={"padding": "16px 28px 0"})
            )
            sections.append(html.Div(className="greeks-grid", children=cells))

    return html.Div(sections) if sections else html.Div()


def compare_table(results: List[Dict]) -> html.Div:
    """Engine comparison table."""
    if not results:
        return html.Div()

    header = html.Thead(html.Tr([
        html.Th("Engine"), html.Th("NPV"), html.Th("Diff (bps)"),
    ]))

    rows = []
    for r in results:
        npv = r.get("npv", r.get("reference_npv"))
        bps = r.get("rel_diff_bps", 0)
        bps_color = "text-green" if abs(bps or 0) < 1 else "text-red"

        rows.append(html.Tr([
            html.Td(r.get("engine", "")),
            html.Td(f"{npv:.6f}" if npv else "FAILED", className="text-accent"),
            html.Td(f"{bps:.2f}" if bps is not None else "—", className=bps_color),
        ]))

    return html.Div([
        html.Div("ENGINE COMPARISON", className="panel-header", style={"padding": "16px 28px 0"}),
        html.Div(style={"padding": "0 28px 16px"}, children=[
            dbc.Table([header, html.Tbody(rows)],
                      bordered=False, hover=True, className="table"),
        ]),
    ])


def error_alert(message: str) -> dbc.Alert:
    """Error alert."""
    return dbc.Alert(f"⚠ {message}", color="danger", className="alert-danger")
