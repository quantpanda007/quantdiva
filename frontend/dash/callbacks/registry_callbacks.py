"""
Registry page callbacks.
"""

from __future__ import annotations

from dash import Input, Output, callback, html, no_update
import dash_bootstrap_components as dbc

from services.api_client import api_client, APIError
from components.components import error_alert


@callback(
    Output("registry-tab-content", "children"),
    Input("registry-tabs", "active_tab"),
)
def render_registry_tab(active_tab):
    if not active_tab:
        return no_update

    try:
        if active_tab == "tab-compat":
            return _render_compatibility()
        elif active_tab == "tab-instruments":
            return _render_instruments()
        elif active_tab == "tab-scenarios":
            return _render_scenarios()
    except APIError as e:
        return error_alert(e.detail)
    except Exception as e:
        return error_alert(str(e))

    return no_update


def _render_compatibility():
    """Engine compatibility matrix."""
    compat = api_client.get_engine_compatibility()

    all_engines = sorted(set(e for engines in compat.values() for e in engines))
    inst_types = sorted(compat.keys())

    # Header row
    header = html.Thead(html.Tr(
        [html.Th("INSTRUMENT", style={"textAlign": "left"})]
        + [html.Th(e.replace("_", " ").upper(), style={"textAlign": "center"})
           for e in all_engines]
    ))

    # Data rows
    rows = []
    for it in inst_types:
        cells = [html.Td(
            it.replace("_", " ").upper(),
            style={"fontWeight": "600"},
        )]
        for eng in all_engines:
            if eng in compat[it]:
                cells.append(html.Td(
                    "✓",
                    style={"textAlign": "center", "color": "var(--green)"},
                ))
            else:
                cells.append(html.Td(
                    "—",
                    style={"textAlign": "center", "color": "var(--text-muted)", "opacity": "0.3"},
                ))
        rows.append(html.Tr(cells))

    return html.Div(className="panel", style={"padding": "0", "overflow": "hidden"}, children=[
        dbc.Table(
            [header, html.Tbody(rows)],
            bordered=False, hover=True, className="table",
            style={"marginBottom": "0"},
        ),
    ])


def _render_instruments():
    """Instruments list."""
    instruments = api_client.get_instruments()

    items = []
    for inst in instruments:
        items.append(html.Div(
            style={
                "padding": "14px 20px",
                "display": "flex",
                "justifyContent": "space-between",
                "alignItems": "center",
                "borderBottom": "1px solid rgba(30, 41, 59, 0.15)",
            },
            children=[
                html.Div([
                    html.Div(
                        inst["type"].replace("_", " ").upper(),
                        style={"color": "var(--text)", "fontSize": "14px", "fontWeight": "600"},
                    ),
                    html.Div(
                        inst["class_name"],
                        style={"color": "var(--text-muted)", "fontSize": "11px"},
                    ),
                ]),
                html.Span(
                    inst["type"],
                    style={
                        "padding": "4px 10px", "borderRadius": "4px", "fontSize": "10px",
                        "background": "rgba(59, 130, 246, 0.1)", "color": "var(--blue)",
                        "fontFamily": "var(--font-mono)",
                    },
                ),
            ],
        ))

    return html.Div(className="panel", style={"padding": "0", "overflow": "hidden"}, children=items)


def _render_scenarios():
    """Scenarios list."""
    scenarios = api_client.get_scenarios()

    items = []
    for s in scenarios:
        shocks_text = ", ".join(
            f"{sh['risk_factor']} {sh['shock_type']} {'+' if sh['value'] > 0 else ''}{sh['value']}"
            for sh in s.get("shocks", [])
        )

        items.append(html.Div(
            style={
                "padding": "14px 20px",
                "borderBottom": "1px solid rgba(30, 41, 59, 0.15)",
            },
            children=[
                html.Div(
                    style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"},
                    children=[
                        html.Div(
                            s["name"],
                            style={"color": "var(--text)", "fontSize": "14px", "fontWeight": "600"},
                        ),
                        html.Span(
                            s["key"],
                            style={
                                "padding": "4px 10px", "borderRadius": "4px", "fontSize": "10px",
                                "background": "rgba(167, 139, 250, 0.1)", "color": "var(--purple)",
                                "fontFamily": "var(--font-mono)",
                            },
                        ),
                    ],
                ),
                html.Div(
                    shocks_text,
                    style={"color": "var(--text-muted)", "fontSize": "12px", "marginTop": "4px"},
                ),
            ],
        ))

    return html.Div(className="panel", style={"padding": "0", "overflow": "hidden"}, children=items)
