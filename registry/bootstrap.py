"""
Registry bootstrap.

Importing this module ensures all instruments, models,
and engines register themselves via decorators.
"""

# Instruments
import instruments.equity.vanilla_option  # noqa: F401
import instruments.equity.barrier_option   # noqa: F401
import instruments.equity.digital_option   # noqa: F401
import instruments.equity.asian_option    # noqa: F401
import instruments.equity.lookback_option      # noqa: F401



# Models
import models.equity.black_scholes  # noqa: F401

# Engines
import engines.analytic.bsm_engine  # noqa: F401
import engines.finite_difference.fd_vanilla_engine  # noqa: F401
import engines.lattice.binomial_engine  # noqa: F401
import engines.monte_carlo.mc_vanilla_engine  # noqa: F401
import engines.analytic.barrier_digital_engine  # noqa: F401
import engines.finite_difference.fd_barrier_engine  # noqa: F401
import engines.monte_carlo.mc_barrier_engine  # noqa: F401
import engines.analytic.asian_engine      # noqa: F401
import engines.monte_carlo.mc_asian_engine  # noqa: F401
import engines.analytic.lookback_engine        # noqa: F401
import engines.monte_carlo.mc_lookback_engine  # noqa: F401
