# %% [markdown]
# # QuantLib Pricing Platform — Quick Start
#
# This notebook demonstrates end-to-end pricing:
# 1. Build market data
# 2. Create instruments
# 3. Price & compute Greeks
# 4. Run scenario analysis

# %%
import sys
sys.path.insert(0, "..")

from datetime import date
import QuantLib as ql

# %% [markdown]
# ## 1. Build Market Environment

# %%
from core.types.value_objects import PricingDate
from market.curves.yield_curve import build_test_market_env

pricing_date = PricingDate(date(2025, 6, 15))

market_env = build_test_market_env(
    pricing_date=pricing_date,
    spot=100.0,
    rate=0.05,
    vol=0.20,
    div_yield=0.02,
    underlying="AAPL",
)

print(f"Pricing date: {pricing_date.value}")
print(f"Spot: {market_env.spot_prices}")
print(f"Discount curves: {list(market_env.discount_curves.keys())}")

# %% [markdown]
# ## 2. Create Instruments

# %%
from core.enums.definitions import OptionType, ExerciseType
from instruments.equity.vanilla_option import VanillaOption

# ATM European Call
call = VanillaOption(
    _trade_id="AAPL-CALL-100",
    underlying="AAPL",
    strike=100.0,
    expiry=date(2025, 12, 19),
    option_type=OptionType.CALL,
    exercise_type=ExerciseType.EUROPEAN,
    _currency="USD",
)

# OTM Put
put = VanillaOption(
    _trade_id="AAPL-PUT-90",
    underlying="AAPL",
    strike=90.0,
    expiry=date(2025, 12, 19),
    option_type=OptionType.PUT,
    exercise_type=ExerciseType.EUROPEAN,
    _currency="USD",
)

print(f"Call: {call.to_dict()}")
print(f"Put:  {put.to_dict()}")

# %% [markdown]
# ## 3. Price with BSM Analytic Engine

# %%
# Trigger registration of engines and models
import engines.analytic.equity_engines  # noqa
import models.equity.black_scholes  # noqa

from services.pricers.pricing_service import PricingService

service = PricingService()

# Price the call
call_result = service.price(call, market_env)
print(f"\nCall NPV: ${call_result.npv:.4f}")
print(f"Engine: {call_result.engine_used}, Model: {call_result.model_used}")
print(f"Time: {call_result.diagnostics.get('elapsed_seconds', 0):.6f}s")

# Price the put
put_result = service.price(put, market_env)
print(f"\nPut NPV: ${put_result.npv:.4f}")

# %% [markdown]
# ## 4. Batch Pricing — Strike Ladder

# %%
import pandas as pd

strikes = [80, 85, 90, 95, 100, 105, 110, 115, 120]
instruments = [
    VanillaOption(
        _trade_id=f"CALL-{K}", underlying="AAPL", strike=float(K),
        expiry=date(2025, 12, 19), option_type=OptionType.CALL,
        exercise_type=ExerciseType.EUROPEAN, _currency="USD",
    )
    for K in strikes
]

results = service.price_batch(instruments, market_env)

df = pd.DataFrame([
    {"Strike": K, "NPV": r.npv, "Moneyness": 100.0 / K}
    for K, r in zip(strikes, results)
])
print("\nStrike Ladder:")
print(df.to_string(index=False, float_format="%.4f"))

# %% [markdown]
# ## 5. Compute Greeks

# %%
from core.enums.definitions import RiskMeasure
from services.risk.risk_service import RiskService

risk_service = RiskService()

greeks = risk_service.compute_greeks(
    call, market_env,
    measures=[RiskMeasure.DELTA, RiskMeasure.GAMMA, RiskMeasure.VEGA, RiskMeasure.THETA, RiskMeasure.RHO],
)

print(f"\nGreeks for {call.trade_id()}:")
for name, value in greeks.greeks.items():
    if value is not None:
        print(f"  {name:8s}: {value:.6f}")

# %% [markdown]
# ## 6. Scenario Analysis

# %%
scenarios = risk_service.generate_standard_scenarios("AAPL")
scenario_results = risk_service.run_scenarios(call, market_env, scenarios)

print(f"\nScenario Analysis for {call.trade_id()} (base NPV={call_result.npv:.4f}):")
for name, pnl in sorted(scenario_results.items()):
    print(f"  {name:25s}: PnL = {pnl:+.4f}")

# %% [markdown]
# ## 7. Heston Model Pricing

# %%
heston_result = service.price(
    call, market_env,
    model_type="heston",
    engine_type="heston_analytic",
)
print(f"\nHeston Analytic NPV: ${heston_result.npv:.4f}")
print(f"BSM Analytic NPV:    ${call_result.npv:.4f}")
print(f"Difference:          ${heston_result.npv - call_result.npv:.4f}")

# %% [markdown]
# ## 8. Check Registry Contents

# %%
from registry import instrument_registry, engine_registry, model_registry

print("\nRegistered Instruments:", instrument_registry.keys())
print("Registered Engines:", engine_registry.keys())
print("Registered Models:", model_registry.keys())
