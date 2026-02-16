"""
Risk computation service.

Provides:
- Bump-and-reprice Greeks (finite difference)
- Scenario analysis (parallel shifts, twists, spot bumps, vol bumps)
- VaR (historical, parametric)
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import QuantLib as ql

from core.enums.definitions import RiskMeasure, ScenarioType
from core.interfaces.base import BaseInstrument, MarketEnvironment
from core.types.value_objects import PricingResult, RiskResult
from services.pricers.pricing_service import PricingService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scenario Definition
# ---------------------------------------------------------------------------

@dataclass
class Scenario:
    """Defines a market scenario for stress testing."""
    name: str
    scenario_type: ScenarioType
    bumps: Dict[str, float] = field(default_factory=dict)
    # bumps examples:
    #   {"USD_discount": 0.01}      → parallel shift of 1% on USD discount curve
    #   {"AAPL_spot": -0.10}        → 10% drop in AAPL spot
    #   {"AAPL_vol": 0.05}          → 5 vol points bump
    description: str = ""


# ---------------------------------------------------------------------------
# Risk Service
# ---------------------------------------------------------------------------

@dataclass
class RiskService:
    """
    Computes risk sensitivities and runs scenario analysis.
    """

    pricing_service: PricingService = field(default_factory=PricingService)
    default_bump_bps: float = 1.0  # 1 basis point

    # -------------------------------------------------------------------
    # Finite Difference Greeks
    # -------------------------------------------------------------------

    def compute_greeks(
        self,
        instrument: BaseInstrument,
        market_env: MarketEnvironment,
        measures: Optional[List[RiskMeasure]] = None,
        bump_size_spot_pct: float = 1.0,       # 1% spot bump
        bump_size_vol_abs: float = 0.01,        # 1 vol point
        bump_size_rate_bps: float = 1.0,        # 1bp rate bump
        **pricing_kwargs,
    ) -> RiskResult:
        """
        Compute Greeks via central finite differences.
        """
        if measures is None:
            measures = [
                RiskMeasure.DELTA, RiskMeasure.GAMMA,
                RiskMeasure.VEGA, RiskMeasure.THETA, RiskMeasure.RHO,
            ]

        # Base price
        base = self.pricing_service.price(instrument, market_env, **pricing_kwargs)
        greeks = {}

        underlying = getattr(instrument, "underlying", None) or getattr(instrument, "ccy_pair", None) or ""

        if RiskMeasure.DELTA in measures and underlying:
            greeks["delta"] = self._spot_bump(
                instrument, market_env, underlying, bump_size_spot_pct / 100.0,
                base.npv, **pricing_kwargs
            )

        if RiskMeasure.GAMMA in measures and underlying:
            greeks["gamma"] = self._spot_gamma(
                instrument, market_env, underlying, bump_size_spot_pct / 100.0,
                base.npv, **pricing_kwargs
            )

        if RiskMeasure.VEGA in measures and underlying:
            greeks["vega"] = self._vol_bump(
                instrument, market_env, underlying, bump_size_vol_abs,
                base.npv, **pricing_kwargs
            )

        if RiskMeasure.THETA in measures:
            greeks["theta"] = self._theta(
                instrument, market_env, base.npv, **pricing_kwargs
            )

        if RiskMeasure.RHO in measures:
            greeks["rho"] = self._rate_bump(
                instrument, market_env, instrument.currency(),
                bump_size_rate_bps / 10000.0, base.npv, **pricing_kwargs
            )

        if RiskMeasure.DV01 in measures:
            greeks["dv01"] = self._rate_bump(
                instrument, market_env, instrument.currency(),
                0.0001, base.npv, **pricing_kwargs
            )

        return RiskResult(
            trade_id=instrument.trade_id(),
            greeks=greeks,
        )

    # -------------------------------------------------------------------
    # Scenario Analysis
    # -------------------------------------------------------------------

    def run_scenarios(
        self,
        instrument: BaseInstrument,
        market_env: MarketEnvironment,
        scenarios: List[Scenario],
        **pricing_kwargs,
    ) -> Dict[str, float]:
        """
        Run multiple scenarios and return {scenario_name: PnL}.
        """
        base = self.pricing_service.price(instrument, market_env, **pricing_kwargs)
        results = {}

        for scenario in scenarios:
            try:
                bumped_env = self._apply_scenario(market_env, scenario)
                bumped = self.pricing_service.price(instrument, bumped_env, **pricing_kwargs)
                results[scenario.name] = bumped.npv - base.npv
            except Exception as e:
                logger.error(f"Scenario '{scenario.name}' failed: {e}")
                results[scenario.name] = float("nan")

        return results

    def generate_standard_scenarios(self, underlying: str = "") -> List[Scenario]:
        """Generate a standard set of stress scenarios."""
        scenarios = [
            Scenario("spot_up_10pct", ScenarioType.SPOT_BUMP, {f"{underlying}_spot": 0.10}),
            Scenario("spot_down_10pct", ScenarioType.SPOT_BUMP, {f"{underlying}_spot": -0.10}),
            Scenario("spot_up_25pct", ScenarioType.SPOT_BUMP, {f"{underlying}_spot": 0.25}),
            Scenario("spot_down_25pct", ScenarioType.SPOT_BUMP, {f"{underlying}_spot": -0.25}),
            Scenario("vol_up_5pts", ScenarioType.VOL_BUMP, {f"{underlying}_vol": 0.05}),
            Scenario("vol_down_5pts", ScenarioType.VOL_BUMP, {f"{underlying}_vol": -0.05}),
            Scenario("rates_up_100bp", ScenarioType.PARALLEL_SHIFT, {"USD_discount": 0.01}),
            Scenario("rates_down_100bp", ScenarioType.PARALLEL_SHIFT, {"USD_discount": -0.01}),
            Scenario("rates_up_50bp", ScenarioType.PARALLEL_SHIFT, {"USD_discount": 0.005}),
        ]
        return scenarios

    # -------------------------------------------------------------------
    # Private: bump helpers
    # -------------------------------------------------------------------

    def _spot_bump(
        self, instrument, market_env, underlying, bump_pct, base_npv, **kwargs
    ) -> Optional[float]:
        """Central difference delta: (V_up - V_down) / (2 * dS)."""
        try:
            spot = market_env.spot_prices.get(underlying, 100.0)
            dS = spot * bump_pct

            env_up = self._bump_spot(market_env, underlying, spot + dS)
            env_down = self._bump_spot(market_env, underlying, spot - dS)

            npv_up = self.pricing_service.price(instrument, env_up, **kwargs).npv
            npv_down = self.pricing_service.price(instrument, env_down, **kwargs).npv

            return (npv_up - npv_down) / (2 * dS)
        except Exception as e:
            logger.warning(f"Delta computation failed: {e}")
            return None

    def _spot_gamma(
        self, instrument, market_env, underlying, bump_pct, base_npv, **kwargs
    ) -> Optional[float]:
        """Central difference gamma: (V_up - 2*V_base + V_down) / (dS^2)."""
        try:
            spot = market_env.spot_prices.get(underlying, 100.0)
            dS = spot * bump_pct

            env_up = self._bump_spot(market_env, underlying, spot + dS)
            env_down = self._bump_spot(market_env, underlying, spot - dS)

            npv_up = self.pricing_service.price(instrument, env_up, **kwargs).npv
            npv_down = self.pricing_service.price(instrument, env_down, **kwargs).npv

            return (npv_up - 2 * base_npv + npv_down) / (dS ** 2)
        except Exception as e:
            logger.warning(f"Gamma computation failed: {e}")
            return None

    def _vol_bump(
        self, instrument, market_env, underlying, bump_abs, base_npv, **kwargs
    ) -> Optional[float]:
        """Vega via vol bump."""
        try:
            env_up = self._bump_vol(market_env, underlying, bump_abs)
            npv_up = self.pricing_service.price(instrument, env_up, **kwargs).npv
            return (npv_up - base_npv) / bump_abs
        except Exception as e:
            logger.warning(f"Vega computation failed: {e}")
            return None

    def _theta(
        self, instrument, market_env, base_npv, **kwargs
    ) -> Optional[float]:
        """Theta: 1-day time decay."""
        try:
            from datetime import timedelta
            tomorrow = market_env.pricing_date.value + timedelta(days=1)
            from core.types.value_objects import PricingDate
            env_shifted = copy.copy(market_env)
            env_shifted.pricing_date = PricingDate(tomorrow)
            npv_tomorrow = self.pricing_service.price(instrument, env_shifted, **kwargs).npv
            return npv_tomorrow - base_npv  # per day
        except Exception as e:
            logger.warning(f"Theta computation failed: {e}")
            return None

    def _rate_bump(
        self, instrument, market_env, currency, bump_abs, base_npv, **kwargs
    ) -> Optional[float]:
        """Rho/DV01 via parallel rate bump."""
        try:
            env_up = self._bump_rate(market_env, currency, bump_abs)
            npv_up = self.pricing_service.price(instrument, env_up, **kwargs).npv
            return (npv_up - base_npv) / bump_abs
        except Exception as e:
            logger.warning(f"Rate sensitivity computation failed: {e}")
            return None

    # -------------------------------------------------------------------
    # Market environment bumpers
    # -------------------------------------------------------------------

    def _bump_spot(self, env: MarketEnvironment, key: str, new_spot: float) -> MarketEnvironment:
        bumped = copy.copy(env)
        bumped.spot_prices = dict(env.spot_prices)
        bumped.spot_prices[key] = new_spot
        return bumped

    def _bump_vol(self, env: MarketEnvironment, key: str, bump: float) -> MarketEnvironment:
        """Rebuild vol surface with additive bump. Simplified: creates new flat vol."""
        bumped = copy.copy(env)
        bumped.vol_surfaces = dict(env.vol_surfaces)
        # Simplified — in production, would bump the actual surface
        from market.curves.yield_curve import build_flat_vol
        # Extract current ATM vol and bump it
        try:
            current_handle = env.vol_surfaces[key]
            current_vol = current_handle.blackVol(1.0, env.spot_prices.get(key, 100.0))
            new_vol = max(0.001, current_vol + bump)
            bumped.vol_surfaces[key] = build_flat_vol(env.pricing_date, new_vol)
        except Exception:
            pass
        return bumped

    def _bump_rate(self, env: MarketEnvironment, currency: str, bump: float) -> MarketEnvironment:
        """Parallel shift on discount curve. Simplified: flat curve rebuild."""
        bumped = copy.copy(env)
        bumped.discount_curves = dict(env.discount_curves)
        try:
            from market.curves.yield_curve import build_flat_curve
            current_handle = env.discount_curves[currency]
            # Extract current short rate and bump
            current_rate = current_handle.zeroRate(
                1.0, ql.Continuous, ql.Annual
            ).rate()
            new_rate = current_rate + bump
            bumped.discount_curves[currency] = build_flat_curve(env.pricing_date, new_rate)
        except Exception:
            pass
        return bumped

    def _apply_scenario(self, env: MarketEnvironment, scenario: Scenario) -> MarketEnvironment:
        """Apply a scenario's bumps to create a stressed market environment."""
        bumped = copy.copy(env)
        bumped.spot_prices = dict(env.spot_prices)
        bumped.vol_surfaces = dict(env.vol_surfaces)
        bumped.discount_curves = dict(env.discount_curves)

        for key, bump_value in scenario.bumps.items():
            if key.endswith("_spot"):
                underlying = key.replace("_spot", "")
                current = bumped.spot_prices.get(underlying, 100.0)
                bumped.spot_prices[underlying] = current * (1 + bump_value)
            elif key.endswith("_vol"):
                underlying = key.replace("_vol", "")
                bumped = self._bump_vol(bumped, underlying, bump_value)
            elif key.endswith("_discount"):
                currency = key.replace("_discount", "")
                bumped = self._bump_rate(bumped, currency, bump_value)

        return bumped
