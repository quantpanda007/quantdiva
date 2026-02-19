"""
QuantPricer — Dash Frontend

Multi-page Dash app with sidebar navigation.

Run:
    cd frontend/dash
    python app.py

Opens at http://localhost:8050
Backend must be running at http://localhost:8000
"""

from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
from dash import html, dcc, Input, Output, callback

from components.components import sidebar, NAV_ITEMS
from pages import pricer, registry, risk_lab

# Import callbacks to register them
import callbacks.pricer_callbacks   # noqa: F401
import callbacks.registry_callbacks  # noqa: F401
import callbacks.risk_callbacks      # noqa: F401


# App
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY],
    suppress_callback_exceptions=True,
    title="QuantPricer",
    update_title="Pricing...",
)

server = app.server


# Layout
app.layout = html.Div([
    dcc.Location(id="url", refresh=False),
    sidebar(),
    html.Div(id="page-content", className="main-content"),
])


# Page routing
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
    else:
        return pricer.layout()


# Highlight active nav link
@callback(
    Output("nav-pricer", "className"),
    Output("nav-registry", "className"),
    Output("nav-risk", "className"),
    Input("url", "pathname"),
)
def update_nav_active(pathname):
    base = "sidebar-link"
    active = "sidebar-link active"

    if pathname == "/registry":
        return base, active, base
    elif pathname == "/risk":
        return base, base, active
    return active, base, base


# Run
if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("  QuantPricer Dashboard")
    print("  http://localhost:8050")
    print("  Backend: http://localhost:8000")
    print("=" * 50 + "\n")

    app.run(debug=True, port=8050)