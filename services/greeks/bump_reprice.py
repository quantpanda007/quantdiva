"""
Bump-and-Reprice Greeks.

Computes Greeks by perturbing market data and re-pricing.
Works with ANY engine and ANY instrument — no analytic formulas needed.

Methods:
    Central difference:  (V(x+h) - V(x-h)) / (2h)     — 1st order
    Second order:        (V(x+h) - 2V(x) + V(x-h)) / h²  — gamma-like
    Forward difference:  (V(x+h) - V(x)) / h           — less accurate

Supported risk factors:
    spot:     Delta (1st), Gamma (2nd)
    vol:      Vega
    rate:     Rho
    div:      Dividend sensitivity
    time:     Theta (roll forward 1 day)

Usage:
    from services.greeks.bump_reprice import BumpAndRepriceGreeks

    greeks_svc = BumpAndRepriceGreeks(pricing_service=ps)
    result = greeks_svc.compute(
        instrument=option,
        market_env=env,
        model_type="black_scholes",
        engine_type="monte_carlo",
        measures=["delta", "gamma", "vega", "theta", "rho"],
    )
    print(result)
    # {'delta': 0.6321, 'gamma': 0.0189, 'vega': 0.3752, 'theta': -0.0176, 'rho': 0.4123}
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import QuantLib as ql

from core.interfaces.base import BaseInstrument, MarketEnvironment
from core.types.value_objects import PricingDate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Greek result
# ---------------------------------------------------------------------------

@dataclass
class BumpGreeksResult:
    """Output of bump-and-reprice Greeks computation."""
    greeks: Dict[str, Optional[float]] = field(default_factory=dict)
    base_npv: float = 0.0
    bump_details: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Optional[float]]:
        return dict(self.greeks)

    def __repr__(self) -> str:
        g = ", ".join(
            f"{k}={v:.6f}" if v is not None else f"{k}=N/A"
            for k, v in self.greeks.items()
        )
        return f"BumpGreeksResult({g})"


# ---------------------------------------------------------------------------
# Market environment cloning helpers
# ---------------------------------------------------------------------------

def _bump_spot(market_env: MarketEnvironment, underlying: str, bump: float) -> MarketEnvironment:
    """Clone market env with bumped spot price."""
    env = copy.copy(market_env)
    env.spot_prices = dict(market_env.spot_prices)
    current = env.spot_prices.get(underlying, 100.0)
    env.spot_prices[underlying] = current + bump
    return env


def _bump_vol(market_env: MarketEnvironment, underlying: str, bump: float) -> MarketEnvironment:
    """
    Clone market env with bumped vol surface.

    Creates a new flat vol surface at (current_vol + bump).
    This is a simplification — in production you'd shift the entire surface.
    """
    env = copy.copy(market_env)
    env.vol_surfaces = dict(market_env.vol_surfaces)

    # Extract current ATM vol
    current_vol = 0.20
    try:
        spot = market_env.spot_prices.get(underlying, 100.0)
        current_vol = market_env.vol_surfaces[underlying].blackVol(1.0, spot)
    except Exception:
        pass

    new_vol = max(current_vol + bump, 0.001)
    env.vol_surfaces[underlying] = ql.BlackVolTermStructureHandle(
        ql.BlackConstantVol(
            market_env.pricing_date.to_ql(),
            ql.NullCalendar(),
            new_vol,
            ql.Actual365Fixed(),
        )
    )
    return env


def _bump_rate(market_env: MarketEnvironment, bump: float) -> MarketEnvironment:
    """Clone market env with bumped risk-free rate."""
    env = copy.copy(market_env)
    env.discount_curves = dict(market_env.discount_curves)

    # Extract current rate
    current_rate = 0.05
    for key in env.discount_curves:
        try:
            current_rate = env.discount_curves[key].zeroRate(
                1.0, ql.Continuous, ql.Annual
            ).rate()
            break
        except Exception:
            pass

    new_rate = current_rate + bump
    new_curve = ql.YieldTermStructureHandle(
        ql.FlatForward(
            market_env.pricing_date.to_ql(), new_rate, ql.Actual365Fixed()
        )
    )

    for key in env.discount_curves:
        env.discount_curves[key] = new_curve

    return env


def _bump_div(market_env: MarketEnvironment, underlying: str, bump: float) -> MarketEnvironment:
    """Clone market env with bumped dividend yield."""
    env = copy.copy(market_env)
    env.dividend_curves = dict(market_env.dividend_curves)

    div_key = f"{underlying}_div"

    current_div = 0.0
    try:
        current_div = market_env.dividend_curves[div_key].zeroRate(
            1.0, ql.Continuous, ql.Annual
        ).rate()
    except Exception:
        pass

    new_div = max(current_div + bump, 0.0)
    env.dividend_curves[div_key] = ql.YieldTermStructureHandle(
        ql.FlatForward(
            market_env.pricing_date.to_ql(), new_div, ql.Actual365Fixed()
        )
    )
    return env


def _bump_time(market_env: MarketEnvironment, days: int = 1) -> MarketEnvironment:
    """Clone market env with pricing date moved forward."""
    env = copy.copy(market_env)
    new_date = market_env.pricing_date.value + timedelta(days=days)
    env.pricing_date = PricingDate(new_date)
    return env


# ---------------------------------------------------------------------------
# Bump-and-Reprice Service
# ---------------------------------------------------------------------------

@dataclass
class BumpAndRepriceGreeks:
    """
    Computes Greeks via bump-and-reprice for any instrument/engine.

    Attributes:
        pricing_service:  PricingService instance for pricing
        spot_bump:        Absolute spot bump size (default: 1.0)
        vol_bump:         Absolute vol bump size (default: 0.01 = 1%)
        rate_bump:        Absolute rate bump size (default: 0.0001 = 1bp)
        div_bump:         Absolute div yield bump (default: 0.0001 = 1bp)
        theta_days:       Days to roll forward for theta (default: 1)
    """

    pricing_service: Any = None  # PricingService — Any to avoid circular import
    spot_bump: float = 1.0
    vol_bump: float = 0.01
    rate_bump: float = 0.0001
    div_bump: float = 0.0001
    theta_days: int = 1

    def compute(
        self,
        instrument: BaseInstrument,
        market_env: MarketEnvironment,
        model_type: str = "black_scholes",
        engine_type: str = "analytic",
        engine_params: Optional[Dict[str, Any]] = None,
        measures: Optional[List[str]] = None,
    ) -> BumpGreeksResult:
        """
        Compute Greeks via bump-and-reprice.

        Args:
            instrument:    Instrument to price
            market_env:    Base market environment
            model_type:    Model type
            engine_type:   Engine type
            engine_params: Engine parameters
            measures:      List of Greeks to compute.
                           Default: ["delta", "gamma", "vega", "theta", "rho"]

        Returns:
            BumpGreeksResult with all requested Greeks
        """
        if self.pricing_service is None:
            from services.pricers.pricing_service import PricingService
            self.pricing_service = PricingService()

        if measures is None:
            measures = ["delta", "gamma", "vega", "theta", "rho"]

        underlying = getattr(instrument, "underlying", None) or ""
        engine_params = engine_params or {}

        # Detect if this is a rates instrument (no underlying / no spot)
        is_rates = not underlying or underlying.strip() == ""

        # Base price
        base_npv = self._price(instrument, market_env, model_type, engine_type, engine_params)

        result = BumpGreeksResult(base_npv=base_npv)

        # --- Equity Greeks (only for instruments with an underlying) ---

        # Delta: dV/dS via central difference
        if "delta" in measures and not is_rates:
            delta, details = self._first_order_greek(
                instrument, market_env, model_type, engine_type, engine_params,
                bumper=lambda env, h: _bump_spot(env, underlying, h),
                bump_size=self.spot_bump,
                base_npv=base_npv,
            )
            result.greeks["delta"] = delta
            result.bump_details["delta"] = details

        # Gamma: d2V/dS2 via second order
        if "gamma" in measures and not is_rates:
            gamma, details = self._second_order_greek(
                instrument, market_env, model_type, engine_type, engine_params,
                bumper=lambda env, h: _bump_spot(env, underlying, h),
                bump_size=self.spot_bump,
                base_npv=base_npv,
            )
            result.greeks["gamma"] = gamma
            result.bump_details["gamma"] = details

        # Vega: dV/dvol (per 1% vol move)
        if "vega" in measures and not is_rates:
            vega, details = self._first_order_greek(
                instrument, market_env, model_type, engine_type, engine_params,
                bumper=lambda env, h: _bump_vol(env, underlying, h),
                bump_size=self.vol_bump,
                base_npv=base_npv,
            )
            result.greeks["vega"] = vega
            result.bump_details["vega"] = details

        # Rho: dV/dr (per 1bp rate move, scaled to per 1%)
        if "rho" in measures:
            rho_raw, details = self._first_order_greek(
                instrument, market_env, model_type, engine_type, engine_params,
                bumper=lambda env, h: _bump_rate(env, h),
                bump_size=self.rate_bump,
                base_npv=base_npv,
            )
            result.greeks["rho"] = rho_raw * 100 if rho_raw is not None else None
            result.bump_details["rho"] = details

        # Theta: -(V(t+1d) - V(t)) / days
        if "theta" in measures:
            theta = self._compute_theta(
                instrument, market_env, model_type, engine_type, engine_params,
                base_npv=base_npv,
            )
            result.greeks["theta"] = theta

        # Dividend sensitivity
        if "div_sensitivity" in measures and not is_rates:
            div_sens, details = self._first_order_greek(
                instrument, market_env, model_type, engine_type, engine_params,
                bumper=lambda env, h: _bump_div(env, underlying, h),
                bump_size=self.div_bump,
                base_npv=base_npv,
            )
            result.greeks["div_sensitivity"] = div_sens
            result.bump_details["div_sensitivity"] = details

        # --- Rates-specific measures ---

        # DV01: value change for 1bp parallel rate shift
        if "dv01" in measures or is_rates:
            dv01_raw, details = self._first_order_greek(
                instrument, market_env, model_type, engine_type, engine_params,
                bumper=lambda env, h: _bump_rate(env, h),
                bump_size=0.0001,
                base_npv=base_npv,
            )
            # DV01 = |dV for +1bp| (positive convention)
            result.greeks["dv01"] = abs(dv01_raw * 0.0001) if dv01_raw is not None else None
            result.bump_details["dv01"] = details

        # Modified Duration: -(1/V) * dV/dr
        if "duration" in measures or is_rates:
            dur_raw, details = self._first_order_greek(
                instrument, market_env, model_type, engine_type, engine_params,
                bumper=lambda env, h: _bump_rate(env, h),
                bump_size=0.0001,
                base_npv=base_npv,
            )
            if dur_raw is not None and abs(base_npv) > 1e-10:
                result.greeks["duration"] = abs(dur_raw / base_npv)
            else:
                result.greeks["duration"] = None
            result.bump_details["duration"] = details

        # Convexity: (1/V) * d2V/dr2
        if "convexity" in measures or is_rates:
            conv_raw, details = self._second_order_greek(
                instrument, market_env, model_type, engine_type, engine_params,
                bumper=lambda env, h: _bump_rate(env, h),
                bump_size=0.0001,
                base_npv=base_npv,
            )
            if conv_raw is not None and abs(base_npv) > 1e-10:
                result.greeks["convexity"] = conv_raw / base_npv
            else:
                result.greeks["convexity"] = None
            result.bump_details["convexity"] = details

        return result


    # -------------------------------------------------------------------
    # Core methods
    # -------------------------------------------------------------------

    def _price(self, instrument, market_env, model_type, engine_type, engine_params) -> float:
        """Price and return NPV."""
        r = self.pricing_service.price(
            instrument, market_env, model_type, engine_type, engine_params
        )
        return r.npv

    def _first_order_greek(
        self, instrument, market_env, model_type, engine_type, engine_params,
        bumper, bump_size, base_npv,
    ) -> tuple:
        """
        Central difference: (V(x+h) - V(x-h)) / (2h)
        """
        try:
            env_up = bumper(market_env, bump_size)
            env_down = bumper(market_env, -bump_size)

            npv_up = self._price(instrument, env_up, model_type, engine_type, engine_params)
            npv_down = self._price(instrument, env_down, model_type, engine_type, engine_params)

            greek = (npv_up - npv_down) / (2 * bump_size)

            details = {
                "npv_up": npv_up,
                "npv_down": npv_down,
                "bump_size": bump_size,
                "method": "central_difference",
            }
            return greek, details

        except Exception as e:
            logger.warning(f"First-order bump failed: {e}")
            return None, {"error": str(e)}

    def _second_order_greek(
        self, instrument, market_env, model_type, engine_type, engine_params,
        bumper, bump_size, base_npv,
    ) -> tuple:
        """
        Second order: (V(x+h) - 2V(x) + V(x-h)) / h²
        """
        try:
            env_up = bumper(market_env, bump_size)
            env_down = bumper(market_env, -bump_size)

            npv_up = self._price(instrument, env_up, model_type, engine_type, engine_params)
            npv_down = self._price(instrument, env_down, model_type, engine_type, engine_params)

            greek = (npv_up - 2 * base_npv + npv_down) / (bump_size ** 2)

            details = {
                "npv_up": npv_up,
                "npv_base": base_npv,
                "npv_down": npv_down,
                "bump_size": bump_size,
                "method": "central_second_order",
            }
            return greek, details

        except Exception as e:
            logger.warning(f"Second-order bump failed: {e}")
            return None, {"error": str(e)}

    def _compute_theta(
        self, instrument, market_env, model_type, engine_type, engine_params,
        base_npv,
    ) -> Optional[float]:
        """
        Theta: -(V(t + dt) - V(t)) / dt

        Rolls pricing date forward by theta_days days.
        """
        try:
            env_fwd = _bump_time(market_env, self.theta_days)
            npv_fwd = self._price(instrument, env_fwd, model_type, engine_type, engine_params)

            # Theta per day (negative = time decay)
            theta = -(npv_fwd - base_npv) / self.theta_days
            return theta

        except Exception as e:
            logger.warning(f"Theta computation failed: {e}")
            return None
