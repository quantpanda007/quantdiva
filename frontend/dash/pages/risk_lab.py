"""
Risk Lab page — scenarios, stress tests, ladders.
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
        html.H1("Risk Lab", className="page-title"),
        html.P("Scenarios, stress tests, and sensitivity analysis",
               className="page-subtitle"),

        # ── Instrument + Market setup (compact) ───────────────────
        dbc.Row([
            dbc.Col(width=6, children=[
                html.Div(className="panel", children=[
                    form_field(
                        "Instrument Type",
                        dropdown("risk-inst-type", INSTRUMENT_TYPES, "vanilla_option"),
                    ),
                    html.Div(id="risk-instrument-form-container",
                             children=build_instrument_form("vanilla_option", page="risk")),
                    dbc.Row([
                        dbc.Col(form_field("Model", dropdown(
                            "risk-model-select", ["black_scholes", "heston"], "black_scholes",
                        )), width=6),
                        dbc.Col(form_field("Engine", dropdown(
                            "risk-engine-select", ["analytic"], "analytic",
                        )), width=6),
                    ]),
                ]),
            ]),
            dbc.Col(width=6, children=[
                html.Div(className="panel", children=[
                    market_data_form(prefix="risk"),
                ]),
            ]),
        ]),

        # ── Risk analysis tabs ────────────────────────────────────
        dbc.Tabs(id="risk-tabs", active_tab="tab-spot-ladder", children=[
            dbc.Tab(label="Spot Ladder", tab_id="tab-spot-ladder"),
            dbc.Tab(label="Vol Ladder", tab_id="tab-vol-ladder"),
            dbc.Tab(label="Stress Test", tab_id="tab-stress"),
            dbc.Tab(label="Custom Scenario", tab_id="tab-scenario"),
        ]),

        # Tab-specific controls
        html.Div(id="risk-tab-controls", style={"marginTop": "16px"}),

        # Run button
        html.Div(style={"marginTop": "16px"}, children=[
            dbc.Button(
                "⚡ Run Analysis",
                id="btn-run-risk",
                className="btn-price",
            ),
        ]),

        # Results
        dcc.Loading(
            type="circle",
            color="#f59e0b",
            children=html.Div(id="risk-results-container", style={"marginTop": "24px"}),
        ),

        # Hidden defaults for tab-specific inputs (always present in DOM)
        # The tab controls update these via separate callbacks
        html.Div(style={"display": "none"}, children=[
            dbc.Input(id="spot-bumps-input", value="-20, -15, -10, -5, -2, 0, 2, 5, 10, 15, 20"),
            dbc.Input(id="vol-bumps-input", value="-10, -5, -2, 0, 2, 5, 10, 15"),
            dbc.Input(id="scenario-spot-shock", value="-10", type="number"),
            dbc.Input(id="scenario-vol-shock", value="5", type="number"),
        ]),
    ])
