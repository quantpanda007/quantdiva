"""
Market Tools callbacks.

Vol surface builder (3D plot), yield curve chart, implied vol solver.
"""

from __future__ import annotations

import numpy as np
from dash import Input, Output, State, callback, html, dcc, no_update
import dash_bootstrap_components as dbc
import plotly.graph_objects as go

from components.components import error_alert
from services.api_client import api_client, APIError
from pages.market_tools import vol_surface_tab, yield_curve_tab, implied_vol_tab


# --- Tab routing ---

@callback(
    Output("market-tab-content", "children"),
    Input("market-tabs", "active_tab"),
)
def render_market_tab(active_tab):
    if active_tab == "tab-vol-surface":
        return vol_surface_tab()
    elif active_tab == "tab-yield-curve":
        return yield_curve_tab()
    elif active_tab == "tab-implied-vol":
        return implied_vol_tab()
    return vol_surface_tab()


# --- Build vol surface ---

@callback(
    Output("vs-results-container", "children"),
    Input("btn-build-surface", "n_clicks"),
    State("vs-pricing-date", "value"),
    State("vs-underlying", "value"),
    State("vs-spot", "value"),
    State("vs-rate", "value"),
    State("vs-div", "value"),
    State("vs-method", "value"),
    State("vs-strikes", "value"),
    State("vs-expiries", "value"),
    State("vs-vol-matrix", "value"),
    prevent_initial_call=True,
)
def build_vol_surface(n_clicks, pricing_date, underlying, spot, rate, div_yield,
                      method, strikes_str, expiries_str, vol_matrix_str):
    if not n_clicks:
        return no_update

    try:
        # Parse inputs
        strikes = [float(s.strip()) for s in strikes_str.split(",")]
        expiries = [e.strip() for e in expiries_str.split(",")]

        # Parse vol matrix: rows separated by ; or newlines
        rows = vol_matrix_str.replace("\n", ";").split(";")
        vol_matrix = []
        for row in rows:
            row = row.strip()
            if row:
                vol_matrix.append([float(v.strip()) for v in row.split(",")])

        # Validate dimensions
        if len(vol_matrix) != len(expiries):
            return error_alert(
                f"Matrix rows ({len(vol_matrix)}) must match expiry count ({len(expiries)})")
        for i, row in enumerate(vol_matrix):
            if len(row) != len(strikes):
                return error_alert(
                    f"Row {i+1} has {len(row)} values, expected {len(strikes)} (strike count)")

        # Call API
        payload = {
            "pricing_date": pricing_date,
            "underlying": underlying,
            "spot": float(spot),
            "rate": float(rate),
            "div_yield": float(div_yield or 0),
            "strikes": strikes,
            "expiry_dates": expiries,
            "vol_matrix": vol_matrix,
            "method": method,
        }

        result = api_client.build_vol_surface(payload)

        # Build 3D surface plot from the input data
        return _render_vol_surface(strikes, expiries, vol_matrix, result, float(spot))

    except APIError as e:
        return error_alert(e.detail)
    except Exception as e:
        return error_alert(str(e))


def _render_vol_surface(strikes, expiries, vol_matrix, api_result, spot):
    """Render 3D vol surface + smile slices + fit report."""

    vol_array = np.array(vol_matrix) * 100  # Convert to %

    # 3D Surface
    fig_3d = go.Figure()
    fig_3d.add_trace(go.Surface(
        x=strikes,
        y=list(range(len(expiries))),
        z=vol_array,
        colorscale=[
            [0, "#0a0e17"],
            [0.25, "#1e3a5f"],
            [0.5, "#3b82f6"],
            [0.75, "#f59e0b"],
            [1, "#ef4444"],
        ],
        colorbar=dict(title="Vol (%)", tickfont=dict(color="#e2e8f0")),
    ))

    fig_3d.update_layout(
        title=dict(text="Implied Vol Surface",
                   font=dict(size=16, family="Space Grotesk", color="#e2e8f0")),
        scene=dict(
            xaxis=dict(title="Strike", backgroundcolor="#0a0e17",
                       gridcolor="#1e293b", color="#e2e8f0"),
            yaxis=dict(title="Expiry", backgroundcolor="#0a0e17",
                       gridcolor="#1e293b", color="#e2e8f0",
                       tickvals=list(range(len(expiries))),
                       ticktext=[e[-5:] for e in expiries]),
            zaxis=dict(title="Vol (%)", backgroundcolor="#0a0e17",
                       gridcolor="#1e293b", color="#e2e8f0"),
            bgcolor="#0a0e17",
        ),
        paper_bgcolor="#111827",
        font=dict(color="#e2e8f0"),
        margin=dict(t=50, b=10, l=10, r=10),
        height=450,
    )

    # Smile slices (2D)
    fig_smile = go.Figure()
    colors = ["#f59e0b", "#3b82f6", "#22c55e", "#a78bfa", "#ef4444", "#06b6d4"]

    for i, expiry in enumerate(expiries):
        fig_smile.add_trace(go.Scatter(
            x=strikes,
            y=vol_array[i],
            mode="lines+markers",
            name=expiry,
            line=dict(color=colors[i % len(colors)], width=2),
            marker=dict(size=5),
        ))

    # ATM line
    fig_smile.add_vline(x=spot, line=dict(color="#f59e0b", width=1, dash="dash"),
                        annotation_text="ATM", annotation_font_color="#f59e0b")

    fig_smile.update_layout(
        title=dict(text="Smile by Expiry",
                   font=dict(size=14, family="Space Grotesk")),
        plot_bgcolor="#0a0e17", paper_bgcolor="#111827",
        font=dict(color="#e2e8f0", family="JetBrains Mono", size=11),
        xaxis=dict(title="Strike", gridcolor="#1e293b"),
        yaxis=dict(title="Vol (%)", gridcolor="#1e293b"),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
        margin=dict(t=50, b=50),
        height=350,
    )

    # Fit report
    fit_report = api_result.get("fit_report", [])
    report_el = html.Div()
    if fit_report:
        header = html.Thead(html.Tr([
            html.Th("Expiry"), html.Th("RMSE"), html.Th("Arb-Free"), html.Th("Params"),
        ]))
        rows = []
        for fr in fit_report:
            rows.append(html.Tr([
                html.Td(f"{fr.get('T', 0):.3f}y"),
                html.Td(f"{fr.get('rmse', 0):.6f}"),
                html.Td(
                    "✓" if fr.get("arbitrage_free", False) else "✗",
                    className="text-green" if fr.get("arbitrage_free") else "text-red",
                ),
                html.Td(
                    f"a={fr.get('a', 0):.4f} b={fr.get('b', 0):.4f} "
                    f"ρ={fr.get('rho', 0):.4f}",
                    style={"fontSize": "10px", "color": "var(--text-muted)"},
                ),
            ]))
        report_el = html.Div(className="panel",
                             style={"padding": "0", "overflow": "hidden", "marginTop": "16px"},
                             children=[
            html.Div("SVI FIT REPORT", className="panel-header",
                     style={"padding": "12px 20px 6px"}),
            dbc.Table([header, html.Tbody(rows)],
                      bordered=False, hover=True, className="table"),
        ])

    # Summary card
    summary = html.Div(className="npv-card", style={"marginBottom": "16px"}, children=[
        html.Div(className="npv-header", children=[
            html.Div("VOL SURFACE BUILT", className="npv-label"),
            html.Div(
                f"{api_result.get('num_expiries', 0)} expiries × "
                f"{api_result.get('num_strikes', 0)} strikes",
                style={"fontSize": "20px", "fontWeight": "600",
                       "color": "var(--accent)", "fontFamily": "var(--font-display)"},
            ),
            html.Div(f"Method: {api_result.get('method', 'unknown').upper()}",
                     className="npv-meta"),
        ]),
    ])

    return html.Div([
        summary,
        html.Div(className="panel", style={"padding": "0"}, children=[
            dcc.Graph(figure=fig_3d, config={"displayModeBar": True}),
        ]),
        html.Div(className="panel", style={"padding": "0", "marginTop": "16px"}, children=[
            dcc.Graph(figure=fig_smile, config={"displayModeBar": False}),
        ]),
        report_el,
    ])


# --- Yield curve query ---

@callback(
    Output("yc-results-container", "children"),
    Input("btn-query-curve", "n_clicks"),
    State("yc-pricing-date", "value"),
    State("yc-rate", "value"),
    State("yc-tenors", "value"),
    prevent_initial_call=True,
)
def query_yield_curve(n_clicks, pricing_date, rate, tenors_str):
    if not n_clicks:
        return no_update

    try:
        tenors = [float(t.strip()) for t in tenors_str.split(",")]

        payload = {
            "market_data": {
                "pricing_date": pricing_date,
                "underlyings": {"DUMMY": {"spot": 100, "vol": 0.2, "div_yield": 0}},
                "rate": float(rate),
            },
            "tenors": tenors,
        }

        result = api_client.query_yield_curve(payload)
        data = result.get("results", [])

        if not data:
            return error_alert("No curve data returned")

        tenors_out = [d["T"] for d in data]
        zero_rates = [d["zero_rate"] * 100 for d in data]
        discounts = [d["discount_factor"] for d in data]

        # Zero rate chart
        fig_rate = go.Figure()
        fig_rate.add_trace(go.Scatter(
            x=tenors_out, y=zero_rates,
            mode="lines+markers",
            line=dict(color="#f59e0b", width=2),
            marker=dict(size=6, color="#f59e0b"),
            name="Zero Rate",
        ))
        fig_rate.update_layout(
            title=dict(text="Zero Rate Curve",
                       font=dict(size=14, family="Space Grotesk")),
            plot_bgcolor="#0a0e17", paper_bgcolor="#111827",
            font=dict(color="#e2e8f0", family="JetBrains Mono", size=11),
            xaxis=dict(title="Tenor (years)", gridcolor="#1e293b"),
            yaxis=dict(title="Zero Rate (%)", gridcolor="#1e293b"),
            margin=dict(t=50, b=50),
            height=350,
        )

        # Discount factor chart
        fig_disc = go.Figure()
        fig_disc.add_trace(go.Scatter(
            x=tenors_out, y=discounts,
            mode="lines+markers",
            line=dict(color="#3b82f6", width=2),
            marker=dict(size=6, color="#3b82f6"),
            name="Discount Factor",
            fill="tozeroy",
            fillcolor="rgba(59, 130, 246, 0.1)",
        ))
        fig_disc.update_layout(
            title=dict(text="Discount Factors",
                       font=dict(size=14, family="Space Grotesk")),
            plot_bgcolor="#0a0e17", paper_bgcolor="#111827",
            font=dict(color="#e2e8f0", family="JetBrains Mono", size=11),
            xaxis=dict(title="Tenor (years)", gridcolor="#1e293b"),
            yaxis=dict(title="Discount Factor", gridcolor="#1e293b"),
            margin=dict(t=50, b=50),
            height=350,
        )

        # Data table
        header = html.Thead(html.Tr([
            html.Th("Tenor"), html.Th("Zero Rate"), html.Th("Discount Factor"),
        ]))
        rows = [html.Tr([
            html.Td(f"{d['T']:.2f}y"),
            html.Td(f"{d['zero_rate']*100:.4f}%", className="text-accent"),
            html.Td(f"{d['discount_factor']:.6f}"),
        ]) for d in data]

        return html.Div([
            html.Div(className="panel", style={"padding": "0"}, children=[
                dcc.Graph(figure=fig_rate, config={"displayModeBar": False}),
            ]),
            html.Div(className="panel", style={"padding": "0", "marginTop": "16px"}, children=[
                dcc.Graph(figure=fig_disc, config={"displayModeBar": False}),
            ]),
            html.Div(className="panel",
                     style={"padding": "0", "overflow": "hidden", "marginTop": "16px"},
                     children=[
                html.Div("CURVE DATA", className="panel-header",
                         style={"padding": "12px 20px 6px"}),
                dbc.Table([header, html.Tbody(rows)],
                          bordered=False, hover=True, className="table"),
            ]),
        ])

    except APIError as e:
        return error_alert(e.detail)
    except Exception as e:
        return error_alert(str(e))


# --- Implied vol solver ---

@callback(
    Output("iv-results-container", "children"),
    Input("btn-solve-iv", "n_clicks"),
    State("iv-price", "value"),
    State("iv-spot", "value"),
    State("iv-strike", "value"),
    State("iv-T", "value"),
    State("iv-rate", "value"),
    State("iv-div", "value"),
    State("iv-type", "value"),
    State("iv-method", "value"),
    prevent_initial_call=True,
)
def solve_implied_vol(n_clicks, price, spot, strike, T, rate, div_yield,
                      option_type, method):
    if not n_clicks:
        return no_update

    try:
        payload = {
            "market_price": float(price),
            "spot": float(spot),
            "strike": float(strike),
            "T": float(T),
            "rate": float(rate),
            "div_yield": float(div_yield or 0),
            "is_call": option_type == "call",
            "method": method,
        }

        result = api_client.compute_implied_vol(payload)

        iv = result.get("implied_vol", 0)
        converged = result.get("converged", False)

        return html.Div(className="npv-card", children=[
            html.Div(className="npv-header", children=[
                html.Div("IMPLIED VOLATILITY", className="npv-label"),
                html.Div(
                    f"{iv*100:.4f}%",
                    className="npv-value",
                ),
                html.Div(
                    f"Method: {result.get('method', '')} · "
                    f"Converged: {'✓' if converged else '✗'} · "
                    f"Price: ${float(price):.2f} · "
                    f"S={float(spot)} K={float(strike)} T={float(T)}",
                    className="npv-meta",
                ),
            ]),
            # Visual gauge
            html.Div(style={"padding": "16px 28px"}, children=[
                html.Div(style={
                    "height": "8px", "background": "var(--bg)",
                    "borderRadius": "4px", "overflow": "hidden",
                    "marginTop": "8px",
                }, children=[
                    html.Div(style={
                        "height": "100%",
                        "width": f"{min(iv * 200, 100)}%",
                        "background": "linear-gradient(90deg, #22c55e, #f59e0b, #ef4444)",
                        "borderRadius": "4px",
                        "transition": "width 0.5s",
                    }),
                ]),
                html.Div(
                    style={"display": "flex", "justifyContent": "space-between",
                           "marginTop": "4px", "fontSize": "10px",
                           "color": "var(--text-muted)"},
                    children=[
                        html.Span("0%"),
                        html.Span("25%"),
                        html.Span("50%"),
                    ],
                ),
            ]),
        ])

    except APIError as e:
        return error_alert(e.detail)
    except Exception as e:
        return error_alert(str(e))
