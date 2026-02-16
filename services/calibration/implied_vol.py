"""
Implied Volatility Solver.

Computes the Black-Scholes implied volatility from a market option price.

Three methods:
1. Bisection:       Robust, always converges, O(50) iterations
2. Newton-Raphson:  Fast (quadratic convergence), needs good initial guess
3. QuantLib:        Uses QuantLib's built-in solver

The bisection method is the default — it's the most robust for production
use where you might encounter extreme moneyness or near-expiry options.

Usage:
    from services.calibration.implied_vol import (
        implied_vol_bisection,
        implied_vol_newton,
        implied_vol_quantlib,
        ImpliedVolSolver,
    )

    # Quick function call
    iv = implied_vol_bisection(
        market_price=10.45,
        spot=100.0,
        strike=105.0,
        T=1.0,
        rate=0.05,
        div_yield=0.02,
        is_call=True,
    )

    # Full solver with diagnostics
    solver = ImpliedVolSolver()
    result = solver.solve(
        market_price=10.45,
        spot=100.0, strike=105.0, T=1.0,
        rate=0.05, div_yield=0.02, is_call=True,
    )
    print(result.implied_vol, result.iterations, result.converged)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.stats import norm

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BSM price function (needed for root finding)
# ---------------------------------------------------------------------------

def bsm_price(
    spot: float,
    strike: float,
    T: float,
    rate: float,
    div_yield: float,
    vol: float,
    is_call: bool,
) -> float:
    """Black-Scholes-Merton price."""
    if T <= 0 or vol <= 0:
        if is_call:
            return max(spot * math.exp(-div_yield * T) - strike * math.exp(-rate * T), 0.0)
        else:
            return max(strike * math.exp(-rate * T) - spot * math.exp(-div_yield * T), 0.0)

    d1 = (math.log(spot / strike) + (rate - div_yield + 0.5 * vol ** 2) * T) / (vol * math.sqrt(T))
    d2 = d1 - vol * math.sqrt(T)

    if is_call:
        return (
            spot * math.exp(-div_yield * T) * norm.cdf(d1)
            - strike * math.exp(-rate * T) * norm.cdf(d2)
        )
    else:
        return (
            strike * math.exp(-rate * T) * norm.cdf(-d2)
            - spot * math.exp(-div_yield * T) * norm.cdf(-d1)
        )


def bsm_vega(
    spot: float,
    strike: float,
    T: float,
    rate: float,
    div_yield: float,
    vol: float,
) -> float:
    """BSM vega = ∂V/∂σ = S*exp(-qT)*N'(d1)*√T."""
    if T <= 0 or vol <= 0:
        return 0.0

    d1 = (math.log(spot / strike) + (rate - div_yield + 0.5 * vol ** 2) * T) / (vol * math.sqrt(T))
    return spot * math.exp(-div_yield * T) * norm.pdf(d1) * math.sqrt(T)


# ---------------------------------------------------------------------------
# Solver result
# ---------------------------------------------------------------------------

@dataclass
class ImpliedVolResult:
    """Output of implied vol computation."""
    implied_vol: float
    converged: bool
    iterations: int
    error: float            # |BSM(iv) - market_price|
    method: str
    market_price: float
    model_price: float


# ---------------------------------------------------------------------------
# Bisection method
# ---------------------------------------------------------------------------

def implied_vol_bisection(
    market_price: float,
    spot: float,
    strike: float,
    T: float,
    rate: float,
    div_yield: float = 0.0,
    is_call: bool = True,
    tol: float = 1e-8,
    max_iter: int = 100,
    vol_lo: float = 1e-6,
    vol_hi: float = 5.0,
) -> float:
    """
    Implied vol via bisection.

    Robust — always converges if the root exists in [vol_lo, vol_hi].
    Typical convergence: ~30 iterations for 1e-8 tolerance.

    Returns implied vol (float). Raises ValueError if no root found.
    """
    # Validate inputs
    if market_price <= 0:
        raise ValueError(f"market_price must be positive, got {market_price}")
    if T <= 0:
        raise ValueError(f"T must be positive, got {T}")

    # Check bounds
    price_lo = bsm_price(spot, strike, T, rate, div_yield, vol_lo, is_call)
    price_hi = bsm_price(spot, strike, T, rate, div_yield, vol_hi, is_call)

    if market_price < price_lo:
        raise ValueError(
            f"Market price {market_price:.6f} below minimum BSM price "
            f"{price_lo:.6f} at vol={vol_lo}"
        )
    if market_price > price_hi:
        raise ValueError(
            f"Market price {market_price:.6f} above maximum BSM price "
            f"{price_hi:.6f} at vol={vol_hi}. "
            f"Increase vol_hi or check inputs."
        )

    # Bisection
    for _ in range(max_iter):
        vol_mid = 0.5 * (vol_lo + vol_hi)
        price_mid = bsm_price(spot, strike, T, rate, div_yield, vol_mid, is_call)

        if abs(price_mid - market_price) < tol:
            return vol_mid

        if price_mid < market_price:
            vol_lo = vol_mid
        else:
            vol_hi = vol_mid

    # Return best guess
    return 0.5 * (vol_lo + vol_hi)


# ---------------------------------------------------------------------------
# Newton-Raphson method
# ---------------------------------------------------------------------------

def implied_vol_newton(
    market_price: float,
    spot: float,
    strike: float,
    T: float,
    rate: float,
    div_yield: float = 0.0,
    is_call: bool = True,
    tol: float = 1e-8,
    max_iter: int = 50,
    initial_guess: Optional[float] = None,
) -> float:
    """
    Implied vol via Newton-Raphson.

    Fast quadratic convergence — typically 4-6 iterations.
    Requires a reasonable initial guess.

    Falls back to bisection if Newton diverges.
    """
    # Initial guess: Brenner-Subrahmanyam approximation
    if initial_guess is None:
        initial_guess = math.sqrt(2 * math.pi / T) * market_price / spot

    vol = max(initial_guess, 0.01)

    for i in range(max_iter):
        price = bsm_price(spot, strike, T, rate, div_yield, vol, is_call)
        vega = bsm_vega(spot, strike, T, rate, div_yield, vol)

        if abs(price - market_price) < tol:
            return vol

        if vega < 1e-12:
            # Vega too small — Newton won't work, fall back
            break

        vol_new = vol - (price - market_price) / vega

        # Guard against negative vol
        if vol_new <= 0:
            vol = vol / 2
        else:
            vol = vol_new

    # Fall back to bisection
    logger.debug(
        f"Newton-Raphson did not converge in {max_iter} iterations. "
        f"Falling back to bisection."
    )
    return implied_vol_bisection(
        market_price, spot, strike, T, rate, div_yield, is_call, tol
    )


# ---------------------------------------------------------------------------
# QuantLib wrapper
# ---------------------------------------------------------------------------

def implied_vol_quantlib(
    market_price: float,
    spot: float,
    strike: float,
    T: float,
    rate: float,
    div_yield: float = 0.0,
    is_call: bool = True,
    tol: float = 1e-8,
) -> float:
    """
    Implied vol using QuantLib's built-in solver.

    Uses QuantLib's VanillaOption.impliedVolatility() which internally
    uses Brent's method.
    """
    import QuantLib as ql

    # Set up QuantLib environment
    today = ql.Date.todaysDate()
    ql.Settings.instance().evaluationDate = today

    # Expiry
    expiry_date = today + ql.Period(int(round(T * 365)), ql.Days)

    # Option
    ql_type = ql.Option.Call if is_call else ql.Option.Put
    payoff = ql.PlainVanillaPayoff(ql_type, strike)
    exercise = ql.EuropeanExercise(expiry_date)
    option = ql.VanillaOption(payoff, exercise)

    # Process (use a dummy vol — we're solving for it)
    spot_handle = ql.QuoteHandle(ql.SimpleQuote(spot))
    rate_handle = ql.YieldTermStructureHandle(
        ql.FlatForward(today, rate, ql.Actual365Fixed())
    )
    div_handle = ql.YieldTermStructureHandle(
        ql.FlatForward(today, div_yield, ql.Actual365Fixed())
    )
    vol_handle = ql.BlackVolTermStructureHandle(
        ql.BlackConstantVol(today, ql.NullCalendar(), 0.20, ql.Actual365Fixed())
    )

    process = ql.BlackScholesMertonProcess(
        spot_handle, div_handle, rate_handle, vol_handle
    )

    # Use QuantLib's implied vol solver
    iv = option.impliedVolatility(
        market_price, process, tol, 1000, 1e-6, 5.0
    )

    return iv


# ---------------------------------------------------------------------------
# Full solver with diagnostics
# ---------------------------------------------------------------------------

@dataclass
class ImpliedVolSolver:
    """
    Full-featured implied vol solver with diagnostics.

    Tries Newton-Raphson first, falls back to bisection.
    Reports convergence info.
    """

    method: str = "newton"  # "newton", "bisection", "quantlib"
    tol: float = 1e-8
    max_iter: int = 100

    def solve(
        self,
        market_price: float,
        spot: float,
        strike: float,
        T: float,
        rate: float,
        div_yield: float = 0.0,
        is_call: bool = True,
    ) -> ImpliedVolResult:
        """Solve for implied vol with full diagnostics."""
        try:
            if self.method == "newton":
                iv = implied_vol_newton(
                    market_price, spot, strike, T, rate, div_yield, is_call,
                    tol=self.tol, max_iter=self.max_iter,
                )
            elif self.method == "bisection":
                iv = implied_vol_bisection(
                    market_price, spot, strike, T, rate, div_yield, is_call,
                    tol=self.tol, max_iter=self.max_iter,
                )
            elif self.method == "quantlib":
                iv = implied_vol_quantlib(
                    market_price, spot, strike, T, rate, div_yield, is_call,
                    tol=self.tol,
                )
            else:
                raise ValueError(f"Unknown method: {self.method}")

            model_price = bsm_price(spot, strike, T, rate, div_yield, iv, is_call)
            error = abs(model_price - market_price)

            return ImpliedVolResult(
                implied_vol=iv,
                converged=error < self.tol * 10,
                iterations=0,  # not tracked per-call for simplicity
                error=error,
                method=self.method,
                market_price=market_price,
                model_price=model_price,
            )

        except Exception as e:
            logger.error(f"Implied vol solve failed: {e}")
            return ImpliedVolResult(
                implied_vol=float("nan"),
                converged=False,
                iterations=0,
                error=float("inf"),
                method=self.method,
                market_price=market_price,
                model_price=0.0,
            )

    def solve_surface(
        self,
        market_data: list,
        spot: float,
        rate: float,
        div_yield: float = 0.0,
    ) -> list:
        """
        Solve implied vols for a grid of options.

        market_data: list of dicts with keys:
            strike, T, price, is_call (optional, default True)

        Returns list of ImpliedVolResult.
        """
        results = []
        for entry in market_data:
            result = self.solve(
                market_price=entry["price"],
                spot=spot,
                strike=entry["strike"],
                T=entry["T"],
                rate=rate,
                div_yield=div_yield,
                is_call=entry.get("is_call", True),
            )
            results.append(result)
        return results