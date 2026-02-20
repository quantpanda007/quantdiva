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
from pages import pricer, registry, risk_lab, portfolio

import callbacks.pricer_callbacks    # noqa: F401
import callbacks.registry_callbacks  # noqa: F401
import callbacks.risk_callbacks      # noqa: F401
import callbacks.portfolio_callbacks # noqa: F401


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
    if pathname == "/" or pathname == "/pricer":
        return pricer.layout()
    elif pathname == "/registry":
        return registry.layout()
    elif pathname == "/risk":
        return risk_lab.layout()
    elif pathname == "/portfolio":
        return portfolio.layout()
    return pricer.layout()


@callback(
    Output("nav-pricer", "className"),
    Output("nav-risk", "className"),
    Output("nav-portfolio", "className"),
    Output("nav-registry", "className"),
    Input("url", "pathname"),
)
def update_nav_active(pathname):
    base = "sidebar-link"
    active = "sidebar-link active"
    states = [base, base, base, base]

    if pathname == "/risk":
        states[1] = active
    elif pathname == "/portfolio":
        states[2] = active
    elif pathname == "/registry":
        states[3] = active
    else:
        states[0] = active

    return tuple(states)


if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("  QuantPricer Dashboard")
    print("  http://localhost:8050")
    print("  Backend: http://localhost:8000")
    print("=" * 50 + "\n")
    app.run(debug=True, port=8050)