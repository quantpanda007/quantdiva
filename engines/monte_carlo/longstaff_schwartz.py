"""
Longstaff-Schwartz least-squares Monte Carlo backward pass.

Separated from the engine for:
- Clean unit testing of the regression logic
- Reuse across American and Bermudan engines
- Easy extension (different basis functions, regularization)

Fixes from audit:
- Fully vectorized — no O(N²) loops over paths
- Discount factors computed correctly per step
- Exercise boundary extracted cleanly
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class LSResult:
    """Output of Longstaff-Schwartz backward pass."""
    continuation_values: np.ndarray    # (T+1, N) — estimated continuation
    exercise_flags: np.ndarray         # (T+1, N) — boolean, True = exercise here
    exercise_boundary: np.ndarray      # (T+1,) — spot level of exercise boundary
    cashflow_times: np.ndarray         # (N,) — time index when each path exercises
    cashflow_values: np.ndarray        # (N,) — payoff at exercise for each path
    npv: float = 0.0
    std_error: float = 0.0
    confidence_interval: tuple = (0.0, 0.0)
    regression_coefficients: Optional[List[np.ndarray]] = None  # per exercise step


def longstaff_schwartz(
    spot_paths: np.ndarray,
    intrinsic_values: np.ndarray,
    discount_factors: np.ndarray,
    is_call: bool,
    poly_degree: int = 3,
    exercise_indices: Optional[List[int]] = None,
) -> LSResult:
    """
    Run the Longstaff-Schwartz backward regression.

    Algorithm:
    1. At maturity: cashflow = intrinsic value
    2. Step backward through exercise dates:
       a. Find in-the-money paths
       b. Regress discounted future cashflows on spot (polynomial basis)
       c. Exercise if intrinsic > regression-estimated continuation
    3. NPV = mean of discounted cashflows at t=0

    Args:
        spot_paths:         (T+1, N) simulated spot prices
        intrinsic_values:   (T+1, N) payoff at each step
        discount_factors:   (T+1,) discount factor at each step: df[i] = exp(-r * t_i)
        is_call:            True for call, False for put
        poly_degree:        Degree of polynomial regression basis
        exercise_indices:   Allowed exercise steps. None = all steps (American).
                            For Bermudan, provide subset of step indices.

    Returns:
        LSResult with full diagnostics
    """
    M_plus_1, N = spot_paths.shape
    M = M_plus_1 - 1

    # Determine exercise steps
    if exercise_indices is None:
        # American: every step from 1 to M
        ex_steps = list(range(1, M + 1))
    else:
        ex_steps = sorted([i for i in exercise_indices if 0 < i <= M])

    if not ex_steps:
        raise ValueError("No valid exercise steps provided.")

    # Initialize
    continuation = np.zeros((M + 1, N))
    exercise_flag = np.zeros((M + 1, N), dtype=bool)
    boundary = np.full(M + 1, np.nan)
    regression_coeffs = []

    # Each path's cashflow: initially exercise at maturity
    cf_time = np.full(N, M, dtype=int)
    cf_value = intrinsic_values[M, :].copy()

    # Continuation at maturity = intrinsic
    continuation[M, :] = intrinsic_values[M, :]

    # Backward pass
    for t in reversed(ex_steps[:-1]):  # skip the last exercise step (maturity)
        iv_t = intrinsic_values[t, :]

        # In-the-money mask
        itm_mask = iv_t > 0
        itm_idx = np.where(itm_mask)[0]

        if len(itm_idx) < poly_degree + 2:
            # Not enough ITM paths for reliable regression
            continuation[t, :] = np.inf  # don't exercise
            regression_coeffs.append(None)
            continue

        # Discounted future cashflows for ALL paths (vectorized)
        # For each path j: future_cf[j] = cf_value[j] * df(cf_time[j]) / df(t)
        # This is the realized discounted cashflow from the current best strategy
        time_diff = cf_time - t  # steps between t and exercise
        dt_per_step = discount_factors[1] / discount_factors[0]  # exp(-r*dt) ratio

        # df_ratio[j] = discount_factors[cf_time[j]] / discount_factors[t]
        df_ratio = discount_factors[cf_time] / discount_factors[t]
        future_cf = cf_value * df_ratio

        # Regression on ITM paths only
        X_itm = spot_paths[t, itm_idx]
        Y_itm = future_cf[itm_idx]

        # Polynomial basis: [1, x, x², ..., x^d]
        # Normalize spot to reduce numerical issues
        X_mean = np.mean(X_itm)
        X_std = np.std(X_itm) if np.std(X_itm) > 1e-10 else 1.0
        X_norm = (X_itm - X_mean) / X_std

        basis_itm = np.column_stack([X_norm ** k for k in range(poly_degree + 1)])

        # Least squares regression
        try:
            coeffs, _, _, _ = np.linalg.lstsq(basis_itm, Y_itm, rcond=None)
        except np.linalg.LinAlgError:
            logger.warning(f"LS regression failed at step {t}. Skipping exercise.")
            continuation[t, :] = np.inf
            regression_coeffs.append(None)
            continue

        regression_coeffs.append(coeffs)

        # Continuation estimate for ITM paths
        cont_est_itm = basis_itm @ coeffs

        # Full continuation estimate (for diagnostics)
        X_all_norm = (spot_paths[t, :] - X_mean) / X_std
        basis_all = np.column_stack([X_all_norm ** k for k in range(poly_degree + 1)])
        continuation[t, :] = basis_all @ coeffs

        # Exercise decision: exercise if intrinsic > continuation (ITM paths only)
        exercise_mask_itm = iv_t[itm_idx] > cont_est_itm

        # Update cashflows for paths that exercise at t (vectorized)
        exercising = itm_idx[exercise_mask_itm]
        if len(exercising) > 0:
            cf_time[exercising] = t
            cf_value[exercising] = iv_t[exercising]
            exercise_flag[t, exercising] = True

        # Exercise boundary estimation
        if np.any(exercise_mask_itm) and not np.all(exercise_mask_itm):
            exercised_spots = X_itm[exercise_mask_itm]
            if is_call:
                boundary[t] = float(np.min(exercised_spots))
            else:
                boundary[t] = float(np.max(exercised_spots))

    # Compute NPV: discount each path's cashflow to t=0
    # npv[j] = cf_value[j] * discount_factors[cf_time[j]]
    discounted_payoffs = cf_value * discount_factors[cf_time]

    npv = float(np.mean(discounted_payoffs))
    std_err = float(np.std(discounted_payoffs) / np.sqrt(N))
    ci = (npv - 1.96 * std_err, npv + 1.96 * std_err)

    return LSResult(
        continuation_values=continuation,
        exercise_flags=exercise_flag,
        exercise_boundary=boundary,
        cashflow_times=cf_time,
        cashflow_values=cf_value,
        npv=npv,
        std_error=std_err,
        confidence_interval=ci,
        regression_coefficients=list(reversed(regression_coeffs)),
    )
