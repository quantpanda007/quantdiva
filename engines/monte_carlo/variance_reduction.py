"""
Variance reduction techniques for Monte Carlo simulation.

Provides:
- Control Variate: uses analytic BSM as control to reduce variance
- Moment Matching: adjusts paths so sample moments match theoretical
- Combined: both techniques together

Theory (Control Variate):
    Let V_mc = MC estimate, V_cv = control variable (BSM analytic for same option)
    V_adjusted = V_mc - β * (V_cv_mc - V_cv_analytic)
    where β = Cov(V_mc, V_cv) / Var(V_cv) ≈ 1 for same underlying process

    This dramatically reduces variance when MC and analytic are highly correlated,
    which they are for vanilla options under BSM.

Theory (Moment Matching):
    Adjust simulated paths so that:
    E[S(T)] = S(0) * exp((r-q)*T)      (first moment)
    This removes drift discretization error.

Usage:
    from engines.monte_carlo.variance_reduction import (
        apply_control_variate,
        apply_moment_matching,
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
import QuantLib as ql

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Control Variate
# ---------------------------------------------------------------------------

@dataclass
class ControlVariateResult:
    """Output of control variate adjustment."""
    adjusted_npv: float
    raw_npv: float
    analytic_npv: float
    beta: float               # optimal β coefficient
    variance_ratio: float     # Var(adjusted) / Var(raw) — <1 means improvement
    std_error_raw: float
    std_error_adjusted: float


def bsm_analytic_price(
    spot: float,
    strike: float,
    T: float,
    rate: float,
    div_yield: float,
    vol: float,
    is_call: bool,
) -> float:
    """
    Black-Scholes-Merton closed-form price.

    Used as the analytic control value.
    """
    if T <= 0 or vol <= 0:
        # Expired or zero vol — intrinsic value
        if is_call:
            return max(spot * np.exp(-div_yield * T) - strike * np.exp(-rate * T), 0.0)
        else:
            return max(strike * np.exp(-rate * T) - spot * np.exp(-div_yield * T), 0.0)

    from scipy.stats import norm

    d1 = (np.log(spot / strike) + (rate - div_yield + 0.5 * vol ** 2) * T) / (vol * np.sqrt(T))
    d2 = d1 - vol * np.sqrt(T)

    if is_call:
        price = (
            spot * np.exp(-div_yield * T) * norm.cdf(d1)
            - strike * np.exp(-rate * T) * norm.cdf(d2)
        )
    else:
        price = (
            strike * np.exp(-rate * T) * norm.cdf(-d2)
            - spot * np.exp(-div_yield * T) * norm.cdf(-d1)
        )

    return float(price)


def apply_control_variate(
    mc_payoffs: np.ndarray,
    spot_paths: np.ndarray,
    strike: float,
    T: float,
    rate: float,
    div_yield: float,
    vol: float,
    is_call: bool,
    discount_factor: float,
) -> ControlVariateResult:
    """
    Apply control variate using analytic BSM price.

    Args:
        mc_payoffs:      (N,) discounted payoffs from MC simulation
        spot_paths:      (T+1, N) simulated spot paths
        strike:          option strike
        T:               time to maturity
        rate:            risk-free rate
        div_yield:       dividend yield
        vol:             volatility (BSM flat vol)
        is_call:         True for call, False for put
        discount_factor: exp(-r*T) for discounting terminal payoff

    Returns:
        ControlVariateResult with adjusted NPV and variance statistics
    """
    N = len(mc_payoffs)
    spot_0 = spot_paths[0, 0]

    # 1. Analytic price (the "known" control value)
    analytic_price = bsm_analytic_price(spot_0, strike, T, rate, div_yield, vol, is_call)

    # 2. MC estimate of the control variable
    # Use the same terminal spot values to price a European option analytically per-path
    # Control payoff = discounted terminal intrinsic
    S_T = spot_paths[-1, :]
    if is_call:
        control_payoffs = np.maximum(S_T - strike, 0.0) * discount_factor
    else:
        control_payoffs = np.maximum(strike - S_T, 0.0) * discount_factor

    control_mean = float(np.mean(control_payoffs))

    # 3. Compute optimal β
    cov_matrix = np.cov(mc_payoffs, control_payoffs)
    var_control = cov_matrix[1, 1]

    if var_control > 1e-16:
        beta = cov_matrix[0, 1] / var_control
    else:
        beta = 1.0  # fallback

    # 4. Adjusted payoffs
    adjusted_payoffs = mc_payoffs - beta * (control_payoffs - analytic_price)

    raw_npv = float(np.mean(mc_payoffs))
    adjusted_npv = float(np.mean(adjusted_payoffs))

    std_raw = float(np.std(mc_payoffs) / np.sqrt(N))
    std_adjusted = float(np.std(adjusted_payoffs) / np.sqrt(N))

    # Variance ratio: how much we improved
    var_ratio = (np.var(adjusted_payoffs) / np.var(mc_payoffs)) if np.var(mc_payoffs) > 0 else 1.0

    logger.info(
        f"Control variate: raw={raw_npv:.6f}±{std_raw:.6f}, "
        f"adjusted={adjusted_npv:.6f}±{std_adjusted:.6f}, "
        f"β={beta:.4f}, variance_ratio={var_ratio:.4f}"
    )

    return ControlVariateResult(
        adjusted_npv=adjusted_npv,
        raw_npv=raw_npv,
        analytic_npv=analytic_price,
        beta=beta,
        variance_ratio=var_ratio,
        std_error_raw=std_raw,
        std_error_adjusted=std_adjusted,
    )


# ---------------------------------------------------------------------------
# Moment Matching
# ---------------------------------------------------------------------------

def apply_moment_matching(
    spot_paths: np.ndarray,
    rate: float,
    div_yield: float,
    T: float,
) -> np.ndarray:
    """
    Adjust simulated paths so the terminal spot mean matches the theoretical forward.

    E[S(T)] should equal S(0) * exp((r-q)*T).
    We scale all terminal values by the ratio of theoretical/simulated mean.

    This can also be applied at each time step for stronger correction.

    Args:
        spot_paths:  (T+1, N) simulated paths
        rate:        risk-free rate
        div_yield:   dividend yield
        T:           time to maturity

    Returns:
        Adjusted spot_paths (T+1, N) — a new array, original not modified
    """
    adjusted = spot_paths.copy()
    M = spot_paths.shape[0] - 1
    N = spot_paths.shape[1]
    S0 = spot_paths[0, 0]
    dt = T / M

    # Apply at each time step for maximum correction
    for t in range(1, M + 1):
        time_t = t * dt
        theoretical_mean = S0 * np.exp((rate - div_yield) * time_t)
        simulated_mean = np.mean(adjusted[t, :])

        if simulated_mean > 1e-10:
            adjusted[t, :] *= theoretical_mean / simulated_mean

    return adjusted


# ---------------------------------------------------------------------------
# Combined: moment matching + control variate
# ---------------------------------------------------------------------------

def apply_all_variance_reduction(
    spot_paths: np.ndarray,
    strike: float,
    T: float,
    rate: float,
    div_yield: float,
    vol: float,
    is_call: bool,
    use_moment_matching: bool = True,
    use_control_variate: bool = True,
) -> Tuple[np.ndarray, float, float, dict]:
    """
    Apply all variance reduction techniques and return adjusted payoffs.

    Args:
        spot_paths:          (T+1, N) simulated paths
        strike, T, rate, div_yield, vol: market parameters
        is_call:             True for call
        use_moment_matching: apply moment matching
        use_control_variate: apply control variate

    Returns:
        (adjusted_payoffs, npv, std_error, diagnostics_dict)
    """
    paths = spot_paths
    diagnostics = {}

    # Step 1: Moment matching
    if use_moment_matching:
        paths = apply_moment_matching(paths, rate, div_yield, T)
        diagnostics["moment_matching"] = True

        # Check correction
        S0 = spot_paths[0, 0]
        theoretical_terminal = S0 * np.exp((rate - div_yield) * T)
        actual_terminal = float(np.mean(paths[-1, :]))
        diagnostics["terminal_mean_error"] = abs(actual_terminal - theoretical_terminal)
    else:
        diagnostics["moment_matching"] = False

    # Compute payoffs
    discount_factor = np.exp(-rate * T)
    S_T = paths[-1, :]
    if is_call:
        payoffs = np.maximum(S_T - strike, 0.0) * discount_factor
    else:
        payoffs = np.maximum(strike - S_T, 0.0) * discount_factor

    # Step 2: Control variate
    if use_control_variate:
        cv_result = apply_control_variate(
            mc_payoffs=payoffs,
            spot_paths=paths,
            strike=strike,
            T=T,
            rate=rate,
            div_yield=div_yield,
            vol=vol,
            is_call=is_call,
            discount_factor=discount_factor,
        )
        diagnostics["control_variate"] = {
            "beta": cv_result.beta,
            "variance_ratio": cv_result.variance_ratio,
            "analytic_price": cv_result.analytic_npv,
        }
        return payoffs, cv_result.adjusted_npv, cv_result.std_error_adjusted, diagnostics
    else:
        diagnostics["control_variate"] = False
        npv = float(np.mean(payoffs))
        std_err = float(np.std(payoffs) / np.sqrt(len(payoffs)))
        return payoffs, npv, std_err, diagnostics
