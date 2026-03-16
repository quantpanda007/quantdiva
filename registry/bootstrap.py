"""
Registry bootstrap — imports all instrument, engine, and model modules
so their @register decorators execute at startup.

This file is imported by api/app.py at startup.
"""

# --- Instruments ---
# Equity
import instruments.equity.vanilla_option        # noqa: F401
import instruments.equity.barrier_option         # noqa: F401
import instruments.equity.digital_option         # noqa: F401
import instruments.equity.asian_option           # noqa: F401
import instruments.equity.lookback_option        # noqa: F401

# Rates
import instruments.rates.interest_rate_swap      # noqa: F401
import instruments.rates.fixed_rate_bond         # noqa: F401
import instruments.rates.fra                     # noqa: F401
import instruments.rates.cap_floor               # noqa: F401
import instruments.rates.swaption                # noqa: F401

# Credit
import instruments.credit.cds                    # noqa: F401

# FX
import instruments.fx.fx_forward                 # noqa: F401
import instruments.fx.fx_option                  # noqa: F401
import instruments.fx.fx_range_forward           # noqa: F401

# --- Engines ---
# Analytic
import engines.analytic.bsm_engine              # noqa: F401
import engines.analytic.barrier_digital_engine   # noqa: F401
import engines.analytic.asian_engine             # noqa: F401
import engines.analytic.lookback_engine          # noqa: F401
import engines.analytic.rates_engines            # noqa: F401
import engines.analytic.credit_engines           # noqa: F401
import engines.analytic.fx_engines               # noqa: F401

# Finite Difference
try:
    import engines.finite_difference.fd_vanilla_engine   # noqa: F401
    import engines.finite_difference.fd_barrier_engine   # noqa: F401
except ImportError:
    pass

# Lattice (Binomial)
try:
    import engines.lattice.binomial_engine       # noqa: F401
except ImportError:
    pass

# Monte Carlo
try:
    import engines.monte_carlo.mc_vanilla_engine   # noqa: F401
    import engines.monte_carlo.mc_asian_engine     # noqa: F401
    import engines.monte_carlo.mc_lookback_engine  # noqa: F401
    import engines.monte_carlo.mc_barrier_engine   # noqa: F401
except ImportError:
    pass

# --- Models ---
try:
    import models.equity.black_scholes           # noqa: F401
    import models.rates_credit_models            # noqa: F401
except ImportError:
    pass


# --- Analytical alias (for forward/linear instruments that don't use a stochastic model) ---
try:
    from registry import model_registry
    _bs_model = model_registry.get('black_scholes')
    model_registry.register('analytical', _bs_model, overwrite=True)
except Exception:
    pass

# --- Range Forward engine registration ---
from registry import engine_registry
try:
    _fx_eng = engine_registry.get(("fx_option", "analytic"))
    engine_registry.register(("fx_range_forward", "analytic"), _fx_eng, overwrite=True)
except Exception:
    pass

print("[bootstrap] Registry loaded: instruments, engines, models")

'''
# --- FX Forward engine registration ---
try:
    _fx_fwd_eng = engine_registry.get(("fx_option", "analytic"))
    engine_registry.register(("fx_forward", "analytic"), _fx_fwd_eng, overwrite=True)
except Exception:
    pass

'''

