"""
Portfolio page — create, manage, value portfolios.
"""

from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import html, dcc

from components.components import (
    form_field, dropdown, text_input,
    build_instrument_form, market_data_form,
)


INSTRUMENT_TYPES = [
    {"label": "VANILLA OPTION",   "value": "vanilla_option"},
    {"label": "BARRIER OPTION",   "value": "barrier_option"},
    {"label": "DIGITAL OPTION",   "value": "digital_option"},
    {"label": "ASIAN OPTION",     "value": "asian_option"},
    {"label": "LOOKBACK OPTION",  "value": "lookback_option"},
    {"label": "INTEREST RATE SWAP", "value": "irs"},
    {"label": "FIXED RATE BOND",  "value": "bond"},
    {"label": "FRA",                "value": "fra"},
    {"label": "CAP / FLOOR",       "value": "cap_floor"},
    {"label": "SWAPTION",          "value": "swaption"},
    {"label": "CDS",               "value": "cds"},
    {"label": "FX FORWARD",        "value": "fx_forward"},
    {"label": "FX OPTION",         "value": "fx_option"},
]


def layout():
    return html.Div([
        html.H1("Portfolio", className="page-title"),
        html.P("Build, value, and stress-test a portfolio of trades",
               className="page-subtitle"),

        dbc.Tabs(id="portfolio-tabs", active_tab="tab-build", children=[
            dbc.Tab(label="Build Portfolio", tab_id="tab-build"),
            dbc.Tab(label="Valuation", tab_id="tab-valuation"),
            dbc.Tab(label="Stress Test", tab_id="tab-pf-stress"),
        ]),

        html.Div(id="portfolio-tab-content", style={"marginTop": "20px"}),

        # Stores
        dcc.Store(id="pf-positions-store", data=[]),
        dcc.Store(id="pf-valuation-store", data=None),
    ])


def build_tab_layout():
    """Build portfolio tab — add positions."""
    return html.Div([
        dbc.Row([
            # Left: instrument form
            dbc.Col(width=6, children=[
                html.Div(className="panel", children=[
                    html.Div("ADD POSITION", className="panel-header"),
                    form_field(
                        "Instrument Type",
                        dropdown("pf-inst-type", INSTRUMENT_TYPES, "vanilla_option"),
                    ),
                    html.Div(id="pf-instrument-form-container",
                             children=build_instrument_form("vanilla_option", page="pf")),
                    dbc.Row([
                        dbc.Col(form_field("Quantity",
                            text_input("pf-quantity", "100", type="number")), width=4),
                        dbc.Col(form_field("Direction",
                            dropdown("pf-direction", ["buy", "sell"], "buy")), width=4),
                        dbc.Col(form_field("Book",
                            text_input("pf-book", "default")), width=4),
                    ]),
                    dbc.Button("+ Add Position", id="btn-add-position",
                               className="btn-price", style={"marginTop": "10px"}),
                ]),
            ]),

            # Right: current positions
            dbc.Col(width=6, children=[
                html.Div(className="panel", children=[
                    html.Div(
                        style={"display": "flex", "justifyContent": "space-between",
                               "alignItems": "center", "marginBottom": "14px"},
                        children=[
                            html.Div("POSITIONS", className="panel-header",
                                     style={"marginBottom": "0"}),
                            dbc.Button("Clear All", id="btn-clear-positions",
                                       className="btn-secondary",
                                       style={"padding": "6px 12px", "fontSize": "11px"}),
                        ],
                    ),
                    html.Div(id="pf-positions-display"),
                    html.Div(id="pf-position-count",
                             style={"marginTop": "10px", "fontSize": "12px",
                                    "color": "var(--text-muted)"}),
                ]),
            ]),
        ]),
    ])


def valuation_tab_layout():
    """Valuation tab — price the portfolio."""
    return html.Div([
        dbc.Row([
            dbc.Col(width=6, children=[
                html.Div(className="panel", children=[
                    market_data_form(prefix="pfmkt"),
                    dbc.Row([
                        dbc.Col(form_field("Model", dropdown(
                            "pf-model-select", ["black_scholes", "heston"],
                            "black_scholes")), width=6),
                        dbc.Col(form_field("Engine", dropdown(
                            "pf-engine-select", ["analytic"], "analytic")), width=6),
                    ]),
                    dbc.Button("⚡ Value Portfolio", id="btn-value-portfolio",
                               className="btn-price", style={"marginTop": "10px"}),
                ]),
            ]),
            dbc.Col(width=6, children=[
                html.Div(id="pf-positions-summary", className="panel",
                         children=[html.Div("Add positions in Build tab first",
                                           style={"color": "var(--text-muted)"})]),
            ]),
        ]),

        dcc.Loading(
            type="circle", color="#f59e0b",
            children=html.Div(id="pf-valuation-results", style={"marginTop": "16px"}),
        ),
    ])


def stress_tab_layout():
    """Stress test tab."""
    return html.Div([
        dbc.Row([
            dbc.Col(width=6, children=[
                html.Div(className="panel", children=[
                    market_data_form(prefix="pfstress"),
                    dbc.Row([
                        dbc.Col(form_field("Model", dropdown(
                            "pfstress-model", ["black_scholes"], "black_scholes")), width=6),
                        dbc.Col(form_field("Engine", dropdown(
                            "pfstress-engine", ["analytic"], "analytic")), width=6),
                    ]),
                    dbc.Button("⚡ Run Stress Test", id="btn-pf-stress",
                               className="btn-price", style={"marginTop": "10px"}),
                ]),
            ]),
        ]),
        dcc.Loading(
            type="circle", color="#f59e0b",
            children=html.Div(id="pf-stress-results", style={"marginTop": "16px"}),
        ),
    ])
