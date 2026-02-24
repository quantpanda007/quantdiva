"""
Pricer page — price any instrument with Greeks and engine comparison.

Market data panel adapts based on instrument type:
- Options: Spot, Vol, Div Yield, Rate, Pricing Date
- IRS/Bond: Rate, Pricing Date (no spot/vol/div)
"""

from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import html, dcc

from components.components import (
    form_field, dropdown, text_input,
    build_instrument_form,
)


INSTRUMENT_TYPES = [
    {"label": "VANILLA OPTION",     "value": "vanilla_option"},
    {"label": "BARRIER OPTION",     "value": "barrier_option"},
    {"label": "DIGITAL OPTION",     "value": "digital_option"},
    {"label": "ASIAN OPTION",       "value": "asian_option"},
    {"label": "LOOKBACK OPTION",    "value": "lookback_option"},
    {"label": "INTEREST RATE SWAP", "value": "irs"},
    {"label": "FIXED RATE BOND",    "value": "bond"},
    {"label": "FRA",                "value": "fra"},
    {"label": "CAP / FLOOR",       "value": "cap_floor"},
    {"label": "SWAPTION",          "value": "swaption"},
    {"label": "CDS",               "value": "cds"},
    {"label": "FX FORWARD",        "value": "fx_forward"},
    {"label": "FX OPTION",         "value": "fx_option"},
]

# Instruments that don't need the equity market data panel
RATES_INSTRUMENTS = {"irs", "bond", "fra", "cap_floor", "swaption", "cds"}
FX_INSTRUMENTS = {"fx_forward", "fx_option"}


def layout():
    return html.Div([
        # Page header
        html.H1("Instrument Pricer", className="page-title"),
        html.P("Price any registered instrument with real-time Greeks",
               className="page-subtitle"),

        dbc.Row([
            # ── Left column: instrument config ────────────────────
            dbc.Col(width=6, children=[
                # Instrument type + form
                html.Div(className="panel", children=[
                    form_field(
                        "Instrument Type",
                        dropdown("inst-type", INSTRUMENT_TYPES, "vanilla_option"),
                    ),
                    html.Div(id="instrument-form-container",
                             children=build_instrument_form("vanilla_option", page="pricer")),
                ]),

                # Model & Engine
                html.Div(className="panel", children=[
                    dbc.Row([
                        dbc.Col(form_field("Model", dropdown(
                            "model-select",
                            [{"label": "Black-Scholes", "value": "black_scholes"},
                             {"label": "Heston", "value": "heston"},
                             {"label": "Hull-White 1F", "value": "hull_white_1f"}],
                            "black_scholes",
                        )), width=6),
                        dbc.Col(form_field("Engine", dropdown(
                            "engine-select",
                            [{"label": "Analytic (Black)", "value": "analytic"},
                             {"label": "Bachelier (Normal)", "value": "bachelier"},
                             {"label": "Hull-White (Tree)", "value": "hull_white"},
                             {"label": "Heston", "value": "heston"},
                             {"label": "Bootstrapped (Credit)", "value": "bootstrapped"},
                             {"label": "ISDA (Credit)", "value": "isda"},
                             {"label": "Monte Carlo", "value": "monte_carlo"},
                             {"label": "Finite Difference", "value": "finite_difference"},
                             {"label": "Binomial", "value": "binomial"}],
                            "analytic",
                        )), width=6),
                    ]),
                    # Engine-specific params (shown conditionally)
                    html.Div(id="engine-params-container"),
                ]),
            ]),

            # ── Right column: market data + actions ───────────────
            dbc.Col(width=6, children=[
                html.Div(className="panel", children=[
                    # Dynamic market data form — switches based on inst type
                    html.Div(id="market-data-container", children=[
                        equity_market_data(),
                    ]),
                    # Live data button
                    dbc.Button(
                        "📡 Load Live Data",
                        id="btn-load-live",
                        color="info",
                        size="sm",
                        outline=True,
                        style={"width": "100%", "marginTop": "8px",
                               "fontSize": "12px", "letterSpacing": "1px"},
                    ),
                    html.Div(id="live-data-status",
                             style={"fontSize": "11px", "color": "var(--text-muted)",
                                    "marginTop": "4px", "textAlign": "center"}),
                ]),

                # Action buttons
                html.Div(style={"display": "flex", "gap": "10px"}, children=[
                    dbc.Button(
                        [html.Span("⚡ ", style={"marginRight": "4px"}), "Price"],
                        id="btn-price",
                        className="btn-price",
                        style={"flex": "1"},
                    ),
                    dbc.Button(
                        "▦ Compare",
                        id="btn-compare",
                        className="btn-secondary",
                    ),
                    dbc.Button(
                        "∂ Greeks",
                        id="btn-greeks",
                        className="btn-secondary",
                    ),
                    dbc.Button(
                        "📥 Excel",
                        id="btn-export-excel",
                        className="btn-secondary",
                    ),
                ]),
            ]),
        ]),

        # Download component (invisible)
        dcc.Download(id="download-excel"),

        # ── Results area ──────────────────────────────────────────
        dcc.Loading(
            id="results-loading",
            type="circle",
            color="#f59e0b",
            children=html.Div(id="results-container", style={"marginTop": "24px"}),
        ),

        # Hidden stores
        dcc.Store(id="store-price-result"),
        dcc.Store(id="store-greeks-result"),
        dcc.Store(id="store-compare-result"),

        # Hidden defaults for engine-specific params (always in DOM)
        html.Div(style={"display": "none"}, children=[
            dcc.Store(id="mc-num-paths", data=10000),
            dcc.Store(id="mc-rng-type", data="pseudorandom"),
            dcc.Store(id="fd-grid-points", data=100),
        ]),
    ])


def equity_market_data():
    """Market data form for equity options — spot, vol, div yield."""
    return html.Div([
        html.Div("MARKET DATA — EQUITY", className="panel-header"),
        dbc.Row([
            dbc.Col(form_field("Pricing Date",
                text_input("mkt-pricing-date", "2025-01-15")), width=6),
            dbc.Col(form_field("Risk-Free Rate",
                text_input("mkt-rate", "0.045", type="number")), width=6),
        ]),
        dbc.Row([
            dbc.Col(form_field("Spot Price",
                text_input("mkt-spot", "185", type="number")), width=4),
            dbc.Col(form_field("Volatility",
                text_input("mkt-vol", "0.25", type="number")), width=4),
            dbc.Col(form_field("Div Yield",
                text_input("mkt-div", "0.005", type="number")), width=4),
        ]),
    ])


def rates_market_data():
    """Market data form for rates instruments — just rate and date."""
    return html.Div([
        html.Div("MARKET DATA — RATES", className="panel-header"),
        dbc.Row([
            dbc.Col(form_field("Pricing Date",
                text_input("mkt-pricing-date", "2025-01-15")), width=6),
            dbc.Col(form_field("Discount Rate",
                text_input("mkt-rate", "0.045", type="number")), width=6),
        ]),
        html.Div(style={
            "padding": "12px 0", "fontSize": "12px",
            "color": "var(--text-muted)", "fontStyle": "italic",
        }, children=[
            "Rates instruments use the discount curve directly. ",
            "Spot / Vol / Div Yield are not applicable.",
        ]),
        # Hidden fields so callbacks can still read mkt-spot, mkt-vol, mkt-div
        html.Div(style={"display": "none"}, children=[
            dbc.Input(id="mkt-spot", value="100", type="hidden"),
            dbc.Input(id="mkt-vol", value="0.2", type="hidden"),
            dbc.Input(id="mkt-div", value="0", type="hidden"),
        ]),
    ])


def fx_market_data():
    """Market data form for FX instruments — spot from pair, rates/vol in form."""
    return html.Div([
        html.Div("MARKET DATA — FX", className="panel-header"),
        dbc.Row([
            dbc.Col(form_field("Pricing Date",
                text_input("mkt-pricing-date", "2025-01-15")), width=6),
            dbc.Col(form_field("FX Spot Rate",
                text_input("mkt-spot", "1.08", type="number")), width=6),
        ]),
        html.Div(style={
            "padding": "12px 0", "fontSize": "12px",
            "color": "var(--text-muted)", "fontStyle": "italic",
        }, children=[
            "FX rates (domestic/foreign) and vol are set in the instrument form. ",
            "Spot rate = price of 1 unit of foreign ccy in domestic ccy.",
        ]),
        # Hidden fields for callbacks
        html.Div(style={"display": "none"}, children=[
            dbc.Input(id="mkt-rate", value="0.045", type="hidden"),
            dbc.Input(id="mkt-vol", value="0.08", type="hidden"),
            dbc.Input(id="mkt-div", value="0.035", type="hidden"),
        ]),
    ])
