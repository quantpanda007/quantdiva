"""
Pricer page — price any instrument with Greeks and engine comparison.
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
]


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
                             children=build_instrument_form("vanilla_option")),
                ]),

                # Model & Engine
                html.Div(className="panel", children=[
                    dbc.Row([
                        dbc.Col(form_field("Model", dropdown(
                            "model-select",
                            ["black_scholes", "heston"],
                            "black_scholes",
                        )), width=6),
                        dbc.Col(form_field("Engine", dropdown(
                            "engine-select",
                            ["analytic"],
                            "analytic",
                        )), width=6),
                    ]),
                ]),
            ]),

            # ── Right column: market data + actions ───────────────
            dbc.Col(width=6, children=[
                html.Div(className="panel", children=[
                    market_data_form(prefix="mkt"),
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
                ]),
            ]),
        ]),

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
    ])