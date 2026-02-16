"""
Streamlit Pricing Dashboard

Quick internal tool for:
- Single trade pricing
- Strike ladder visualization
- Greeks computation
- Scenario analysis
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import date, timedelta
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

st.set_page_config(page_title="QuantLib Pricing Platform", layout="wide", page_icon="📈")
st.title("📈 QuantLib Pricing Platform")


# ---------------------------------------------------------------------------
# Sidebar: Market Data Inputs
# ---------------------------------------------------------------------------

st.sidebar.header("Market Data")
spot = st.sidebar.number_input("Spot Price", value=100.0, step=1.0)
risk_free_rate = st.sidebar.number_input("Risk-Free Rate (%)", value=5.0, step=0.1) / 100
vol = st.sidebar.number_input("Volatility (%)", value=20.0, step=1.0) / 100
div_yield = st.sidebar.number_input("Dividend Yield (%)", value=2.0, step=0.1) / 100
pricing_date = st.sidebar.date_input("Pricing Date", value=date.today())
underlying = st.sidebar.text_input("Underlying", value="AAPL")


# ---------------------------------------------------------------------------
# Lazy imports and setup
# ---------------------------------------------------------------------------

@st.cache_resource
def setup():
    """One-time setup: register components."""
    import instruments.equity.vanilla_option  # noqa
    import engines.analytic.equity_engines  # noqa
    import models.equity.black_scholes  # noqa
    from services.pricers.pricing_service import PricingService
    from services.risk.risk_service import RiskService
    return PricingService(), RiskService()


def build_market(spot_val, rate_val, vol_val, div_val, pdate, und):
    from core.types.value_objects import PricingDate
    from market.curves.yield_curve import build_test_market_env
    return build_test_market_env(
        pricing_date=PricingDate(pdate),
        spot=spot_val, rate=rate_val, vol=vol_val,
        div_yield=div_val, underlying=und,
    )


try:
    pricing_service, risk_service = setup()
    market_env = build_market(spot, risk_free_rate, vol, div_yield, pricing_date, underlying)
    setup_ok = True
except Exception as e:
    st.error(f"Setup failed: {e}")
    st.info("Make sure QuantLib-Python is installed: `pip install QuantLib-Python`")
    setup_ok = False


# ---------------------------------------------------------------------------
# Tab layout
# ---------------------------------------------------------------------------

if setup_ok:
    tab1, tab2, tab3, tab4 = st.tabs(["💰 Single Price", "📊 Strike Ladder", "🔢 Greeks", "🎯 Scenarios"])

    # -----------------------------------------------------------------------
    # Tab 1: Single Trade Pricing
    # -----------------------------------------------------------------------
    with tab1:
        st.subheader("Single Option Pricing")
        col1, col2, col3 = st.columns(3)

        with col1:
            strike = st.number_input("Strike", value=100.0, step=1.0)
            option_type = st.selectbox("Option Type", ["CALL", "PUT"])
        with col2:
            expiry = st.date_input("Expiry", value=date.today() + timedelta(days=365))
            model_choice = st.selectbox("Model", ["BSM (Analytic)", "Heston (Analytic)", "BSM (Monte Carlo)"])
        with col3:
            notional = st.number_input("Notional", value=1.0, step=1.0)

        if st.button("Price", type="primary"):
            from instruments.equity.vanilla_option import VanillaOption
            from core.enums.definitions import OptionType as OT, ExerciseType

            opt = VanillaOption(
                _trade_id="UI-TRADE",
                underlying=underlying,
                strike=strike,
                expiry=expiry,
                option_type=OT.CALL if option_type == "CALL" else OT.PUT,
                exercise_type=ExerciseType.EUROPEAN,
                notional=notional,
                _currency="USD",
            )

            model_map = {
                "BSM (Analytic)": ("black_scholes", "analytic"),
                "Heston (Analytic)": ("heston", "heston_analytic"),
                "BSM (Monte Carlo)": ("black_scholes", "monte_carlo"),
            }
            m, e = model_map[model_choice]

            result = pricing_service.price(opt, market_env, model_type=m, engine_type=e)

            col_r1, col_r2, col_r3 = st.columns(3)
            col_r1.metric("NPV", f"${result.npv:.4f}")
            col_r2.metric("Model", result.model_used)
            col_r3.metric("Time", f"{result.diagnostics.get('elapsed_seconds', 0):.4f}s")

    # -----------------------------------------------------------------------
    # Tab 2: Strike Ladder
    # -----------------------------------------------------------------------
    with tab2:
        st.subheader("Strike Ladder")
        col1, col2 = st.columns(2)
        with col1:
            k_min = st.number_input("Min Strike", value=int(spot * 0.7))
            k_max = st.number_input("Max Strike", value=int(spot * 1.3))
        with col2:
            k_step = st.number_input("Step", value=5)
            expiry_ladder = st.date_input("Expiry (Ladder)", value=date.today() + timedelta(days=365), key="ladder_exp")

        if st.button("Generate Ladder"):
            from instruments.equity.vanilla_option import VanillaOption
            from core.enums.definitions import OptionType as OT, ExerciseType

            strikes_list = list(range(int(k_min), int(k_max) + 1, int(k_step)))
            calls = [
                VanillaOption(
                    _trade_id=f"LADDER-C-{K}", underlying=underlying, strike=float(K),
                    expiry=expiry_ladder, option_type=OT.CALL,
                    exercise_type=ExerciseType.EUROPEAN, _currency="USD",
                ) for K in strikes_list
            ]
            puts = [
                VanillaOption(
                    _trade_id=f"LADDER-P-{K}", underlying=underlying, strike=float(K),
                    expiry=expiry_ladder, option_type=OT.PUT,
                    exercise_type=ExerciseType.EUROPEAN, _currency="USD",
                ) for K in strikes_list
            ]

            call_results = pricing_service.price_batch(calls, market_env)
            put_results = pricing_service.price_batch(puts, market_env)

            df = pd.DataFrame({
                "Strike": strikes_list,
                "Call NPV": [r.npv for r in call_results],
                "Put NPV": [r.npv for r in put_results],
            })

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df["Strike"], y=df["Call NPV"], name="Call", mode="lines+markers"))
            fig.add_trace(go.Scatter(x=df["Strike"], y=df["Put NPV"], name="Put", mode="lines+markers"))
            fig.add_vline(x=spot, line_dash="dash", annotation_text=f"Spot={spot}")
            fig.update_layout(title="Option Payoff by Strike", xaxis_title="Strike", yaxis_title="NPV")
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(df.style.format({"Call NPV": "{:.4f}", "Put NPV": "{:.4f}"}))

    # -----------------------------------------------------------------------
    # Tab 3: Greeks
    # -----------------------------------------------------------------------
    with tab3:
        st.subheader("Greeks (Finite Difference)")
        strike_g = st.number_input("Strike (Greeks)", value=100.0, step=1.0, key="greek_strike")
        expiry_g = st.date_input("Expiry (Greeks)", value=date.today() + timedelta(days=365), key="greek_exp")

        if st.button("Compute Greeks"):
            from instruments.equity.vanilla_option import VanillaOption
            from core.enums.definitions import OptionType as OT, ExerciseType, RiskMeasure

            opt = VanillaOption(
                _trade_id="GREEK-TRADE", underlying=underlying, strike=strike_g,
                expiry=expiry_g, option_type=OT.CALL,
                exercise_type=ExerciseType.EUROPEAN, _currency="USD",
            )

            result = risk_service.compute_greeks(
                opt, market_env,
                measures=[RiskMeasure.DELTA, RiskMeasure.GAMMA, RiskMeasure.VEGA, RiskMeasure.THETA, RiskMeasure.RHO],
            )

            cols = st.columns(5)
            for i, (name, val) in enumerate(result.greeks.items()):
                cols[i % 5].metric(name.upper(), f"{val:.6f}" if val is not None else "N/A")

    # -----------------------------------------------------------------------
    # Tab 4: Scenarios
    # -----------------------------------------------------------------------
    with tab4:
        st.subheader("Scenario Analysis")
        strike_s = st.number_input("Strike (Scenarios)", value=100.0, step=1.0, key="scen_strike")
        expiry_s = st.date_input("Expiry (Scenarios)", value=date.today() + timedelta(days=365), key="scen_exp")

        if st.button("Run Scenarios"):
            from instruments.equity.vanilla_option import VanillaOption
            from core.enums.definitions import OptionType as OT, ExerciseType

            opt = VanillaOption(
                _trade_id="SCEN-TRADE", underlying=underlying, strike=strike_s,
                expiry=expiry_s, option_type=OT.CALL,
                exercise_type=ExerciseType.EUROPEAN, _currency="USD",
            )

            base = pricing_service.price(opt, market_env)
            scenarios = risk_service.generate_standard_scenarios(underlying)
            results = risk_service.run_scenarios(opt, market_env, scenarios)

            df = pd.DataFrame([
                {"Scenario": name, "PnL": pnl, "PnL %": pnl / base.npv * 100 if base.npv else 0}
                for name, pnl in sorted(results.items(), key=lambda x: x[1], reverse=True)
            ])

            fig = px.bar(df, x="Scenario", y="PnL", color="PnL",
                         color_continuous_scale=["red", "gray", "green"],
                         title=f"Scenario PnL (Base NPV: ${base.npv:.4f})")
            fig.update_layout(xaxis_tickangle=-45)
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(df.style.format({"PnL": "{:+.4f}", "PnL %": "{:+.2f}%"}))
