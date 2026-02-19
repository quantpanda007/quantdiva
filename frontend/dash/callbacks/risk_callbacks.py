"""
Risk Lab callbacks.

Handles spot ladder, vol ladder, stress test, and custom scenarios.
"""

from __future__ import annotations

from dash import Input, Output, State, callback, html, dcc, no_update, ctx, ALL
import dash_bootstrap_components as dbc
import plotly.graph_objects as go

from components.components import (
    INSTRUMENT_FIELDS, NUMERIC_FIELDS,
    build_instrument_form, collect_market_data, error_alert,
)
from services.api_client import api_client, APIError


# --- Rebuild instrument form on type change ---

@callback(
    Output("risk-instrument-form-container", "children"),
    Input("risk-inst-type", "value"),
)
def update_risk_instrument_form(inst_type):
    if not inst_type:
        return no_update
    return build_instrument_form(inst_type)


# --- Update engine dropdown ---

@callback(
    Output("risk-engine-select", "options"),
    Output("risk-engine-select", "value"),
    Input("risk-inst-type", "value"),
)
def update_risk_engine_options(inst_type):
    if not inst_type:
        return [{"label": "analytic", "value": "analytic"}], "analytic"
    try:
        compat = api_client.get_engine_compatibility()
        engines = compat.get(inst_type, ["analytic"])
        options = [{"label": e, "value": e} for e in engines]
        return options, engines[0] if engines else "analytic"
    except Exception:
        return [{"label": "analytic", "value": "analytic"}], "analytic"


# --- Tab-specific controls ---

@callback(
    Output("risk-tab-controls", "children"),
    Input("risk-tabs", "active_tab"),
)
def render_tab_controls(active_tab):
    if active_tab == "tab-spot-ladder":
        return html.Div(className="panel", children=[
            html.Div("SPOT LADDER SETTINGS", className="panel-header"),
            dbc.Row([
                dbc.Col(dbc.Label("Bumps (%)", className="form-label"), width=3),
                dbc.Col(dbc.Input(
                    id="vis-spot-bumps",
                    value="-20, -15, -10, -5, -2, 0, 2, 5, 10, 15, 20",
                    className="form-control",
                    style={"background": "var(--bg)", "color": "var(--text)"},
                ), width=9),
            ]),
        ])
    elif active_tab == "tab-vol-ladder":
        return html.Div(className="panel", children=[
            html.Div("VOL LADDER SETTINGS", className="panel-header"),
            dbc.Row([
                dbc.Col(dbc.Label("Bumps (pts)", className="form-label"), width=3),
                dbc.Col(dbc.Input(
                    id="vis-vol-bumps",
                    value="-10, -5, -2, 0, 2, 5, 10, 15",
                    className="form-control",
                    style={"background": "var(--bg)", "color": "var(--text)"},
                ), width=9),
            ]),
        ])
    elif active_tab == "tab-stress":
        return html.Div(className="panel", children=[
            html.Div("STRESS TEST", className="panel-header"),
            html.P("Runs all predefined scenarios",
                   style={"color": "var(--text-muted)", "fontSize": "12px"}),
        ])
    elif active_tab == "tab-scenario":
        return html.Div(className="panel", children=[
            html.Div("CUSTOM SCENARIO", className="panel-header"),
            dbc.Row([
                dbc.Col(dbc.Label("Spot Shock (%)", className="form-label"), width=3),
                dbc.Col(dbc.Input(
                    id="vis-scenario-spot", value="-10", type="number",
                    className="form-control",
                    style={"background": "var(--bg)", "color": "var(--text)"},
                ), width=3),
                dbc.Col(dbc.Label("Vol Shock (pts)", className="form-label"), width=3),
                dbc.Col(dbc.Input(
                    id="vis-scenario-vol", value="5", type="number",
                    className="form-control",
                    style={"background": "var(--bg)", "color": "var(--text)"},
                ), width=3),
            ]),
        ])
    return html.Div()


# --- Sync visible inputs to hidden stores ---

@callback(Output("spot-bumps-input", "value"), Input("vis-spot-bumps", "value"),
          prevent_initial_call=True)
def sync_spot_bumps(v): return v

@callback(Output("vol-bumps-input", "value"), Input("vis-vol-bumps", "value"),
          prevent_initial_call=True)
def sync_vol_bumps(v): return v

@callback(Output("scenario-spot-shock", "value"), Input("vis-scenario-spot", "value"),
          prevent_initial_call=True)
def sync_scenario_spot(v): return v

@callback(Output("scenario-vol-shock", "value"), Input("vis-scenario-vol", "value"),
          prevent_initial_call=True)
def sync_scenario_vol(v): return v


# --- Run analysis ---

@callback(
    Output("risk-results-container", "children"),
    Input("btn-run-risk", "n_clicks"),
    State("risk-tabs", "active_tab"),
    State("risk-inst-type", "value"),
    State({"type": "inst-field", "field": ALL}, "value"),
    State("risk-model-select", "value"),
    State("risk-engine-select", "value"),
    State("risk-pricing-date", "value"),
    State("risk-rate", "value"),
    State("risk-spot", "value"),
    State("risk-vol", "value"),
    State("risk-div", "value"),
    State("spot-bumps-input", "value"),
    State("vol-bumps-input", "value"),
    State("scenario-spot-shock", "value"),
    State("scenario-vol-shock", "value"),
    prevent_initial_call=True,
)
def run_risk_analysis(
    n_clicks, active_tab,
    inst_type, field_values, model, engine,
    pricing_date, rate, spot, vol, div_yield,
    spot_bumps_str, vol_bumps_str,
    scenario_spot, scenario_vol,
):
    if not n_clicks:
        return no_update

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

    underlying = params.get("underlying", "AAPL")
    market_data = collect_market_data(pricing_date, rate, spot, vol, div_yield, underlying)

    instrument = {"type": inst_type, "params": params}

    try:
        if active_tab == "tab-spot-ladder":
            return _run_spot_ladder(instrument, market_data, model, engine, spot_bumps_str)
        elif active_tab == "tab-vol-ladder":
            return _run_vol_ladder(instrument, market_data, model, engine, vol_bumps_str)
        elif active_tab == "tab-stress":
            return _run_stress_test(instrument, market_data, model, engine)
        elif active_tab == "tab-scenario":
            return _run_custom_scenario(instrument, market_data, model, engine,
                                        scenario_spot, scenario_vol)
    except APIError as e:
        return error_alert(e.detail)
    except Exception as e:
        return error_alert(str(e))

    return no_update


def _run_spot_ladder(instrument, market_data, model, engine, bumps_str):
    bumps_str = bumps_str or "-20, -10, -5, 0, 5, 10, 20"
    bumps = [float(b.strip()) / 100.0 for b in bumps_str.split(",")]

    payload = {
        "instruments": [instrument],
        "market_data": market_data,
        "model": model,
        "engine": engine,
        "risk_factor": "spot",
        "bump_type": "relative",
        "bumps": bumps,
    }

    result = api_client.run_ladder(payload)
    return _render_ladder_chart(result, "Spot", "%")


def _run_vol_ladder(instrument, market_data, model, engine, bumps_str):
    bumps_str = bumps_str or "-10, -5, -2, 0, 2, 5, 10, 15"
    bumps = [float(b.strip()) / 100.0 for b in bumps_str.split(",")]

    payload = {
        "instruments": [instrument],
        "market_data": market_data,
        "model": model,
        "engine": engine,
        "risk_factor": "vol",
        "bump_type": "absolute",
        "bumps": bumps,
    }

    result = api_client.run_ladder(payload)
    return _render_ladder_chart(result, "Vol", "pts")


def _run_stress_test(instrument, market_data, model, engine):
    payload = {
        "instruments": [instrument],
        "market_data": market_data,
        "model": model,
        "engine": engine,
    }

    result = api_client.run_stress_test(payload)
    return _render_stress_table(result)


def _run_custom_scenario(instrument, market_data, model, engine, spot_shock, vol_shock):
    shocks = []
    if spot_shock:
        shocks.append({
            "risk_factor": "spot",
            "shock_type": "relative",
            "value": float(spot_shock) / 100.0,
        })
    if vol_shock:
        shocks.append({
            "risk_factor": "vol",
            "shock_type": "absolute",
            "value": float(vol_shock) / 100.0,
        })

    payload = {
        "instruments": [instrument],
        "market_data": market_data,
        "model": model,
        "engine": engine,
        "scenario_name": f"Custom: Spot {spot_shock}%, Vol {vol_shock}pts",
        "shocks": shocks,
    }

    result = api_client.run_scenario(payload)
    return _render_scenario_result(result)


# --- Renderers ---

def _render_ladder_chart(result, factor_name, unit):
    data = result.get("results", [])
    if not data:
        return error_alert("No ladder results")

    bumps = [r["bump"] for r in data]
    impacts = [r["total_impact"] for r in data]
    base_npv = data[0]["total_base"] if data else 0

    if unit == "%":
        labels = [f"{b*100:+.0f}%" for b in bumps]
    else:
        labels = [f"{b*100:+.0f}pts" for b in bumps]

    colors = ["#22c55e" if v >= 0 else "#ef4444" for v in impacts]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=labels, y=impacts,
        marker_color=colors,
        text=[f"{v:+.4f}" for v in impacts],
        textposition="outside",
        textfont=dict(size=10, family="JetBrains Mono"),
    ))

    fig.update_layout(
        title=dict(text=f"{factor_name} Ladder - P&L Impact",
                   font=dict(size=16, family="Space Grotesk")),
        plot_bgcolor="#0a0e17",
        paper_bgcolor="#111827",
        font=dict(color="#e2e8f0", family="JetBrains Mono", size=11),
        xaxis=dict(title=f"{factor_name} Bump", gridcolor="#1e293b"),
        yaxis=dict(title="P&L Impact", gridcolor="#1e293b",
                   zeroline=True, zerolinecolor="#f59e0b"),
        margin=dict(t=60, b=60),
        height=400,
    )

    return html.Div([
        html.Div(className="npv-card", children=[
            html.Div(className="npv-header", children=[
                html.Div("BASE NPV", className="npv-label"),
                html.Div(f"${base_npv:,.4f}", className="npv-value"),
            ]),
        ]),
        html.Div(className="panel", style={"marginTop": "16px", "padding": "0"}, children=[
            dcc.Graph(figure=fig, config={"displayModeBar": False}),
        ]),
    ])


def _render_stress_table(result):
    scenarios = result.get("results", [])
    worst = result.get("worst_scenario", "")
    best = result.get("best_scenario", "")

    header = html.Thead(html.Tr([
        html.Th("Scenario"), html.Th("Base NPV"), html.Th("Shocked NPV"),
        html.Th("Impact"), html.Th("Time (ms)"),
    ]))

    rows = []
    for s in scenarios:
        impact = s.get("total_impact", 0)
        color = "text-green" if impact >= 0 else "text-red"
        is_worst = s.get("scenario_name") == worst
        is_best = s.get("scenario_name") == best

        name = s.get("scenario_name", "")
        if is_worst:
            name += "  worst"
        elif is_best:
            name += "  best"

        rows.append(html.Tr([
            html.Td(name, style={"fontWeight": "600" if is_worst or is_best else "400"}),
            html.Td(f"{s.get('total_base', 0):.4f}"),
            html.Td(f"{s.get('total_shocked', 0):.4f}"),
            html.Td(f"{impact:+.4f}", className=color, style={"fontWeight": "600"}),
            html.Td(f"{s.get('elapsed_ms', 0):.0f}"),
        ]))

    return html.Div(className="panel", style={"padding": "0", "overflow": "hidden"}, children=[
        html.Div("STRESS TEST RESULTS", className="panel-header",
                 style={"padding": "16px 20px 8px"}),
        dbc.Table([header, html.Tbody(rows)],
                  bordered=False, hover=True, className="table"),
        html.Div(style={"padding": "12px 20px", "fontSize": "12px"}, children=[
            html.Span(f"Worst: {worst} ", className="text-red",
                      style={"marginRight": "20px"}),
            html.Span(f"Best: {best}", className="text-green"),
        ]),
    ])


def _render_scenario_result(result):
    impact = result.get("total_impact", 0)
    color = "text-green" if impact >= 0 else "text-red"

    return html.Div(className="npv-card", children=[
        html.Div(className="npv-header", children=[
            html.Div("SCENARIO RESULT", className="npv-label"),
            html.Div(result.get("scenario_name", ""),
                     className="npv-meta", style={"marginBottom": "8px"}),
            dbc.Row([
                dbc.Col([
                    html.Div("Base NPV", className="npv-label"),
                    html.Div(f"${result.get('total_base', 0):,.4f}",
                             style={"fontSize": "20px", "fontWeight": "600",
                                    "color": "var(--text)"}),
                ], width=4),
                dbc.Col([
                    html.Div("Shocked NPV", className="npv-label"),
                    html.Div(f"${result.get('total_shocked', 0):,.4f}",
                             style={"fontSize": "20px", "fontWeight": "600",
                                    "color": "var(--text)"}),
                ], width=4),
                dbc.Col([
                    html.Div("P&L Impact", className="npv-label"),
                    html.Div(f"${impact:+,.4f}",
                             style={"fontSize": "20px", "fontWeight": "600"},
                             className=color),
                ], width=4),
            ]),
        ]),
    ])