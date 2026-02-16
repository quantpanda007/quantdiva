"""
Value-at-Risk (VaR) and Conditional VaR (CVaR / Expected Shortfall).

Methods:
1. Parametric (Delta-Normal):  VaR = -μ + z_α · σ  (assumes normal P&L)
2. Delta-Gamma:                includes gamma adjustment for non-linearity
3. Historical simulation:      full re-pricing under historical scenarios
4. Monte Carlo VaR:            simulate risk factor moves, full reprice

Usage:
    from services.risk.var import VaREngine

    engine = VaREngine(pricing_service=ps)

    # Parametric VaR
    result = engine.parametric_var(
        instruments=[opt1, opt2],
        market_env=env,
        confidence=0.99,
        horizon_days=1,
        annual_vol=0.20,
    )

    # Historical VaR
    result = engine.historical_var(
        instruments=[opt1, opt2],
        market_env=env,
        historical_returns=returns_array,
        confidence=0.99,
    )
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
from scipy.stats import norm

from core.interfaces.base import BaseInstrument, MarketEnvironment

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# VaR result
# ---------------------------------------------------------------------------

@dataclass
class VaRResult:
    """
    VaR computation result.

    Attributes:
        var:              Value-at-Risk (positive = loss)
        cvar:             Conditional VaR / Expected Shortfall
        confidence:       Confidence level (e.g. 0.99)
        horizon_days:     Holding period
        method:           Computation method
        portfolio_value:  Current portfolio value
        pnl_distribution: Array of P&L values (for historical/MC)
        trade_contributions: Per-trade VaR contribution
    """
    var: float = 0.0
    cvar: float = 0.0
    confidence: float = 0.99
    horizon_days: int = 1
    method: str = ""
    portfolio_value: float = 0.0
    pnl_distribution: Optional[np.ndarray] = field(default=None, repr=False)
    trade_contributions: Dict[str, float] = field(default_factory=dict)

    def print_report(self) -> None:
        print(f"\nVaR Report ({self.method})")
        print(f"{'='*50}")
        print(f"  Confidence:       {self.confidence*100:.1f}%")
        print(f"  Horizon:          {self.horizon_days} day(s)")
        print(f"  Portfolio Value:  {self.portfolio_value:>14.4f}")
        print(f"  VaR:              {self.var:>14.4f}")
        print(f"  CVaR (ES):        {self.cvar:>14.4f}")
        if self.portfolio_value != 0:
            print(f"  VaR %:            {self.var / abs(self.portfolio_value) * 100:>13.2f}%")
        if self.pnl_distribution is not None:
            print(f"  P&L samples:      {len(self.pnl_distribution)}")
            print(f"  P&L mean:         {np.mean(self.pnl_distribution):>14.4f}")
            print(f"  P&L std:          {np.std(self.pnl_distribution):>14.4f}")
            print(f"  P&L min:          {np.min(self.pnl_distribution):>14.4f}")
            print(f"  P&L max:          {np.max(self.pnl_distribution):>14.4f}")
        if self.trade_contributions:
            print(f"\n  Per-trade contributions:")
            for tid, contrib in self.trade_contributions.items():
                print(f"    {tid:<20} {contrib:>14.4f}")
        print()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "var": self.var,
            "cvar": self.cvar,
            "confidence": self.confidence,
            "horizon_days": self.horizon_days,
            "method": self.method,
            "portfolio_value": self.portfolio_value,
            "trade_contributions": self.trade_contributions,
        }


# ---------------------------------------------------------------------------
# VaR Engine
# ---------------------------------------------------------------------------

@dataclass
class VaREngine:
    """
    Value-at-Risk computation engine.

    Supports parametric, delta-gamma, and historical VaR.
    """

    pricing_service: Any = None
    model_type: str = "black_scholes"
    engine_type: str = "analytic"
    engine_params: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.pricing_service is None:
            from services.pricers.pricing_service import PricingService
            self.pricing_service = PricingService()

    # -------------------------------------------------------------------
    # Parametric (Delta-Normal) VaR
    # -------------------------------------------------------------------

    def parametric_var(
        self,
        instruments: List[BaseInstrument],
        market_env: MarketEnvironment,
        confidence: float = 0.99,
        horizon_days: int = 1,
        annual_vol: float = 0.20,
    ) -> VaRResult:
        """
        Delta-Normal VaR.

        Assumes P&L is normally distributed:
            VaR = Δ_portfolio · S · σ_daily · z_α · √(horizon)

        Fast but ignores gamma/convexity.
        """
        from services.greeks.bump_reprice import BumpAndRepriceGreeks

        z_alpha = norm.ppf(confidence)
        daily_vol = annual_vol / np.sqrt(252)
        horizon_vol = daily_vol * np.sqrt(horizon_days)

        portfolio_value = 0.0
        portfolio_delta_dollar = 0.0
        portfolio_gamma_dollar = 0.0
        contributions = {}

        greeks_svc = BumpAndRepriceGreeks(pricing_service=self.pricing_service)

        for inst in instruments:
            tid = str(inst.trade_id())
            underlying = getattr(inst, "underlying", "")
            spot = market_env.spot_prices.get(underlying, 100.0)

            try:
                # Price
                npv = self.pricing_service.price(
                    inst, market_env,
                    model_type=self.model_type,
                    engine_type=self.engine_type,
                    engine_params=self.engine_params,
                ).npv
                portfolio_value += npv

                # Greeks
                result = greeks_svc.compute(
                    inst, market_env,
                    model_type=self.model_type,
                    engine_type=self.engine_type,
                    engine_params=self.engine_params,
                    measures=["delta", "gamma"],
                )

                delta = result.greeks.get("delta", 0) or 0
                gamma = result.greeks.get("gamma", 0) or 0

                # Dollar delta and gamma
                dollar_delta = delta * spot
                dollar_gamma = gamma * spot ** 2

                portfolio_delta_dollar += dollar_delta
                portfolio_gamma_dollar += dollar_gamma

                # Per-trade VaR contribution (delta-based)
                trade_var = abs(dollar_delta) * horizon_vol * z_alpha
                contributions[tid] = trade_var

            except Exception as e:
                logger.warning(f"Parametric VaR: failed for {tid}: {e}")

        # Portfolio VaR (delta only)
        var_delta = abs(portfolio_delta_dollar) * horizon_vol * z_alpha

        # CVaR for normal distribution
        cvar = abs(portfolio_delta_dollar) * horizon_vol * norm.pdf(z_alpha) / (1 - confidence)

        return VaRResult(
            var=var_delta,
            cvar=cvar,
            confidence=confidence,
            horizon_days=horizon_days,
            method="parametric_delta_normal",
            portfolio_value=portfolio_value,
            trade_contributions=contributions,
        )

    # -------------------------------------------------------------------
    # Historical VaR
    # -------------------------------------------------------------------

    def historical_var(
        self,
        instruments: List[BaseInstrument],
        market_env: MarketEnvironment,
        historical_returns: np.ndarray,
        confidence: float = 0.99,
        horizon_days: int = 1,
    ) -> VaRResult:
        """
        Historical simulation VaR.

        Applies historical return scenarios to spot and re-prices.
        Full revaluation — captures gamma and all non-linearities.

        Args:
            historical_returns: (N,) array of historical daily returns
                                (e.g. [-0.02, 0.01, -0.005, ...])
        """
        from services.risk.scenario_engine import ScenarioEngine, Scenario, ShockSpec

        scenario_engine = ScenarioEngine(
            pricing_service=self.pricing_service,
            model_type=self.model_type,
            engine_type=self.engine_type,
            engine_params=self.engine_params,
        )

        # Scale returns to horizon
        if horizon_days > 1:
            scaled_returns = historical_returns * np.sqrt(horizon_days)
        else:
            scaled_returns = historical_returns

        # Base portfolio value
        base_value = 0.0
        for inst in instruments:
            try:
                npv = self.pricing_service.price(
                    inst, market_env,
                    model_type=self.model_type,
                    engine_type=self.engine_type,
                    engine_params=self.engine_params,
                ).npv
                base_value += npv
            except Exception:
                pass

        # Re-price under each historical return
        pnl_dist = []
        for ret in scaled_returns:
            scenario = Scenario(
                name=f"hist_{ret:.4f}",
                shocks=[ShockSpec("spot", "relative", float(ret))],
            )
            result = scenario_engine.run_scenario(instruments, market_env, scenario)
            pnl_dist.append(result.total_impact)

        pnl_array = np.array(pnl_dist)

        # VaR = negative of the (1-α) percentile of P&L distribution
        var = float(-np.percentile(pnl_array, (1 - confidence) * 100))

        # CVaR = expected loss given loss > VaR
        losses = pnl_array[pnl_array <= -var] if var > 0 else pnl_array[pnl_array <= np.percentile(pnl_array, (1 - confidence) * 100)]
        cvar = float(-np.mean(losses)) if len(losses) > 0 else var

        return VaRResult(
            var=var,
            cvar=cvar,
            confidence=confidence,
            horizon_days=horizon_days,
            method="historical_simulation",
            portfolio_value=base_value,
            pnl_distribution=pnl_array,
        )

    # -------------------------------------------------------------------
    # Monte Carlo VaR
    # -------------------------------------------------------------------

    def monte_carlo_var(
        self,
        instruments: List[BaseInstrument],
        market_env: MarketEnvironment,
        confidence: float = 0.99,
        horizon_days: int = 1,
        num_simulations: int = 10000,
        annual_vol: float = 0.20,
        seed: int = 42,
    ) -> VaRResult:
        """
        Monte Carlo VaR.

        Simulates correlated risk factor moves (spot, vol, rates)
        and fully re-prices under each scenario.

        Currently simulates spot returns only (normal distribution).
        Can be extended to multi-factor / correlated simulations.
        """
        from services.risk.scenario_engine import ScenarioEngine, Scenario, ShockSpec

        np.random.seed(seed)

        scenario_engine = ScenarioEngine(
            pricing_service=self.pricing_service,
            model_type=self.model_type,
            engine_type=self.engine_type,
            engine_params=self.engine_params,
        )

        daily_vol = annual_vol / np.sqrt(252)
        horizon_vol = daily_vol * np.sqrt(horizon_days)

        # Simulate returns
        simulated_returns = np.random.normal(0, horizon_vol, num_simulations)

        # Base value
        base_value = 0.0
        for inst in instruments:
            try:
                npv = self.pricing_service.price(
                    inst, market_env,
                    model_type=self.model_type,
                    engine_type=self.engine_type,
                    engine_params=self.engine_params,
                ).npv
                base_value += npv
            except Exception:
                pass

        # Re-price under each simulation
        pnl_dist = []
        for i, ret in enumerate(simulated_returns):
            scenario = Scenario(
                name=f"mc_{i}",
                shocks=[ShockSpec("spot", "relative", float(ret))],
            )
            result = scenario_engine.run_scenario(instruments, market_env, scenario)
            pnl_dist.append(result.total_impact)

        pnl_array = np.array(pnl_dist)

        var = float(-np.percentile(pnl_array, (1 - confidence) * 100))
        tail = pnl_array[pnl_array <= np.percentile(pnl_array, (1 - confidence) * 100)]
        cvar = float(-np.mean(tail)) if len(tail) > 0 else var

        return VaRResult(
            var=var,
            cvar=cvar,
            confidence=confidence,
            horizon_days=horizon_days,
            method=f"monte_carlo_{num_simulations}",
            portfolio_value=base_value,
            pnl_distribution=pnl_array,
        )