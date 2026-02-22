"""
Pricer page callbacks.

Uses pattern-matching callbacks to read dynamic instrument form fields.
Supports engine-specific params (MC simulations, FD grid, etc.)
"""

from __future__ import annotations

from dash import Input, Output, State, callback, html, dcc, no_update, ctx, ALL
import dash_bootstrap_components as dbc

from components.components import (
    INSTRUMENT_FIELDS, NUMERIC_FIELDS,
    build_instrument_form, collect_market_data,
    npv_card, greeks_display, compare_table, error_alert,
    form_field,
)
from pages.pricer import equity_market_data, rates_market_data, fx_market_data, RATES_INSTRUMENTS, FX_INSTRUMENTS
from services.api_client import api_client, APIError


# --- Rebuild instrument form on type change ---

@callback(
    Output("instrument-form-container", "children"),
    Output("market-data-container", "children"),
    Input("inst-type", "value"),
)
def update_instrument_form(inst_type):
    if not inst_type:
        return no_update, no_update

    form = build_instrument_form(inst_type, page="pricer")

    if inst_type in FX_INSTRUMENTS:
        mkt = fx_market_data()
    elif inst_type in RATES_INSTRUMENTS:
        mkt = rates_market_data()
    else:
        mkt = equity_market_data()

    return form, mkt


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


# --- Show/hide engine-specific params ---

MC_SIMULATION_OPTIONS = [
    {"label": "1,000",    "value": 1000},
    {"label": "5,000",    "value": 5000},
    {"label": "10,000",   "value": 10000},
    {"label": "50,000",   "value": 50000},
    {"label": "100,000",  "value": 100000},
    {"label": "500,000",  "value": 500000},
]

FD_GRID_OPTIONS = [
    {"label": "Coarse (50)",   "value": 50},
    {"label": "Medium (100)",  "value": 100},
    {"label": "Fine (200)",    "value": 200},
    {"label": "Ultra (500)",   "value": 500},
]

@callback(
    Output("engine-params-container", "children"),
    Input("engine-select", "value"),
)
def show_engine_params(engine):
    if not engine:
        return html.Div()

    eng = str(engine).lower()

    if "monte_carlo" in eng or "mc" in eng:
        return dbc.Row([
            dbc.Col(form_field(
                "Simulations",
                dcc.Dropdown(
                    id="vis-mc-num-paths",
                    options=MC_SIMULATION_OPTIONS,
                    value=10000,
                    clearable=False,
                    style={"background": "var(--bg)"},
                ),
            ), width=6),
            dbc.Col(form_field(
                "RNG Type",
                dcc.Dropdown(
                    id="vis-mc-rng-type",
                    options=[
                        {"label": "Pseudo-Random", "value": "pseudorandom"},
                        {"label": "Sobol (Quasi)", "value": "sobol"},
                    ],
                    value="pseudorandom",
                    clearable=False,
                    style={"background": "var(--bg)"},
                ),
            ), width=6),
        ], style={"marginTop": "10px"})

    elif "finite_difference" in eng or "fd" in eng:
        return dbc.Row([
            dbc.Col(form_field(
                "Grid Points",
                dcc.Dropdown(
                    id="vis-fd-grid-points",
                    options=FD_GRID_OPTIONS,
                    value=100,
                    clearable=False,
                    style={"background": "var(--bg)"},
                ),
            ), width=6),
        ], style={"marginTop": "10px"})

    return html.Div()


# --- Sync visible engine params to hidden stores ---

@callback(Output("mc-num-paths", "data"), Input("vis-mc-num-paths", "value"),
          prevent_initial_call=True)
def sync_mc_paths(v): return v

@callback(Output("mc-rng-type", "data"), Input("vis-mc-rng-type", "value"),
          prevent_initial_call=True)
def sync_mc_rng(v): return v

@callback(Output("fd-grid-points", "data"), Input("vis-fd-grid-points", "value"),
          prevent_initial_call=True)
def sync_fd_grid(v): return v


# --- Price / Greeks / Compare ---

@callback(
    Output("results-container", "children"),
    Input("btn-price", "n_clicks"),
    Input("btn-greeks", "n_clicks"),
    Input("btn-compare", "n_clicks"),
    State("inst-type", "value"),
    State({"type": "pricer-inst-field", "field": ALL}, "value"),
    State("model-select", "value"),
    State("engine-select", "value"),
    State("mkt-pricing-date", "value"),
    State("mkt-rate", "value"),
    State("mkt-spot", "value"),
    State("mkt-vol", "value"),
    State("mkt-div", "value"),
    # Engine-specific params from stores
    State("mc-num-paths", "data"),
    State("mc-rng-type", "data"),
    State("fd-grid-points", "data"),
    prevent_initial_call=True,
)
def handle_action(
    price_clicks, greeks_clicks, compare_clicks,
    inst_type, field_values, model, engine,
    pricing_date, rate, spot, vol, div_yield,
    mc_num_paths, mc_rng_type, fd_grid_points,
):
    """Handle Price / Greeks / Compare button clicks."""
    triggered = ctx.triggered_id
    if not triggered:
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

    # Determine underlying key for market data
    # FX uses ccy_pair as key, equity uses underlying, rates use USD
    underlying = (
        params.get("ccy_pair")
        or params.get("underlying")
        or "USD"
    )
    market_data = collect_market_data(pricing_date, rate, spot, vol, div_yield, underlying)

    # Build engine params
    eng = str(engine or "").lower()
    engine_params = {}
    if "monte_carlo" in eng or "mc" in eng:
        engine_params["num_paths"] = int(mc_num_paths or 10000)
        if mc_rng_type:
            engine_params["rng_type"] = mc_rng_type
    elif "finite_difference" in eng or "fd" in eng:
        engine_params["grid_points"] = int(fd_grid_points or 100)

    payload = {
        "instrument": {"type": inst_type, "params": params},
        "market_data": market_data,
        "model": model or "black_scholes",
        "engine": engine or "analytic",
    }
    if engine_params:
        payload["engine_params"] = engine_params

    try:
        if triggered == "btn-price":
            return _handle_price(payload, engine_params)
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


def _handle_price(payload, engine_params=None):
    """Price single + fetch Greeks."""
    result = api_client.price_single(payload)

    greeks = None
    try:
        greeks_payload = {**payload, "measures": ["delta", "gamma", "vega", "theta", "rho"]}
        greeks_result = api_client.compute_greeks(greeks_payload)
        greeks = greeks_result.get("greeks", {})
    except Exception:
        pass

    meta_parts = [
        result.get("trade_id", ""),
        result.get("model", ""),
        result.get("engine", ""),
        f"{result.get('elapsed_ms', 0)}ms",
    ]
    if engine_params:
        if "num_paths" in engine_params:
            meta_parts.append(f"{engine_params['num_paths']:,} paths")
        if "rng_type" in engine_params:
            meta_parts.append(engine_params["rng_type"])
        if "grid_points" in engine_params:
            meta_parts.append(f"{engine_params['grid_points']} grid pts")

    npv_card_el = html.Div(className="npv-header", children=[
        html.Div("NET PRESENT VALUE", className="npv-label"),
        html.Div(f"${result.get('npv', 0):,.4f}", className="npv-value"),
        html.Div(" \u00b7 ".join(meta_parts), className="npv-meta"),
    ])

    children = [npv_card_el]
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
                f"{result.get('trade_id', '')} \u00b7 ref: {result.get('reference_engine', '')}",
                className="npv-meta",
            ),
        ]),
        compare_table(result.get("results", [])),
    ])


# --- Load Live Market Data ---

@callback(
    Output("mkt-spot", "value"),
    Output("mkt-vol", "value"),
    Output("mkt-rate", "value"),
    Output("mkt-div", "value"),
    Output("mkt-pricing-date", "value"),
    Output("live-data-status", "children"),
    Input("btn-load-live", "n_clicks"),
    State("inst-type", "value"),
    State({"type": "pricer-inst-field", "field": ALL}, "value"),
    prevent_initial_call=True,
)
def load_live_data(n_clicks, inst_type, field_values):
    """Fetch live market data and populate form fields."""
    from datetime import date as dt_date

    if not n_clicks:
        return no_update, no_update, no_update, no_update, no_update, no_update

    fields = INSTRUMENT_FIELDS.get(inst_type, [])
    params = {}
    for i, (name, ftype, default) in enumerate(fields):
        if i < len(field_values):
            params[name] = field_values[i]

    # Determine what to fetch
    underlying = params.get("underlying")
    ccy_pair = params.get("ccy_pair")

    try:
        if underlying:
            # Equity instrument — get spot, vol, rate
            data = api_client.get_live_snapshot(underlying=underlying)
            und_data = data.get("underlyings", {}).get(underlying, {})
            spot = und_data.get("spot", "")
            vol = und_data.get("vol", "")
            rate = data.get("rate", "")
            div_yield = und_data.get("div_yield", "")
            pricing_date = data.get("pricing_date", dt_date.today().isoformat())
            source = data.get("source", "")

            status = f"✓ {underlying} ${spot:.2f} | vol={vol:.2%} | rate={rate:.4f} — {source}"
            return str(spot), str(vol), str(rate), str(div_yield), pricing_date, status

        elif ccy_pair:
            # FX instrument — get FX rate
            data = api_client.get_live_snapshot(ccy_pair=ccy_pair)
            fx_data = data.get("underlyings", {}).get(ccy_pair, {})
            spot = fx_data.get("spot", "")
            rate = data.get("rate", "")
            pricing_date = data.get("pricing_date", dt_date.today().isoformat())
            source = data.get("source", "")

            status = f"✓ {ccy_pair} {spot:.4f} | rate={rate:.4f} — {source}"
            return str(spot), no_update, str(rate), no_update, pricing_date, status

        else:
            # Rates instrument — get yield curve rate
            data = api_client.get_live_snapshot(currency="USD")
            rate = data.get("rate", "")
            pricing_date = data.get("pricing_date", dt_date.today().isoformat())
            source = data.get("source", "")

            # Show curve info if available
            yc = data.get("yield_curve", [])
            curve_info = ""
            if yc:
                tenors = [f"{p['maturity']}={p['rate']:.3%}" for p in yc[:4]]
                curve_info = " | " + " ".join(tenors)

            status = f"✓ Rate={rate:.4f}{curve_info} — {source}"
            return no_update, no_update, str(rate), no_update, pricing_date, status

    except Exception as e:
        return no_update, no_update, no_update, no_update, no_update, f"✗ {str(e)[:60]}"
