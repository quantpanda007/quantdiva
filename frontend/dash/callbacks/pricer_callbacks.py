"""
Pricer page callbacks.

Uses pattern-matching callbacks to read dynamic instrument form fields.
"""

from __future__ import annotations

from dash import Input, Output, State, callback, html, no_update, ctx, ALL
import dash_bootstrap_components as dbc

from components.components import (
    INSTRUMENT_FIELDS, NUMERIC_FIELDS,
    build_instrument_form, collect_market_data,
    npv_card, greeks_display, compare_table, error_alert,
)
from services.api_client import api_client, APIError


# --- Rebuild instrument form on type change ---

@callback(
    Output("instrument-form-container", "children"),
    Input("inst-type", "value"),
)
def update_instrument_form(inst_type):
    if not inst_type:
        return no_update
    return build_instrument_form(inst_type)


# --- Update engine dropdown based on instrument type ---

@callback(
    Output("engine-select", "options"),
    Output("engine-select", "value"),
    Input("inst-type", "value"),
)
def update_engine_options(inst_type):
    if not inst_type:
        return [{"label": "analytic", "value": "analytic"}], "analytic"

    try:
        compat = api_client.get_engine_compatibility()
        engines = compat.get(inst_type, ["analytic"])
        options = [{"label": e, "value": e} for e in engines]
        value = engines[0] if engines else "analytic"
        return options, value
    except Exception:
        return [{"label": "analytic", "value": "analytic"}], "analytic"


# --- Price / Greeks / Compare ---

@callback(
    Output("results-container", "children"),
    Input("btn-price", "n_clicks"),
    Input("btn-greeks", "n_clicks"),
    Input("btn-compare", "n_clicks"),
    # Instrument type
    State("inst-type", "value"),
    # All dynamic instrument fields (pattern-matching)
    State({"type": "inst-field", "field": ALL}, "value"),
    # Model & engine
    State("model-select", "value"),
    State("engine-select", "value"),
    # Market data
    State("mkt-pricing-date", "value"),
    State("mkt-rate", "value"),
    State("mkt-spot", "value"),
    State("mkt-vol", "value"),
    State("mkt-div", "value"),
    prevent_initial_call=True,
)
def handle_action(
    price_clicks, greeks_clicks, compare_clicks,
    inst_type, field_values,
    model, engine,
    pricing_date, rate, spot, vol, div_yield,
):
    """Handle Price / Greeks / Compare button clicks."""
    triggered = ctx.triggered_id
    if not triggered:
        return no_update

    # -- Collect instrument params from pattern-matching fields --
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

    # -- Build market data --
    underlying = params.get("underlying", "AAPL")
    market_data = collect_market_data(pricing_date, rate, spot, vol, div_yield, underlying)

    # -- Build payload --
    payload = {
        "instrument": {"type": inst_type, "params": params},
        "market_data": market_data,
        "model": model or "black_scholes",
        "engine": engine or "analytic",
    }

    try:
        if triggered == "btn-price":
            return _handle_price(payload)
        elif triggered == "btn-greeks":
            return _handle_greeks(payload)
        elif triggered == "btn-compare":
            return _handle_compare(payload, inst_type)
        else:
            return no_update

    except APIError as e:
        return error_alert(e.detail)
    except Exception as e:
        return error_alert(str(e))


def _handle_price(payload):
    """Price single + fetch Greeks."""
    result = api_client.price_single(payload)

    greeks = None
    try:
        greeks_payload = {**payload, "measures": ["delta", "gamma", "vega", "theta", "rho"]}
        greeks_result = api_client.compute_greeks(greeks_payload)
        greeks = greeks_result.get("greeks", {})
    except Exception:
        pass

    children = [npv_card(result)]
    if greeks:
        children.append(greeks_display(greeks))

    return html.Div(className="npv-card", children=children)


def _handle_greeks(payload):
    """Compute Greeks only."""
    greeks_payload = {**payload, "measures": ["delta", "gamma", "vega", "theta", "rho"]}
    result = api_client.compute_greeks(greeks_payload)

    return html.Div(className="npv-card", children=[
        html.Div(className="npv-header", children=[
            html.Div("BASE NPV", className="npv-label"),
            html.Div(f"${result.get('base_npv', 0):,.4f}", className="npv-value"),
            html.Div(result.get("trade_id", ""), className="npv-meta"),
        ]),
        greeks_display(result.get("greeks", {})),
    ])


def _handle_compare(payload, inst_type):
    """Compare across engines."""
    try:
        compat = api_client.get_engine_compatibility()
        engines = compat.get(inst_type, ["analytic"])
    except Exception:
        engines = None

    compare_payload = {**payload, "engines": engines}
    result = api_client.price_compare(compare_payload)

    return html.Div(className="npv-card", children=[
        html.Div(className="npv-header", children=[
            html.Div("REFERENCE NPV", className="npv-label"),
            html.Div(
                f"${result.get('reference_npv', 0):,.6f}",
                className="npv-value",
            ),
            html.Div(
                f"{result.get('trade_id', '')} · ref: {result.get('reference_engine', '')}",
                className="npv-meta",
            ),
        ]),
        compare_table(result.get("results", [])),
    ])