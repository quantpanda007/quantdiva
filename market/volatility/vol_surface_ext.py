"""
Extended volatility surface toolkit.

Builds on the existing vol_surface.py with:
1. SVI calibration (fit SVI params to market smile per expiry)
2. Local vol extraction (Dupire's formula from implied vol surface)
3. Vol surface manager (unified interface for MarketEnvironment)
4. Smile interpolation and extrapolation
5. Vol surface diagnostics (arbitrage checks, butterfly spread test)

Usage:
    from market.volatility.vol_surface_ext import (
        calibrate_svi,
        SVIVolSurface,
        LocalVolSurface,
        VolSurfaceManager,
    )

    # Calibrate SVI per expiry
    svi_surface = SVIVolSurface.from_market_quotes(
        pricing_date, strikes, expiries, vol_matrix, spot, rate, div_yield
    )

    # Extract local vol
    local_vol = LocalVolSurface.from_implied(svi_surface, ...)

    # Unified manager
    manager = VolSurfaceManager(pricing_date)
    manager.add_surface("AAPL", svi_surface)
    market_env.vol_surfaces["AAPL"] = manager.get_ql_handle("AAPL")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy.optimize import minimize

import QuantLib as ql

from core.types.value_objects import PricingDate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SVI Calibration
# ---------------------------------------------------------------------------

@dataclass
class SVISlice:
    """
    SVI parameters for a single expiry slice.

    Total variance: w(k) = a + b * (ρ(k-m) + √((k-m)² + σ²))
    where k = ln(K/F) is log-moneyness.
    """
    a: float
    b: float
    rho: float
    m: float
    sigma: float
    T: float          # time to expiry
    forward: float    # forward price for this expiry
    fit_error: float = 0.0  # calibration RMSE

    def total_variance(self, k: float) -> float:
        """Total variance w(k) at log-moneyness k."""
        return self.a + self.b * (
            self.rho * (k - self.m)
            + np.sqrt((k - self.m) ** 2 + self.sigma ** 2)
        )

    def implied_vol(self, strike: float) -> float:
        """BSM implied vol at a given strike."""
        k = np.log(strike / self.forward)
        w = self.total_variance(k)
        if w <= 0 or self.T <= 0:
            return 0.0
        return float(np.sqrt(max(w / self.T, 0.0)))

    def implied_vol_grid(self, strikes: np.ndarray) -> np.ndarray:
        """Vectorized implied vol for array of strikes."""
        k = np.log(strikes / self.forward)
        w = self.a + self.b * (
            self.rho * (k - self.m)
            + np.sqrt((k - self.m) ** 2 + self.sigma ** 2)
        )
        w = np.maximum(w, 0.0)
        return np.sqrt(w / self.T)

    def is_arbitrage_free(self) -> bool:
        """
        Check Gatheral's no-butterfly-arbitrage condition:
        b >= 0, b*(1+|ρ|) <= 4, σ > 0
        """
        if self.b < 0:
            return False
        if self.b * (1 + abs(self.rho)) > 4:
            return False
        if self.sigma <= 0:
            return False
        return True


def calibrate_svi(
    forward: float,
    T: float,
    strikes: List[float],
    market_vols: List[float],
    initial_guess: Optional[Dict[str, float]] = None,
) -> SVISlice:
    """
    Calibrate SVI parameters to a single expiry smile.

    Args:
        forward:     Forward price at this expiry
        T:           Time to expiry in years
        strikes:     Market strike prices
        market_vols: Market implied vols at each strike

    Returns:
        SVISlice with calibrated parameters
    """
    strikes_arr = np.array(strikes)
    vols_arr = np.array(market_vols)
    k_arr = np.log(strikes_arr / forward)
    w_market = vols_arr ** 2 * T  # total variance

    # Initial guess
    if initial_guess is None:
        atm_var = float(np.interp(0.0, k_arr, w_market))
        initial_guess = {
            "a": atm_var,
            "b": 0.1,
            "rho": -0.3,
            "m": 0.0,
            "sigma": 0.1,
        }

    def objective(params):
        a, b, rho, m, sigma = params
        # Constraints
        if b < 0 or sigma <= 0 or abs(rho) >= 1:
            return 1e10
        if a + b * sigma * np.sqrt(1 - rho ** 2) < 0:
            return 1e10  # ensure w(k) >= 0

        w_model = a + b * (
            rho * (k_arr - m) + np.sqrt((k_arr - m) ** 2 + sigma ** 2)
        )
        return float(np.sum((w_model - w_market) ** 2))

    x0 = [
        initial_guess["a"],
        initial_guess["b"],
        initial_guess["rho"],
        initial_guess["m"],
        initial_guess["sigma"],
    ]

    result = minimize(
        objective,
        x0=x0,
        method="Nelder-Mead",
        options={"maxiter": 10000, "xatol": 1e-10, "fatol": 1e-12},
    )

    a, b, rho, m, sigma = result.x
    rmse = float(np.sqrt(result.fun / len(strikes)))

    svi = SVISlice(
        a=a, b=b, rho=rho, m=m, sigma=sigma,
        T=T, forward=forward, fit_error=rmse,
    )

    if not svi.is_arbitrage_free():
        logger.warning(
            f"SVI slice at T={T:.3f} fails arbitrage check: "
            f"b={b:.4f}, ρ={rho:.4f}, σ={sigma:.4f}"
        )

    return svi


# ---------------------------------------------------------------------------
# SVI Vol Surface (multi-expiry)
# ---------------------------------------------------------------------------

@dataclass
class SVIVolSurface:
    """
    Full implied vol surface built from SVI slices per expiry.

    Interpolates between expiries in total variance space
    (linear in variance is arbitrage-free if slices are).
    """
    pricing_date: PricingDate
    slices: List[SVISlice] = field(default_factory=list)
    spot: float = 100.0
    rate: float = 0.05
    div_yield: float = 0.0

    @classmethod
    def from_market_quotes(
        cls,
        pricing_date: PricingDate,
        strikes: List[float],
        expiry_dates: List[date],
        vol_matrix: List[List[float]],
        spot: float,
        rate: float,
        div_yield: float = 0.0,
    ) -> SVIVolSurface:
        """
        Build SVI surface from market vol quotes.

        vol_matrix[expiry_idx][strike_idx] = implied vol
        """
        dc = ql.Actual365Fixed()
        ql_pricing = pricing_date.to_ql()

        surface = cls(
            pricing_date=pricing_date,
            spot=spot,
            rate=rate,
            div_yield=div_yield,
        )

        for i, expiry in enumerate(expiry_dates):
            ql_expiry = ql.Date(expiry.day, expiry.month, expiry.year)
            T = dc.yearFraction(ql_pricing, ql_expiry)
            if T <= 0:
                continue

            forward = spot * np.exp((rate - div_yield) * T)
            market_vols = vol_matrix[i]

            svi_slice = calibrate_svi(forward, T, strikes, market_vols)
            surface.slices.append(svi_slice)

            logger.info(
                f"SVI T={T:.3f}: a={svi_slice.a:.4f}, b={svi_slice.b:.4f}, "
                f"ρ={svi_slice.rho:.4f}, m={svi_slice.m:.4f}, σ={svi_slice.sigma:.4f}, "
                f"RMSE={svi_slice.fit_error:.6f}, "
                f"arb-free={'✓' if svi_slice.is_arbitrage_free() else '✗'}"
            )

        return surface

    def implied_vol(self, T: float, strike: float) -> float:
        """
        Interpolate implied vol at arbitrary (T, strike).

        Uses linear interpolation in total variance between slices.
        """
        if not self.slices:
            return 0.0

        # Edge cases
        if T <= self.slices[0].T:
            return self.slices[0].implied_vol(strike)
        if T >= self.slices[-1].T:
            return self.slices[-1].implied_vol(strike)

        # Find bracketing slices
        for j in range(len(self.slices) - 1):
            if self.slices[j].T <= T <= self.slices[j + 1].T:
                s1 = self.slices[j]
                s2 = self.slices[j + 1]

                # Linear interpolation in total variance
                w = (T - s1.T) / (s2.T - s1.T)
                forward = self.spot * np.exp((self.rate - self.div_yield) * T)
                k = np.log(strike / forward)

                # Interpolate total variance
                w1 = s1.total_variance(np.log(strike / s1.forward))
                w2 = s2.total_variance(np.log(strike / s2.forward))
                w_interp = (1 - w) * w1 + w * w2

                if w_interp <= 0 or T <= 0:
                    return 0.0
                return float(np.sqrt(w_interp / T))

        return self.slices[-1].implied_vol(strike)

    def to_ql_surface(self) -> ql.BlackVolTermStructureHandle:
        """Convert to QuantLib BlackVolTermStructure for use in engines."""
        ql_date = self.pricing_date.to_ql()

        # Build a grid of vols for QuantLib
        # Use the strike range from slices
        all_forwards = [s.forward for s in self.slices]
        avg_fwd = np.mean(all_forwards)

        strikes = np.linspace(avg_fwd * 0.5, avg_fwd * 1.5, 21)
        expiry_dates = []
        vol_matrix = ql.Matrix(len(strikes), len(self.slices))

        for j, s in enumerate(self.slices):
            days = int(round(s.T * 365))
            expiry_dates.append(ql_date + ql.Period(days, ql.Days))
            vols = s.implied_vol_grid(strikes)
            for i in range(len(strikes)):
                vol_matrix[i][j] = max(vols[i], 0.001)

        surface = ql.BlackVarianceSurface(
            ql_date,
            ql.NullCalendar(),
            expiry_dates,
            list(strikes),
            vol_matrix,
            ql.Actual365Fixed(),
        )
        surface.enableExtrapolation()
        return ql.BlackVolTermStructureHandle(surface)

    def fit_report(self) -> List[Dict[str, Any]]:
        """Report fit quality per slice."""
        return [
            {
                "T": s.T,
                "forward": round(s.forward, 4),
                "a": round(s.a, 6),
                "b": round(s.b, 6),
                "rho": round(s.rho, 6),
                "m": round(s.m, 6),
                "sigma": round(s.sigma, 6),
                "rmse": round(s.fit_error, 8),
                "arbitrage_free": s.is_arbitrage_free(),
            }
            for s in self.slices
        ]


# ---------------------------------------------------------------------------
# Local Volatility (Dupire)
# ---------------------------------------------------------------------------

@dataclass
class LocalVolSurface:
    """
    Dupire local volatility extracted from an implied vol surface.

    Dupire's formula:
        σ_L²(K,T) = (∂w/∂T) / (1 - k/(w) * ∂w/∂k + 1/4 * (-1/4 - 1/w + k²/w²)(∂w/∂k)² + 1/2 * ∂²w/∂k²)

    where w = σ²T is total variance, k = ln(K/F).

    In practice, we use QuantLib's LocalVolSurface which handles
    the numerical differentiation internally.
    """
    pricing_date: PricingDate
    _ql_local_vol: Optional[Any] = field(default=None, repr=False)
    _ql_handle: Optional[Any] = field(default=None, repr=False)

    @classmethod
    def from_implied_surface(
        cls,
        pricing_date: PricingDate,
        implied_vol_handle: ql.BlackVolTermStructureHandle,
        spot: float,
        risk_free_handle: ql.YieldTermStructureHandle,
        dividend_handle: ql.YieldTermStructureHandle,
    ) -> LocalVolSurface:
        """
        Extract local vol surface from implied vol surface via Dupire.

        Uses QuantLib's LocalVolSurface which numerically computes:
            σ_local(K,T) from σ_implied(K,T)
        """
        ql_date = pricing_date.to_ql()
        spot_handle = ql.QuoteHandle(ql.SimpleQuote(spot))

        local_vol = ql.LocalVolSurface(
            implied_vol_handle,
            risk_free_handle,
            dividend_handle,
            spot_handle,
        )
        local_vol.enableExtrapolation()
        handle = ql.LocalVolTermStructureHandle(local_vol)

        surface = cls(pricing_date=pricing_date)
        surface._ql_local_vol = local_vol
        surface._ql_handle = handle
        return surface

    @classmethod
    def from_svi_surface(
        cls,
        svi_surface: SVIVolSurface,
        risk_free_handle: ql.YieldTermStructureHandle,
        dividend_handle: ql.YieldTermStructureHandle,
    ) -> LocalVolSurface:
        """Build local vol from an SVI surface."""
        implied_handle = svi_surface.to_ql_surface()
        return cls.from_implied_surface(
            pricing_date=svi_surface.pricing_date,
            implied_vol_handle=implied_handle,
            spot=svi_surface.spot,
            risk_free_handle=risk_free_handle,
            dividend_handle=dividend_handle,
        )

    def local_vol(self, T: float, strike: float) -> float:
        """Query local vol at (T, strike)."""
        if self._ql_local_vol is None:
            return 0.0
        try:
            return self._ql_local_vol.localVol(T, strike)
        except Exception:
            return 0.0

    def local_vol_grid(
        self,
        T_grid: np.ndarray,
        strike_grid: np.ndarray,
    ) -> np.ndarray:
        """Compute local vol on a (T, K) grid."""
        result = np.zeros((len(T_grid), len(strike_grid)))
        for i, T in enumerate(T_grid):
            for j, K in enumerate(strike_grid):
                result[i, j] = self.local_vol(float(T), float(K))
        return result

    @property
    def ql_handle(self) -> Optional[Any]:
        return self._ql_handle


# ---------------------------------------------------------------------------
# Vol Surface Diagnostics
# ---------------------------------------------------------------------------

def check_calendar_arbitrage(
    surface: SVIVolSurface,
    strikes: np.ndarray,
) -> List[Dict[str, Any]]:
    """
    Check for calendar arbitrage: total variance must be
    non-decreasing in T for each strike.

    Returns list of violations.
    """
    violations = []

    for K in strikes:
        prev_w = None
        for s in surface.slices:
            k = np.log(K / s.forward)
            w = s.total_variance(k)

            if prev_w is not None and w < prev_w - 1e-10:
                violations.append({
                    "type": "calendar_arbitrage",
                    "strike": float(K),
                    "T": s.T,
                    "total_var": w,
                    "prev_total_var": prev_w,
                })
            prev_w = w

    return violations


def check_butterfly_arbitrage(
    svi_slice: SVISlice,
    strikes: np.ndarray,
) -> List[Dict[str, Any]]:
    """
    Check for butterfly arbitrage: the density g(k) must be non-negative.

    g(k) = (1 - k*w'/(2w))² - w'²/4*(1/w + 1/4) + w''/2

    where w = w(k), w' = dw/dk, w'' = d²w/dk².
    Returns list of strikes where g(k) < 0.
    """
    violations = []
    dk = 0.001

    for K in strikes:
        k = np.log(K / svi_slice.forward)
        w = svi_slice.total_variance(k)
        w_up = svi_slice.total_variance(k + dk)
        w_down = svi_slice.total_variance(k - dk)

        w_prime = (w_up - w_down) / (2 * dk)
        w_double_prime = (w_up - 2 * w + w_down) / (dk ** 2)

        if w <= 0:
            continue

        g = (
            (1 - k * w_prime / (2 * w)) ** 2
            - w_prime ** 2 / 4 * (1.0 / w + 0.25)
            + w_double_prime / 2
        )

        if g < -1e-8:
            violations.append({
                "type": "butterfly_arbitrage",
                "strike": float(K),
                "T": svi_slice.T,
                "density": g,
            })

    return violations


# ---------------------------------------------------------------------------
# Vol Surface Manager
# ---------------------------------------------------------------------------

@dataclass
class VolSurfaceManager:
    """
    Unified vol surface manager for the pricing platform.

    Manages named vol surfaces and provides QuantLib handles
    for integration with MarketEnvironment.

    Supports:
    - Flat vol (quick pricing)
    - Grid-based (BlackVarianceSurface)
    - SVI-parameterized
    - Local vol (Dupire)
    """
    pricing_date: PricingDate
    _surfaces: Dict[str, Any] = field(default_factory=dict)
    _ql_handles: Dict[str, ql.BlackVolTermStructureHandle] = field(default_factory=dict)
    _local_vol_handles: Dict[str, Any] = field(default_factory=dict)

    def add_flat(self, underlying: str, vol: float) -> None:
        """Add a flat vol surface."""
        from market.curves.yield_curve import build_flat_vol
        handle = build_flat_vol(self.pricing_date, vol)
        self._surfaces[underlying] = {"type": "flat", "vol": vol}
        self._ql_handles[underlying] = handle

    def add_svi_surface(self, underlying: str, svi_surface: SVIVolSurface) -> None:
        """Add an SVI-parameterized vol surface."""
        self._surfaces[underlying] = {"type": "svi", "surface": svi_surface}
        self._ql_handles[underlying] = svi_surface.to_ql_surface()

    def add_grid_surface(
        self,
        underlying: str,
        strikes: List[float],
        expiry_dates: List[date],
        vol_matrix: List[List[float]],
    ) -> None:
        """Add a grid-based vol surface."""
        from market.volatility.vol_surface import VolSurfaceBuilder, VolSurfaceDefinition

        defn = VolSurfaceDefinition(
            pricing_date=self.pricing_date,
            strikes=strikes,
            expiry_dates=expiry_dates,
            vols=vol_matrix,
        )
        builder = VolSurfaceBuilder()
        handle = builder.build(defn)
        self._surfaces[underlying] = {"type": "grid", "definition": defn}
        self._ql_handles[underlying] = handle

    def add_local_vol(
        self,
        underlying: str,
        local_vol_surface: LocalVolSurface,
    ) -> None:
        """Add a local vol surface (extracted from implied)."""
        self._local_vol_handles[underlying] = local_vol_surface.ql_handle

    def get_ql_handle(self, underlying: str) -> ql.BlackVolTermStructureHandle:
        """Get QuantLib BlackVolTermStructureHandle for an underlying."""
        if underlying not in self._ql_handles:
            raise KeyError(
                f"No vol surface for '{underlying}'. "
                f"Available: {list(self._ql_handles.keys())}"
            )
        return self._ql_handles[underlying]

    def get_local_vol_handle(self, underlying: str):
        """Get local vol handle if available."""
        return self._local_vol_handles.get(underlying)

    def get_implied_vol(self, underlying: str, T: float, strike: float) -> float:
        """Query implied vol at (T, strike) for an underlying."""
        handle = self.get_ql_handle(underlying)
        return handle.blackVol(T, strike)

    def list_underlyings(self) -> List[str]:
        return list(self._ql_handles.keys())

    def summary(self) -> Dict[str, Any]:
        return {
            und: {
                "type": info.get("type", "unknown"),
                "has_local_vol": und in self._local_vol_handles,
            }
            for und, info in self._surfaces.items()
        }