"""
QuantPricer — Dash Frontend

Run:
    cd frontend/dash
    python app.py
"""

from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
from dash import html, dcc, Input, Output, callback

from components.components import sidebar
from pages import dashboard, pricer, registry, risk_lab, portfolio, market_tools

import callbacks.dashboard_callbacks  # noqa: F401
import callbacks.pricer_callbacks     # noqa: F401
import callbacks.registry_callbacks   # noqa: F401
import callbacks.risk_callbacks       # noqa: F401
import callbacks.portfolio_callbacks  # noqa: F401
import callbacks.market_callbacks     # noqa: F401


app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY],
    suppress_callback_exceptions=True,
    title="QuantPricer",
    update_title="Pricing...",
)
server = app.server

app.layout = html.Div([
    dcc.Location(id="url", refresh=False),
    sidebar(),
    html.Div(id="page-content", className="main-content"),
])


@callback(
    Output("page-content", "children"),
    Input("url", "pathname"),
)
def display_page(pathname):
    if pathname == "/" or pathname == "/dashboard":
        return dashboard.layout()
    elif pathname == "/pricer":
        return pricer.layout()
    elif pathname == "/registry":
        return registry.layout()
    elif pathname == "/risk":
        return risk_lab.layout()
    elif pathname == "/portfolio":
        return portfolio.layout()
    elif pathname == "/market":
        return market_tools.layout()
    return dashboard.layout()


@callback(
    Output("nav-dashboard", "className"),
    Output("nav-pricer", "className"),
    Output("nav-risk", "className"),
    Output("nav-portfolio", "className"),
    Output("nav-market", "className"),
    Output("nav-registry", "className"),
    Input("url", "pathname"),
)
def update_nav_active(pathname):
    base = "sidebar-link"
    active = "sidebar-link active"
    s = [base] * 6

    mapping = {
        "/pricer": 1, "/risk": 2, "/portfolio": 3,
        "/market": 4, "/registry": 5,
    }
    idx = mapping.get(pathname, 0)
    s[idx] = active

    return tuple(s)


if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("  QuantPricer Dashboard")
    print("  http://localhost:8050")
    print("  Backend: http://localhost:8000")
    print("=" * 50 + "\n")
    app.run(debug=True, port=8050)
