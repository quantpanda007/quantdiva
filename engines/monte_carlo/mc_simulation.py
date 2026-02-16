"""
MC path simulation — generates spot paths for BSM and Heston models.

Separated from the engine so it can be:
- Unit tested independently
- Reused across European/American/Bermudan engines
- Extended with variance reduction without touching engine code

Key fixes from audit:
- T derived from instrument, not hardcoded
- Market data extracted at correct maturity and strike
- Heston uses proper Euler/QE discretization, not GBM
- Discount factors computed from actual curve
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional, Tuple

import numpy as np
import QuantLib as ql

from core.interfaces.base import MarketEnvironment
from core.types.value_objects import PricingDate

logger = logging.getLogger(__name__)


@dataclass
class SimulationConfig:
    """Configuration for MC path simulation."""
    num_paths: int = 50_000
    time_steps: int = 252
    seed: int = 42
    antithetic: bool = True

    # Derived at runtime
    T: float = 1.0            # time to maturity in years
    spot: float = 100.0
    rate: float = 0.05
    div_yield: float = 0.0
    vol: float = 0.20         # BSM flat vol or Heston initial vol

    # Heston-specific
    heston_v0: float = 0.04
    heston_kappa: float = 1.0
    heston_theta: float = 0.04
    heston_sigma: float = 0.5
    heston_rho: float = -0.7


def extract_market_data(
    market_env: MarketEnvironment,
    underlying: str,
    maturity: date,
    strike: float,
) -> dict:
    """
    Extract market data at the correct maturity and strike.

    Fixes audit issue: rates/dividends/vol must be extracted at
    actual T, not hardcoded to 1.0.
    """
    pricing_date = market_env.pricing_date.value
    ql_pricing = market_env.pricing_date.to_ql()
    ql_maturity = ql.Date(maturity.day, maturity.month, maturity.year)

    # Time to maturity in years (ACT/365)
    T = ql.Actual365Fixed().yearFraction(ql_pricing, ql_maturity)
    if T <= 0:
        raise ValueError(
            f"Maturity {maturity} is not after pricing date {pricing_date}. T={T}"
        )

    # Spot
    spot = market_env.spot_prices.get(underlying)
    if spot is None:
        raise ValueError(f"No spot price for '{underlying}'")

    # Risk-free rate at maturity T
    try:
        discount_handle = market_env.discount_curves.get(
            underlying, market_env.discount_curves.get("USD")
        )
        rate = discount_handle.zeroRate(T, ql.Continuous, ql.Annual).rate()
    except Exception as e:
        logger.warning(f"Could not extract rate at T={T}: {e}. Using 0.05.")
        rate = 0.05

    # Dividend yield at maturity T
    div_yield = 0.0
    try:
        div_key = f"{underlying}_div"
        if div_key in market_env.dividend_curves:
            div_yield = market_env.dividend_curves[div_key].zeroRate(
                T, ql.Continuous, ql.Annual
            ).rate()
    except Exception as e:
        logger.warning(f"Could not extract div yield at T={T}: {e}. Using 0.0.")

    # Volatility at maturity T and strike
    vol = 0.20
    try:
        vol_handle = market_env.vol_surfaces.get(underlying)
        if vol_handle is not None:
            vol = vol_handle.blackVol(T, strike)
    except Exception as e:
        logger.warning(f"Could not extract vol at T={T}, K={strike}: {e}. Using 0.20.")

    return {
        "T": T,
        "spot": spot,
        "rate": rate,
        "div_yield": div_yield,
        "vol": vol,
    }


def extract_heston_params(model) -> dict:
    """Extract Heston-specific parameters from model."""
    return {
        "heston_v0": getattr(model, "v0", 0.04),
        "heston_kappa": getattr(model, "kappa", 1.0),
        "heston_theta": getattr(model, "theta", 0.04),
        "heston_sigma": getattr(model, "sigma", 0.5),
        "heston_rho": getattr(model, "rho", -0.7),
    }


# ---------------------------------------------------------------------------
# Discount factor schedule
# ---------------------------------------------------------------------------

def compute_discount_factors(
    rate: float,
    T: float,
    time_steps: int,
) -> np.ndarray:
    """
    Compute discount factors at each time step.

    Returns array of shape (time_steps+1,) where df[i] = exp(-r * t_i).
    """
    dt = T / time_steps
    times = np.arange(time_steps + 1) * dt  # [0, dt, 2*dt, ..., T]
    return np.exp(-rate * times)


# ---------------------------------------------------------------------------
# GBM Path Simulation (Black-Scholes)
# ---------------------------------------------------------------------------

def simulate_gbm_paths(
    config: SimulationConfig,
    Z: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Simulate GBM paths using exact log-normal discretization.

    S(t+dt) = S(t) * exp((r - q - 0.5*σ²)*dt + σ*√dt*Z)

    Args:
        config: simulation configuration
        Z: pre-generated random numbers shape (time_steps, num_paths).
           If None, generates using numpy pseudorandom.

    Returns:
        random_numbers: shape (time_steps, num_paths) — Gaussian draws
        spot_paths:     shape (time_steps+1, num_paths) — S(t) at each step
    """
    N = config.num_paths
    M = config.time_steps
    dt = config.T / M

    # Generate random numbers if not provided
    if Z is None:
        rng = np.random.RandomState(config.seed)
        Z = rng.standard_normal((M, N))

    # Ensure correct shape
    assert Z.shape == (M, N), f"Z shape {Z.shape} != expected ({M}, {N})"

    # Exact GBM discretization
    drift = (config.rate - config.div_yield - 0.5 * config.vol ** 2) * dt
    diffusion = config.vol * np.sqrt(dt)

    log_increments = drift + diffusion * Z  # (M, N)

    # Build paths
    spot_paths = np.zeros((M + 1, N))
    spot_paths[0, :] = config.spot
    spot_paths[1:, :] = config.spot * np.exp(np.cumsum(log_increments, axis=0))

    return Z, spot_paths


# ---------------------------------------------------------------------------
# Heston Path Simulation (Euler discretization)
# ---------------------------------------------------------------------------

def simulate_heston_paths(
    config: SimulationConfig,
    Z1: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Simulate Heston stochastic volatility paths using Euler discretization.

    dS = (r - q) * S * dt + √V * S * dW_s
    dV = κ(θ - V) * dt + σ_v * √V * dW_v
    corr(dW_s, dW_v) = ρ

    Uses full truncation scheme: V(t) = max(V(t), 0) to prevent negative variance.

    Args:
        config: simulation configuration with Heston parameters
        Z1: pre-generated spot random numbers (time_steps, num_paths).
            If None, generates internally. Vol random numbers always generated fresh
            (correlated with Z1 via ρ).

    Returns:
        random_numbers: shape (time_steps, num_paths) — spot Gaussian draws (Z_s only)
        spot_paths:     shape (time_steps+1, num_paths) — S(t) at each step
    """
    N = config.num_paths
    M = config.time_steps
    dt = config.T / M

    v0 = config.heston_v0
    kappa = config.heston_kappa
    theta = config.heston_theta
    sigma_v = config.heston_sigma
    rho = config.heston_rho

    # Generate random numbers
    rng = np.random.RandomState(config.seed)
    if Z1 is None:
        Z1 = rng.standard_normal((M, N))
    Z2 = rng.standard_normal((M, N))  # independent vol draws

    # Correlate: W_v = ρ * W_s + √(1-ρ²) * W_independent
    Z_v = rho * Z1 + np.sqrt(1 - rho ** 2) * Z2

    # Simulate paths
    spot_paths = np.zeros((M + 1, N))
    var_paths = np.zeros((M + 1, N))

    spot_paths[0, :] = config.spot
    var_paths[0, :] = v0

    sqrt_dt = np.sqrt(dt)

    for t in range(M):
        V = np.maximum(var_paths[t, :], 0.0)  # full truncation
        sqrt_V = np.sqrt(V)

        # Variance step: dV = κ(θ - V)*dt + σ_v * √V * √dt * Z_v
        var_paths[t + 1, :] = (
            V + kappa * (theta - V) * dt + sigma_v * sqrt_V * sqrt_dt * Z_v[t, :]
        )

        # Spot step: log scheme for positivity
        # ln S(t+1) = ln S(t) + (r - q - V/2)*dt + √V * √dt * Z_s
        log_spot = (
            np.log(spot_paths[t, :])
            + (config.rate - config.div_yield - 0.5 * V) * dt
            + sqrt_V * sqrt_dt * Z1[t, :]
        )
        spot_paths[t + 1, :] = np.exp(log_spot)

    return Z1, spot_paths


# ---------------------------------------------------------------------------
# Intrinsic value computation
# ---------------------------------------------------------------------------

def compute_intrinsic_values(
    spot_paths: np.ndarray,
    strike: float,
    is_call: bool,
) -> np.ndarray:
    """
    Compute intrinsic values at each time step for all paths.

    Args:
        spot_paths: shape (T+1, N)
        strike: option strike
        is_call: True for call, False for put

    Returns:
        intrinsic_values: shape (T+1, N)
    """
    if is_call:
        return np.maximum(spot_paths - strike, 0.0)
    else:
        return np.maximum(strike - spot_paths, 0.0)
