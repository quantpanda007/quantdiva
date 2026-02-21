"""
Dashboard callbacks — status cards, quick price.
"""

from __future__ import annotations

from dash import Input, Output, State, callback, html, dcc, no_update, ctx
import dash_bootstrap_components as dbc

from components.components import error_alert
from services.api_client import api_client, APIError


# --- Status cards on page load ---

@callback(
    Output("dash-status-cards", "children"),
    Input("url", "pathname"),
)
def load_status_cards(pathname):
    if pathname not in ("/", "/dashboard"):
        return no_update

    cards = []

    # Health
    try:
        health = api_client.health()
        status = health.get("status", "unknown")
        color = "var(--green)" if status in ("ok", "healthy") else "var(--red)"
        cards.append(_status_card("BACKEND", status.upper(), color))
    except Exception:
        cards.append(_status_card("BACKEND", "OFFLINE", "var(--red)"))

    # Instruments
    try:
        instruments = api_client.get_instruments()
        cards.append(_status_card("INSTRUMENTS", str(len(instruments)), "var(--accent)"))
    except Exception:
        cards.append(_status_card("INSTRUMENTS", "?", "var(--text-muted)"))

    # Engines
    try:
        engines = api_client.get_engines()
        cards.append(_status_card("ENGINES", str(len(engines)), "var(--blue)"))
    except Exception:
        cards.append(_status_card("ENGINES", "?", "var(--text-muted)"))

    # Scenarios
    try:
        scenarios = api_client.get_scenarios()
        cards.append(_status_card("SCENARIOS", str(len(scenarios)), "var(--purple)"))
    except Exception:
        cards.append(_status_card("SCENARIOS", "?", "var(--text-muted)"))

    # Models
    try:
        models = api_client.get_models()
        cards.append(_status_card("MODELS", str(len(models)), "var(--green)"))
    except Exception:
        cards.append(_status_card("MODELS", "?", "var(--text-muted)"))

    return html.Div(style={
        "display": "grid",
        "gridTemplateColumns": f"repeat({len(cards)}, 1fr)",
        "gap": "12px",
    }, children=cards)


def _status_card(label, value, color):
    return html.Div(className="panel", style={
        "padding": "16px 20px", "textAlign": "center",
    }, children=[
        html.Div(value, style={
            "fontSize": "28px", "fontWeight": "700",
            "color": color, "fontFamily": "var(--font-display)",
        }),
        html.Div(label, style={
            "fontSize": "10px", "color": "var(--text-muted)",
            "textTransform": "uppercase", "letterSpacing": "1px",
            "marginTop": "4px",
        }),
    ])


# --- Quick price ---

@callback(
    Output("qp-result", "children"),
    Input("btn-quick-price", "n_clicks"),
    State("qp-type", "value"),
    State("qp-spot", "value"),
    State("qp-strike", "value"),
    State("qp-vol", "value"),
    State("qp-expiry", "value"),
    prevent_initial_call=True,
)
def quick_price(n_clicks, option_type, spot, strike, vol, expiry):
    if not n_clicks:
        return no_update

    try:
        payload = {
            "instrument": {
                "type": "vanilla_option",
                "params": {
                    "trade_id": "QUICK-001",
                    "underlying": "SPOT",
                    "strike": float(strike or 100),
                    "expiry": expiry or "2026-01-15",
                    "option_type": option_type or "call",
                    "exercise_type": "european",
                    "currency": "USD",
                },
            },
            "market_data": {
                "pricing_date": "2025-01-15",
                "underlyings": {
                    "SPOT": {
                        "spot": float(spot or 100),
                        "vol": float(vol or 0.2),
                        "div_yield": 0.0,
                    }
                },
                "rate": 0.045,
            },
            "model": "black_scholes",
            "engine": "analytic",
        }

        result = api_client.price_single(payload)

        # Also get Greeks
        greeks = {}
        try:
            g = api_client.compute_greeks({
                **payload,
                "measures": ["delta", "gamma", "vega", "theta", "rho"],
            })
            greeks = g.get("greeks", {})
        except Exception:
            pass

        npv = result.get("npv", 0)

        # Compact result display
        greek_parts = []
        for name in ["delta", "gamma", "vega", "theta", "rho"]:
            v = greeks.get(name)
            if v is not None:
                greek_parts.append(html.Span([
                    html.Span(f"{name[0].upper()} ",
                             style={"color": "var(--text-muted)", "fontSize": "10px"}),
                    html.Span(f"{v:.4f} ",
                             style={"color": "var(--green)" if v >= 0 else "var(--red)"}),
                ]))

        return html.Div(style={
            "padding": "16px 20px",
            "background": "linear-gradient(135deg, rgba(245,158,11,0.03), rgba(245,158,11,0.01))",
            "borderRadius": "8px", "border": "1px solid var(--border)",
        }, children=[
            html.Div(style={"display": "flex", "alignItems": "baseline", "gap": "12px"},
                     children=[
                html.Span(f"${npv:,.4f}", style={
                    "fontSize": "24px", "fontWeight": "700",
                    "color": "var(--accent)", "fontFamily": "var(--font-display)",
                }),
                html.Span(f"{result.get('elapsed_ms', 0):.0f}ms", style={
                    "fontSize": "11px", "color": "var(--text-muted)",
                }),
            ]),
            html.Div(style={"marginTop": "8px", "fontSize": "12px"},
                     children=greek_parts) if greek_parts else html.Div(),
        ])

    except APIError as e:
        return error_alert(e.detail)
    except Exception as e:
        return error_alert(str(e))
