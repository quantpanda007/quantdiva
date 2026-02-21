"""
Dashboard page — landing page with system overview and quick price.
"""

from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import html, dcc

from components.components import form_field, dropdown, text_input


def layout():
    return html.Div([
        # Hero header
        html.Div(style={
            "padding": "32px 0 24px",
            "borderBottom": "1px solid var(--border)",
            "marginBottom": "28px",
        }, children=[
            html.H1("QuantPricer", style={
                "fontFamily": "var(--font-display)", "fontSize": "36px",
                "fontWeight": "700", "color": "var(--text)", "margin": "0",
            }),
            html.P("QuantLib-based Derivatives Pricing Platform", style={
                "color": "var(--text-muted)", "fontSize": "14px", "margin": "6px 0 0",
            }),
        ]),

        # Status cards row
        html.Div(id="dash-status-cards", style={"marginBottom": "24px"}),

        dbc.Row([
            # Left: Quick Pricer
            dbc.Col(width=7, children=[
                html.Div(className="panel", children=[
                    html.Div("QUICK PRICE", className="panel-header"),
                    dbc.Row([
                        dbc.Col(form_field("Type", dropdown("qp-type",
                            [{"label": "VANILLA CALL", "value": "call"},
                             {"label": "VANILLA PUT", "value": "put"}],
                            "call")), width=3),
                        dbc.Col(form_field("Spot",
                            text_input("qp-spot", "185", type="number")), width=2),
                        dbc.Col(form_field("Strike",
                            text_input("qp-strike", "185", type="number")), width=2),
                        dbc.Col(form_field("Vol",
                            text_input("qp-vol", "0.25", type="number")), width=2),
                        dbc.Col(form_field("Expiry",
                            text_input("qp-expiry", "2026-01-15")), width=3),
                    ]),
                    dbc.Button("⚡ Price", id="btn-quick-price",
                               className="btn-price",
                               style={"marginTop": "4px"}),
                    html.Div(id="qp-result", style={"marginTop": "16px"}),
                ]),
            ]),

            # Right: Platform info
            dbc.Col(width=5, children=[
                html.Div(className="panel", children=[
                    html.Div("PLATFORM", className="panel-header"),
                    _info_row("Version", "0.2.0"),
                    _info_row("Backend", "FastAPI + QuantLib"),
                    _info_row("Frontend", "Dash + Plotly"),
                    _info_row("Python", "3.11"),
                ]),

                html.Div(className="panel", style={"marginTop": "16px"}, children=[
                    html.Div("CAPABILITIES", className="panel-header"),
                    _capability_item("⚡", "Pricing",
                        "Vanilla, Barrier, Digital, Asian, Lookback"),
                    _capability_item("∂", "Greeks",
                        "Delta, Gamma, Vega, Theta, Rho (bump & reprice)"),
                    _capability_item("⚠", "Risk",
                        "Scenarios, Stress Tests, VaR, P&L Explain"),
                    _capability_item("📈", "Market",
                        "SVI Vol Surface, Yield Curves, Implied Vol"),
                    _capability_item("📋", "Portfolio",
                        "Multi-trade books, aggregated Greeks"),
                ]),
            ]),
        ]),

        # Navigation shortcuts
        html.Div(style={"marginTop": "24px"}, children=[
            html.Div("NAVIGATE", className="panel-header"),
            dbc.Row([
                dbc.Col(_nav_card("⚡ Pricer",
                    "Price any registered instrument with real-time Greeks",
                    "/"), width=3),
                dbc.Col(_nav_card("⚠ Risk Lab",
                    "Spot/vol ladders, stress tests, custom scenarios",
                    "/risk"), width=3),
                dbc.Col(_nav_card("📋 Portfolio",
                    "Build, value, and stress-test trade books",
                    "/portfolio"), width=3),
                dbc.Col(_nav_card("📈 Market Tools",
                    "Vol surface builder, yield curves, implied vol",
                    "/market"), width=3),
            ]),
        ]),
    ])


def _info_row(label, value):
    return html.Div(style={
        "display": "flex", "justifyContent": "space-between",
        "padding": "6px 0", "borderBottom": "1px solid rgba(30,41,59,0.2)",
        "fontSize": "12px",
    }, children=[
        html.Span(label, style={"color": "var(--text-muted)"}),
        html.Span(value, style={"color": "var(--text)", "fontWeight": "600"}),
    ])


def _capability_item(icon, title, desc):
    return html.Div(style={
        "display": "flex", "gap": "10px", "padding": "8px 0",
        "borderBottom": "1px solid rgba(30,41,59,0.2)",
    }, children=[
        html.Span(icon, style={"fontSize": "16px", "minWidth": "20px"}),
        html.Div([
            html.Div(title, style={"fontSize": "13px", "fontWeight": "600",
                                    "color": "var(--text)"}),
            html.Div(desc, style={"fontSize": "11px", "color": "var(--text-muted)"}),
        ]),
    ])


def _nav_card(title, desc, href):
    return dcc.Link(href=href, style={"textDecoration": "none"}, children=[
        html.Div(className="panel", style={
            "cursor": "pointer", "transition": "all 0.15s",
            "minHeight": "100px",
        }, children=[
            html.Div(title, style={
                "fontSize": "15px", "fontWeight": "700",
                "color": "var(--accent)", "marginBottom": "6px",
            }),
            html.Div(desc, style={
                "fontSize": "11px", "color": "var(--text-muted)",
                "lineHeight": "1.4",
            }),
        ]),
    ])
