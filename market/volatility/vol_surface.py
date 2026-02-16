"""
Volatility surface construction utilities.

Provides builders for:
- Flat vol surfaces
- Black variance surfaces from strike/expiry grids
- SABR smile fitting
- SVI parameterization
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

import QuantLib as ql
import numpy as np

from core.types.value_objects import PricingDate


# ---------------------------------------------------------------------------
# Flat Vol
# ---------------------------------------------------------------------------

def build_flat_vol(
    pricing_date: PricingDate,
    vol: float,
    calendar: ql.Calendar = ql.NullCalendar(),
    day_count: ql.DayCounter = ql.Actual365Fixed(),
) -> ql.BlackVolTermStructureHandle:
    """Flat Black volatility surface."""
    surface = ql.BlackConstantVol(
        pricing_date.to_ql(), calendar, vol, day_count
    )
    return ql.BlackVolTermStructureHandle(surface)


# ---------------------------------------------------------------------------
# Grid-Based Black Vol Surface
# ---------------------------------------------------------------------------

@dataclass
class VolSurfaceDefinition:
    """Defines a vol surface from a strike × expiry grid."""
    pricing_date: PricingDate
    strikes: List[float]                    # sorted list of strikes
    expiry_dates: List[date]                # sorted list of expiry dates
    vols: List[List[float]]                 # vols[expiry_idx][strike_idx]
    calendar: ql.Calendar = None
    day_count: ql.DayCounter = None

    def __post_init__(self):
        if self.calendar is None:
            self.calendar = ql.NullCalendar()
        if self.day_count is None:
            self.day_count = ql.Actual365Fixed()

        # Validate dimensions
        assert len(self.vols) == len(self.expiry_dates), \
            f"Vol matrix rows ({len(self.vols)}) != expiry count ({len(self.expiry_dates)})"
        for i, row in enumerate(self.vols):
            assert len(row) == len(self.strikes), \
                f"Vol matrix row {i} width ({len(row)}) != strike count ({len(self.strikes)})"


class VolSurfaceBuilder:
    """Builds a QuantLib BlackVarianceSurface from a grid."""

    def build(self, definition: VolSurfaceDefinition) -> ql.BlackVolTermStructureHandle:
        ql_date = definition.pricing_date.to_ql()

        ql_expiries = [
            ql.Date(d.day, d.month, d.year) for d in definition.expiry_dates
        ]

        # QuantLib expects a Matrix(strikes x expiries)
        vol_matrix = ql.Matrix(len(definition.strikes), len(definition.expiry_dates))
        for i, strike_idx in enumerate(range(len(definition.strikes))):
            for j, expiry_idx in enumerate(range(len(definition.expiry_dates))):
                vol_matrix[i][j] = definition.vols[expiry_idx][strike_idx]

        surface = ql.BlackVarianceSurface(
            ql_date,
            definition.calendar,
            ql_expiries,
            definition.strikes,
            vol_matrix,
            definition.day_count,
        )
        surface.enableExtrapolation()
        return ql.BlackVolTermStructureHandle(surface)


# ---------------------------------------------------------------------------
# SABR Smile Section
# ---------------------------------------------------------------------------

@dataclass
class SABRParams:
    """SABR model parameters for a single expiry."""
    alpha: float     # initial vol level
    beta: float      # CEV exponent (usually fixed: 0, 0.5, or 1)
    rho: float       # spot-vol correlation
    nu: float        # vol of vol
    forward: float   # forward price
    expiry: float    # time to expiry in years

    def validate(self) -> bool:
        """Check SABR parameter bounds."""
        return (
            self.alpha > 0
            and 0 <= self.beta <= 1
            and -1 < self.rho < 1
            and self.nu >= 0
            and self.forward > 0
            and self.expiry > 0
        )

    def implied_vol(self, strike: float) -> float:
        """Compute SABR implied vol for a given strike."""
        try:
            return ql.sabrVolatility(
                strike, self.forward, self.expiry,
                self.alpha, self.beta, self.nu, self.rho,
            )
        except RuntimeError:
            # Fallback for ATM
            return self.alpha


def calibrate_sabr(
    forward: float,
    expiry_years: float,
    strikes: List[float],
    market_vols: List[float],
    beta: float = 0.5,
    initial_alpha: float = 0.1,
    initial_rho: float = -0.3,
    initial_nu: float = 0.5,
) -> SABRParams:
    """
    Calibrate SABR parameters to market smile for a single expiry.

    Fixes beta, calibrates alpha, rho, nu.
    """
    from scipy.optimize import minimize

    def objective(params):
        alpha, rho, nu = params
        if alpha <= 0 or abs(rho) >= 1 or nu < 0:
            return 1e10
        total_err = 0.0
        for strike, mkt_vol in zip(strikes, market_vols):
            try:
                model_vol = ql.sabrVolatility(
                    strike, forward, expiry_years, alpha, beta, nu, rho
                )
                total_err += (model_vol - mkt_vol) ** 2
            except RuntimeError:
                total_err += 1e6
        return total_err

    result = minimize(
        objective,
        x0=[initial_alpha, initial_rho, initial_nu],
        method="Nelder-Mead",
        options={"maxiter": 5000, "xatol": 1e-8, "fatol": 1e-10},
    )

    alpha_cal, rho_cal, nu_cal = result.x
    return SABRParams(
        alpha=alpha_cal,
        beta=beta,
        rho=rho_cal,
        nu=nu_cal,
        forward=forward,
        expiry=expiry_years,
    )


# ---------------------------------------------------------------------------
# SVI Parameterization
# ---------------------------------------------------------------------------

@dataclass
class SVIParams:
    """
    Stochastic Volatility Inspired (SVI) parameterization.

    w(k) = a + b * (rho * (k - m) + sqrt((k - m)^2 + sigma^2))

    where k = log(K/F) is log-moneyness, w = sigma_BS^2 * T is total variance.
    """
    a: float       # vertical translation
    b: float       # angle between left/right wings
    rho: float     # rotation (left/right asymmetry)
    m: float       # horizontal translation
    sigma: float   # smoothing at ATM

    def total_variance(self, log_moneyness: float) -> float:
        k = log_moneyness
        return self.a + self.b * (
            self.rho * (k - self.m) + np.sqrt((k - self.m) ** 2 + self.sigma ** 2)
        )

    def implied_vol(self, log_moneyness: float, time_to_expiry: float) -> float:
        w = self.total_variance(log_moneyness)
        if w < 0 or time_to_expiry <= 0:
            return 0.0
        return np.sqrt(w / time_to_expiry)
