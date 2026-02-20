"""
Portfolio page callbacks.

Manages portfolio positions client-side via dcc.Store,
then sends to backend for valuation and stress testing.
"""

from __future__ import annotations

import json
from dash import Input, Output, State, callback, html, dcc, no_update, ctx, ALL
import dash_bootstrap_components as dbc
import plotly.graph_objects as go

from components.components import (
    INSTRUMENT_FIELDS, NUMERIC_FIELDS,
    build_instrument_form, collect_market_data, error_alert,
)
from services.api_client import api_client, APIError
from pages.portfolio import build_tab_layout, valuation_tab_layout, stress_tab_layout


# --- Tab routing ---

@callback(
    Output("portfolio-tab-content", "children"),
    Input("portfolio-tabs", "active_tab"),
)
def render_portfolio_tab(active_tab):
    if active_tab == "tab-build":
        return build_tab_layout()
    elif active_tab == "tab-valuation":
        return valuation_tab_layout()
    elif active_tab == "tab-pf-stress":
        return stress_tab_layout()
    return build_tab_layout()


# --- Rebuild instrument form on type change ---

@callback(
    Output("pf-instrument-form-container", "children"),
    Input("pf-inst-type", "value"),
)
def update_pf_instrument_form(inst_type):
    if not inst_type:
        return no_update
    return build_instrument_form(inst_type)


# --- Add position to store ---

@callback(
    Output("pf-positions-store", "data"),
    Input("btn-add-position", "n_clicks"),
    Input("btn-clear-positions", "n_clicks"),
    State("pf-positions-store", "data"),
    State("pf-inst-type", "value"),
    State({"type": "inst-field", "field": ALL}, "value"),
    State("pf-quantity", "value"),
    State("pf-direction", "value"),
    State("pf-book", "value"),
    prevent_initial_call=True,
)
def manage_positions(
    add_clicks, clear_clicks,
    current_positions, inst_type, field_values,
    quantity, direction, book,
):
    triggered = ctx.triggered_id
    positions = current_positions or []

    if triggered == "btn-clear-positions":
        return []

    if triggered == "btn-add-position":
        # Collect instrument params
        fields = INSTRUMENT_FIELDS.get(inst_type, [])
        params = {}
        for i, (name, ftype, default) in enumerate(fields):
            if i < len(field_values):
                val = field_values[i]
            else:
                val = default[0] if isinstance(default, list) else default
            if name in NUMERIC_FIELDS and val is not None:
                try:
                    val = float(val)
                except (ValueError, TypeError):
                    val = 0.0
            params[name] = val

        position = {
            "instrument": {"type": inst_type, "params": params},
            "quantity": float(quantity or 1),
            "direction": direction or "buy",
            "book": book or "default",
        }

        positions.append(position)
        return positions

    return no_update


# --- Display positions ---

@callback(
    Output("pf-positions-display", "children"),
    Output("pf-position-count", "children"),
    Input("pf-positions-store", "data"),
)
def display_positions(positions):
    if not positions:
        return (
            html.Div("No positions yet. Add instruments from the left panel.",
                     style={"color": "var(--text-muted)", "fontSize": "12px", "padding": "20px 0"}),
            ""
        )

    rows = []
    for i, pos in enumerate(positions):
        inst = pos["instrument"]
        params = inst["params"]
        qty = pos["quantity"]
        direction = pos["direction"]
        book = pos["book"]

        sign_color = "text-green" if direction == "buy" else "text-red"
        sign_label = f"+{qty:.0f}" if direction == "buy" else f"-{qty:.0f}"

        # Summary line
        inst_type = inst["type"].replace("_", " ").upper()
        detail_parts = []
        if "underlying" in params:
            detail_parts.append(params["underlying"])
        if "strike" in params:
            detail_parts.append(f"K={params['strike']}")
        if "expiry" in params:
            detail_parts.append(params["expiry"])
        if "option_type" in params:
            detail_parts.append(params["option_type"].upper())
        if "barrier_type" in params:
            detail_parts.append(params["barrier_type"])
        if "barrier_level" in params:
            detail_parts.append(f"B={params['barrier_level']}")

        detail = " · ".join(detail_parts)

        rows.append(html.Div(
            style={
                "padding": "10px 0",
                "borderBottom": "1px solid rgba(30, 41, 59, 0.3)",
                "display": "flex",
                "justifyContent": "space-between",
                "alignItems": "center",
            },
            children=[
                html.Div([
                    html.Div(
                        style={"display": "flex", "alignItems": "center", "gap": "8px"},
                        children=[
                            html.Span(sign_label, className=sign_color,
                                     style={"fontWeight": "700", "fontSize": "14px",
                                            "minWidth": "50px"}),
                            html.Span(inst_type,
                                     style={"fontWeight": "600", "fontSize": "13px"}),
                        ],
                    ),
                    html.Div(detail,
                             style={"fontSize": "11px", "color": "var(--text-muted)",
                                    "marginTop": "2px", "marginLeft": "58px"}),
                ]),
                html.Span(book,
                          style={"fontSize": "10px", "padding": "3px 8px",
                                 "borderRadius": "4px",
                                 "background": "rgba(59, 130, 246, 0.1)",
                                 "color": "var(--blue)"}),
            ],
        ))

    count_text = f"{len(positions)} position{'s' if len(positions) != 1 else ''}"
    return html.Div(rows), count_text


# --- Positions summary on valuation tab ---

@callback(
    Output("pf-positions-summary", "children"),
    Input("portfolio-tabs", "active_tab"),
    State("pf-positions-store", "data"),
)
def show_positions_summary(active_tab, positions):
    if not positions:
        return html.Div("No positions. Go to Build tab first.",
                        style={"color": "var(--text-muted)"})

    items = []
    for pos in positions:
        inst = pos["instrument"]
        params = inst["params"]
        sign = "+" if pos["direction"] == "buy" else "-"
        color = "text-green" if pos["direction"] == "buy" else "text-red"
        label = f"{sign}{pos['quantity']:.0f} {inst['type'].replace('_', ' ')}"
        if "strike" in params:
            label += f" K={params['strike']}"
        if "option_type" in params:
            label += f" {params['option_type']}"

        items.append(html.Div(label, className=color,
                             style={"fontSize": "12px", "marginBottom": "4px"}))

    return html.Div([
        html.Div("PORTFOLIO POSITIONS", className="panel-header"),
    ] + items)


# --- Value portfolio ---

@callback(
    Output("pf-valuation-results", "children"),
    Input("btn-value-portfolio", "n_clicks"),
    State("pf-positions-store", "data"),
    State("pfmkt-pricing-date", "value"),
    State("pfmkt-rate", "value"),
    State("pfmkt-spot", "value"),
    State("pfmkt-vol", "value"),
    State("pfmkt-div", "value"),
    State("pf-model-select", "value"),
    State("pf-engine-select", "value"),
    prevent_initial_call=True,
)
def value_portfolio(n_clicks, positions, pricing_date, rate, spot, vol, div_yield,
                    model, engine):
    if not positions:
        return error_alert("No positions to value. Add positions in the Build tab.")

    underlying = "AAPL"
    for pos in positions:
        und = pos["instrument"]["params"].get("underlying", "AAPL")
        if und:
            underlying = und
            break

    market_data = collect_market_data(pricing_date, rate, spot, vol, div_yield, underlying)

    try:
        # Price each position individually and aggregate
        results = []
        total_npv = 0.0
        total_greeks = {}

        for pos in positions:
            payload = {
                "instrument": pos["instrument"],
                "market_data": market_data,
                "model": model or "black_scholes",
                "engine": engine or "analytic",
            }

            try:
                price_result = api_client.price_single(payload)
                unit_npv = price_result.get("npv", 0)
            except Exception as e:
                results.append({
                    "instrument": pos["instrument"]["type"],
                    "quantity": pos["quantity"],
                    "direction": pos["direction"],
                    "unit_npv": 0,
                    "position_npv": 0,
                    "error": str(e),
                })
                continue

            sign = 1.0 if pos["direction"] == "buy" else -1.0
            position_npv = unit_npv * pos["quantity"] * sign
            total_npv += position_npv

            # Greeks
            try:
                greeks_payload = {**payload,
                                 "measures": ["delta", "gamma", "vega", "theta", "rho"]}
                gr = api_client.compute_greeks(greeks_payload)
                for g, v in gr.get("greeks", {}).items():
                    if v is not None:
                        scaled = v * pos["quantity"] * sign
                        total_greeks[g] = total_greeks.get(g, 0) + scaled
            except Exception:
                pass

            results.append({
                "instrument": pos["instrument"]["type"],
                "params": pos["instrument"]["params"],
                "quantity": pos["quantity"],
                "direction": pos["direction"],
                "unit_npv": unit_npv,
                "position_npv": position_npv,
            })

        return _render_valuation(total_npv, total_greeks, results)

    except APIError as e:
        return error_alert(e.detail)
    except Exception as e:
        return error_alert(str(e))


def _render_valuation(total_npv, total_greeks, results):
    """Render portfolio valuation results."""
    # Portfolio summary
    summary = html.Div(className="npv-card", children=[
        html.Div(className="npv-header", children=[
            html.Div("PORTFOLIO NPV", className="npv-label"),
            html.Div(f"${total_npv:,.4f}", className="npv-value"),
            html.Div(f"{len(results)} positions", className="npv-meta"),
        ]),
    ])

    # Aggregated Greeks
    greeks_el = html.Div()
    if total_greeks:
        cells = []
        for name, val in total_greeks.items():
            css = "greek-positive" if val >= 0 else "greek-negative"
            cells.append(html.Div(className="greek-cell", children=[
                html.Div(name.upper(), className="greek-name"),
                html.Div(f"{val:.4f}", className=f"greek-value {css}"),
            ]))

        greeks_el = html.Div([
            html.Div("PORTFOLIO GREEKS", className="panel-header",
                     style={"padding": "16px 28px 0"}),
            html.Div(className="greeks-grid", children=cells),
        ])

    # Position details table
    header = html.Thead(html.Tr([
        html.Th("Type"), html.Th("Details"), html.Th("Qty"),
        html.Th("Dir"), html.Th("Unit NPV"), html.Th("Pos NPV"),
    ]))

    rows = []
    for r in results:
        if "error" in r:
            rows.append(html.Tr([
                html.Td(r["instrument"].replace("_", " ")),
                html.Td(""), html.Td(f"{r['quantity']:.0f}"),
                html.Td(r["direction"]),
                html.Td("ERROR", className="text-red"),
                html.Td(r.get("error", "")[:30], className="text-red"),
            ]))
        else:
            params = r.get("params", {})
            detail_parts = []
            if "underlying" in params:
                detail_parts.append(params["underlying"])
            if "strike" in params:
                detail_parts.append(f"K={params['strike']}")
            if "option_type" in params:
                detail_parts.append(params["option_type"])
            detail = " ".join(detail_parts)

            pos_color = "text-green" if r["position_npv"] >= 0 else "text-red"
            dir_color = "text-green" if r["direction"] == "buy" else "text-red"

            rows.append(html.Tr([
                html.Td(r["instrument"].replace("_", " ")),
                html.Td(detail, style={"color": "var(--text-muted)"}),
                html.Td(f"{r['quantity']:.0f}"),
                html.Td(r["direction"], className=dir_color),
                html.Td(f"${r['unit_npv']:.4f}"),
                html.Td(f"${r['position_npv']:+,.4f}", className=pos_color,
                        style={"fontWeight": "600"}),
            ]))

    table_el = html.Div(className="panel",
                        style={"padding": "0", "overflow": "hidden", "marginTop": "16px"},
                        children=[
        html.Div("POSITION DETAILS", className="panel-header",
                 style={"padding": "16px 20px 8px"}),
        dbc.Table([header, html.Tbody(rows)],
                  bordered=False, hover=True, className="table"),
    ])

    return html.Div([summary, greeks_el, table_el])


# --- Portfolio stress test ---

@callback(
    Output("pf-stress-results", "children"),
    Input("btn-pf-stress", "n_clicks"),
    State("pf-positions-store", "data"),
    State("pfstress-pricing-date", "value"),
    State("pfstress-rate", "value"),
    State("pfstress-spot", "value"),
    State("pfstress-vol", "value"),
    State("pfstress-div", "value"),
    State("pfstress-model", "value"),
    State("pfstress-engine", "value"),
    prevent_initial_call=True,
)
def portfolio_stress_test(n_clicks, positions,
                          pricing_date, rate, spot, vol, div_yield,
                          model, engine):
    if not positions:
        return error_alert("No positions. Add positions in the Build tab.")

    underlying = "AAPL"
    for pos in positions:
        und = pos["instrument"]["params"].get("underlying")
        if und:
            underlying = und
            break

    market_data = collect_market_data(pricing_date, rate, spot, vol, div_yield, underlying)

    instruments = [pos["instrument"] for pos in positions]

    try:
        payload = {
            "instruments": instruments,
            "market_data": market_data,
            "model": model or "black_scholes",
            "engine": engine or "analytic",
        }
        result = api_client.run_stress_test(payload)

        scenarios = result.get("results", [])
        worst = result.get("worst_scenario", "")
        best = result.get("best_scenario", "")

        # Bar chart
        names = [s.get("scenario_name", "") for s in scenarios]
        impacts = [s.get("total_impact", 0) for s in scenarios]
        colors = ["#22c55e" if v >= 0 else "#ef4444" for v in impacts]

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=names, y=impacts,
            marker_color=colors,
            text=[f"{v:+.4f}" for v in impacts],
            textposition="outside",
            textfont=dict(size=9, family="JetBrains Mono"),
        ))
        fig.update_layout(
            title=dict(text="Portfolio Stress Test",
                       font=dict(size=16, family="Space Grotesk")),
            plot_bgcolor="#0a0e17", paper_bgcolor="#111827",
            font=dict(color="#e2e8f0", family="JetBrains Mono", size=10),
            xaxis=dict(gridcolor="#1e293b", tickangle=-45),
            yaxis=dict(title="P&L Impact", gridcolor="#1e293b",
                       zeroline=True, zerolinecolor="#f59e0b"),
            margin=dict(t=60, b=100),
            height=450,
        )

        return html.Div([
            html.Div(className="panel", style={"padding": "0"}, children=[
                dcc.Graph(figure=fig, config={"displayModeBar": False}),
            ]),
            html.Div(style={"marginTop": "12px", "fontSize": "12px"}, children=[
                html.Span(f"Worst: {worst}", className="text-red",
                          style={"marginRight": "20px"}),
                html.Span(f"Best: {best}", className="text-green"),
            ]),
        ])

    except APIError as e:
        return error_alert(e.detail)
    except Exception as e:
        return error_alert(str(e))