"""
Market Tools page — vol surface builder, yield curve query.
"""

from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import html, dcc

from components.components import form_field, text_input, dropdown


def layout():
    return html.Div([
        html.H1("Market Tools", className="page-title"),
        html.P("Vol surface construction, yield curve analysis",
               className="page-subtitle"),

        dbc.Tabs(id="market-tabs", active_tab="tab-vol-surface", children=[
            dbc.Tab(label="Vol Surface", tab_id="tab-vol-surface"),
            dbc.Tab(label="Yield Curve", tab_id="tab-yield-curve"),
            dbc.Tab(label="Implied Vol", tab_id="tab-implied-vol"),
        ]),

        html.Div(id="market-tab-content", style={"marginTop": "20px"}),
    ])


def vol_surface_tab():
    """Vol surface builder with SVI calibration."""
    return html.Div([
        dbc.Row([
            dbc.Col(width=5, children=[
                html.Div(className="panel", children=[
                    html.Div("SURFACE PARAMETERS", className="panel-header"),
                    dbc.Row([
                        dbc.Col(form_field("Pricing Date",
                            text_input("vs-pricing-date", "2025-01-15")), width=6),
                        dbc.Col(form_field("Underlying",
                            text_input("vs-underlying", "SPX")), width=6),
                    ]),
                    dbc.Row([
                        dbc.Col(form_field("Spot",
                            text_input("vs-spot", "5800", type="number")), width=4),
                        dbc.Col(form_field("Rate",
                            text_input("vs-rate", "0.045", type="number")), width=4),
                        dbc.Col(form_field("Div Yield",
                            text_input("vs-div", "0.015", type="number")), width=4),
                    ]),
                    form_field("Method", dropdown("vs-method",
                        [{"label": "SVI Calibration", "value": "svi"},
                         {"label": "Grid Interpolation", "value": "grid"}],
                        "svi")),

                    html.Div("MARKET QUOTES", className="panel-header",
                             style={"marginTop": "16px"}),
                    html.P("Strikes (comma-separated)", className="form-label"),
                    dbc.Textarea(
                        id="vs-strikes",
                        value="5200, 5400, 5500, 5600, 5700, 5800, 5900, 6000, 6100, 6200, 6400",
                        className="form-control",
                        style={"background": "var(--bg)", "color": "var(--text)",
                               "height": "50px", "fontFamily": "var(--font-mono)",
                               "fontSize": "12px"},
                    ),
                    html.P("Expiry Dates (comma-separated)", className="form-label",
                           style={"marginTop": "10px"}),
                    dbc.Textarea(
                        id="vs-expiries",
                        value="2025-04-15, 2025-07-15, 2025-10-15, 2026-01-15",
                        className="form-control",
                        style={"background": "var(--bg)", "color": "var(--text)",
                               "height": "50px", "fontFamily": "var(--font-mono)",
                               "fontSize": "12px"},
                    ),
                    html.P("Vol Matrix (rows=expiries, cols=strikes, comma-separated, semicolon between rows)",
                           className="form-label", style={"marginTop": "10px"}),
                    dbc.Textarea(
                        id="vs-vol-matrix",
                        value=(
                            "0.28, 0.24, 0.22, 0.20, 0.19, 0.18, 0.18, 0.19, 0.20, 0.21, 0.24;\n"
                            "0.27, 0.23, 0.21, 0.20, 0.19, 0.18, 0.18, 0.18, 0.19, 0.20, 0.23;\n"
                            "0.26, 0.23, 0.21, 0.19, 0.18, 0.17, 0.17, 0.18, 0.19, 0.20, 0.22;\n"
                            "0.25, 0.22, 0.20, 0.19, 0.18, 0.17, 0.17, 0.17, 0.18, 0.19, 0.22"
                        ),
                        className="form-control",
                        style={"background": "var(--bg)", "color": "var(--text)",
                               "height": "120px", "fontFamily": "var(--font-mono)",
                               "fontSize": "11px"},
                    ),

                    dbc.Button("⚡ Build Surface", id="btn-build-surface",
                               className="btn-price", style={"marginTop": "16px"}),
                ]),
            ]),

            dbc.Col(width=7, children=[
                dcc.Loading(
                    type="circle", color="#f59e0b",
                    children=html.Div(id="vs-results-container"),
                ),
            ]),
        ]),
    ])


def yield_curve_tab():
    """Yield curve query."""
    return html.Div([
        dbc.Row([
            dbc.Col(width=5, children=[
                html.Div(className="panel", children=[
                    html.Div("YIELD CURVE QUERY", className="panel-header"),
                    dbc.Row([
                        dbc.Col(form_field("Pricing Date",
                            text_input("yc-pricing-date", "2025-01-15")), width=6),
                        dbc.Col(form_field("Flat Rate",
                            text_input("yc-rate", "0.045", type="number")), width=6),
                    ]),
                    form_field("Tenors (years, comma-separated)",
                        text_input("yc-tenors", "0.25, 0.5, 1, 2, 3, 5, 7, 10, 15, 20, 30")),

                    dbc.Button("⚡ Query Curve", id="btn-query-curve",
                               className="btn-price", style={"marginTop": "10px"}),
                ]),
            ]),
            dbc.Col(width=7, children=[
                dcc.Loading(
                    type="circle", color="#f59e0b",
                    children=html.Div(id="yc-results-container"),
                ),
            ]),
        ]),
    ])


def implied_vol_tab():
    """Implied vol solver."""
    return html.Div([
        dbc.Row([
            dbc.Col(width=5, children=[
                html.Div(className="panel", children=[
                    html.Div("IMPLIED VOL SOLVER", className="panel-header"),
                    dbc.Row([
                        dbc.Col(form_field("Market Price",
                            text_input("iv-price", "12.50", type="number")), width=6),
                        dbc.Col(form_field("Spot",
                            text_input("iv-spot", "185", type="number")), width=6),
                    ]),
                    dbc.Row([
                        dbc.Col(form_field("Strike",
                            text_input("iv-strike", "185", type="number")), width=4),
                        dbc.Col(form_field("Time (yrs)",
                            text_input("iv-T", "1.0", type="number")), width=4),
                        dbc.Col(form_field("Rate",
                            text_input("iv-rate", "0.045", type="number")), width=4),
                    ]),
                    dbc.Row([
                        dbc.Col(form_field("Div Yield",
                            text_input("iv-div", "0.005", type="number")), width=4),
                        dbc.Col(form_field("Option Type",
                            dropdown("iv-type", ["call", "put"], "call")), width=4),
                        dbc.Col(form_field("Method",
                            dropdown("iv-method",
                                     ["newton", "bisection", "brent"], "newton")), width=4),
                    ]),

                    dbc.Button("⚡ Solve", id="btn-solve-iv",
                               className="btn-price", style={"marginTop": "10px"}),
                ]),
            ]),
            dbc.Col(width=7, children=[
                html.Div(id="iv-results-container"),
            ]),
        ]),
    ])