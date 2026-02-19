"""
Registry page — explore instruments, engines, compatibility, scenarios.
"""

from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import html, dcc


def layout():
    return html.Div([
        html.H1("Registry", className="page-title"),
        html.P("Registered instruments, models, engines, and their compatibility",
               className="page-subtitle"),

        # Tabs
        dbc.Tabs(id="registry-tabs", active_tab="tab-compat", children=[
            dbc.Tab(label="Engine Compatibility", tab_id="tab-compat"),
            dbc.Tab(label="Instruments", tab_id="tab-instruments"),
            dbc.Tab(label="Scenarios", tab_id="tab-scenarios"),
        ]),

        # Tab content
        dcc.Loading(
            type="circle",
            color="#f59e0b",
            children=html.Div(id="registry-tab-content", style={"marginTop": "20px"}),
        ),
    ])