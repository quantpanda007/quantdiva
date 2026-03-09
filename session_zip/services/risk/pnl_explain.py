"""
P&L Explain — decompose portfolio P&L into risk factor contributions.

Uses Taylor expansion to attribute P&L to Greeks:

    ΔV ≈ Δ·ΔS + ½Γ·ΔS² + ν·Δσ + θ·Δt + ρ·Δr + unexplained

This is the standard "Greek P&L explain" used on every trading desk.

Supports:
- Single trade P&L explain
- Portfolio-level aggregation
- Cross-term (vanna, volga) if higher-order Greeks available
- Unexplained = actual - explained (should be small)

Usage:
    from services.risk.pnl_explain import PnLExplainService

    svc = PnLExplainService(pricing_service=ps)
    result = svc.explain(
        instrument=option,
        base_env=yesterday_env,
        current_env=today_env,
        model_type="black_scholes",
        engine_type="analytic",
    )
    result.print_report()
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import QuantLib as ql

from core.interfaces.base import BaseInstrument, MarketEnvironment

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# P&L explain result
# ---------------------------------------------------------------------------

@dataclass
class PnLExplainResult:
    """
    P&L explain for a single instrument.

    Attributes:
        trade_id:       Trade identifier
        base_npv:       Yesterday's NPV
        current_npv:    Today's NPV
        actual_pnl:     current - base
        delta_pnl:      Δ · ΔS
        gamma_pnl:      ½ · Γ · ΔS²
        vega_pnl:       ν · Δσ
        theta_pnl:      θ · Δt
        rho_pnl:        ρ · Δr
        explained_pnl:  sum of all components
        unexplained:    actual - explained
        greeks:         raw Greeks used
        market_moves:   risk factor changes
    """
    trade_id: str = ""
    base_npv: float = 0.0
    current_npv: float = 0.0
    actual_pnl: float = 0.0
    delta_pnl: float = 0.0
    gamma_pnl: float = 0.0
    vega_pnl: float = 0.0
    theta_pnl: float = 0.0
    rho_pnl: float = 0.0
    explained_pnl: float = 0.0
    unexplained: float = 0.0
    greeks: Dict[str, Optional[float]] = field(default_factory=dict)
    market_moves: Dict[str, float] = field(default_factory=dict)

    def print_report(self) -> None:
        print(f"\nP&L Explain: {self.trade_id}")
        print(f"{'='*50}")
        print(f"  Base NPV:      {self.base_npv:>14.6f}")
        print(f"  Current NPV:   {self.current_npv:>14.6f}")
        print(f"  Actual P&L:    {self.actual_pnl:>14.6f}")
        print(f"{'─'*50}")
        print(f"  Delta P&L:     {self.delta_pnl:>14.6f}  (Δ={self.greeks.get('delta', 0):.4f}, ΔS={self.market_moves.get('dS', 0):.4f})")
        print(f"  Gamma P&L:     {self.gamma_pnl:>14.6f}  (Γ={self.greeks.get('gamma', 0):.6f})")
        print(f"  Vega P&L:      {self.vega_pnl:>14.6f}  (ν={self.greeks.get('vega', 0):.4f}, Δσ={self.market_moves.get('dvol', 0):.4f})")
        print(f"  Theta P&L:     {self.theta_pnl:>14.6f}  (θ={self.greeks.get('theta', 0):.4f}, Δt={self.market_moves.get('dt', 0):.4f})")
        print(f"  Rho P&L:       {self.rho_pnl:>14.6f}  (ρ={self.greeks.get('rho', 0):.4f}, Δr={self.market_moves.get('dr', 0):.4f})")
        print(f"{'─'*50}")
        print(f"  Explained:     {self.explained_pnl:>14.6f}")
        print(f"  Unexplained:   {self.unexplained:>14.6f}")

        if abs(self.actual_pnl) > 1e-10:
            explain_pct = (self.explained_pnl / self.actual_pnl) * 100
            print(f"  Explain ratio: {explain_pct:>13.1f}%")
        print()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "base_npv": self.base_npv,
            "current_npv": self.current_npv,
            "actual_pnl": self.actual_pnl,
            "delta_pnl": self.delta_pnl,
            "gamma_pnl": self.gamma_pnl,
            "vega_pnl": self.vega_pnl,
            "theta_pnl": self.theta_pnl,
            "rho_pnl": self.rho_pnl,
            "explained_pnl": self.explained_pnl,
            "unexplained": self.unexplained,
        }


@dataclass
class PortfolioPnLExplain:
    """Aggregated P&L explain across a portfolio."""
    trade_explains: List[PnLExplainResult] = field(default_factory=list)

    @property
    def total_actual(self) -> float:
        return sum(e.actual_pnl for e in self.trade_explains)

    @property
    def total_delta_pnl(self) -> float:
        return sum(e.delta_pnl for e in self.trade_explains)

    @property
    def total_gamma_pnl(self) -> float:
        return sum(e.gamma_pnl for e in self.trade_explains)

    @property
    def total_vega_pnl(self) -> float:
        return sum(e.vega_pnl for e in self.trade_explains)

    @property
    def total_theta_pnl(self) -> float:
        return sum(e.theta_pnl for e in self.trade_explains)

    @property
    def total_rho_pnl(self) -> float:
        return sum(e.rho_pnl for e in self.trade_explains)

    @property
    def total_explained(self) -> float:
        return sum(e.explained_pnl for e in self.trade_explains)

    @property
    def total_unexplained(self) -> float:
        return sum(e.unexplained for e in self.trade_explains)

    def print_report(self) -> None:
        # Per-trade
        for e in self.trade_explains:
            e.print_report()

        # Portfolio summary
        print(f"{'='*60}")
        print(f"PORTFOLIO P&L EXPLAIN ({len(self.trade_explains)} trades)")
        print(f"{'='*60}")
        print(f"  Total Actual P&L:  {self.total_actual:>14.6f}")
        print(f"  Delta:             {self.total_delta_pnl:>14.6f}")
        print(f"  Gamma:             {self.total_gamma_pnl:>14.6f}")
        print(f"  Vega:              {self.total_vega_pnl:>14.6f}")
        print(f"  Theta:             {self.total_theta_pnl:>14.6f}")
        print(f"  Rho:               {self.total_rho_pnl:>14.6f}")
        print(f"  Explained:         {self.total_explained:>14.6f}")
        print(f"  Unexplained:       {self.total_unexplained:>14.6f}")
        if abs(self.total_actual) > 1e-10:
            print(f"  Explain ratio:     {self.total_explained / self.total_actual * 100:>13.1f}%")
        print()

    def to_dataframe(self):
        import pandas as pd
        return pd.DataFrame([e.to_dict() for e in self.trade_explains])


# ---------------------------------------------------------------------------
# Market move extraction
# ---------------------------------------------------------------------------

def extract_market_moves(
    base_env: MarketEnvironment,
    current_env: MarketEnvironment,
    underlying: str,
) -> Dict[str, float]:
    """Extract risk factor changes between two market environments."""
    moves = {}

    # Spot change
    s0 = base_env.spot_prices.get(underlying, 100.0)
    s1 = current_env.spot_prices.get(underlying, s0)
    moves["dS"] = s1 - s0
    moves["dS_pct"] = (s1 - s0) / s0 if s0 != 0 else 0

    # Vol change
    try:
        vol0 = base_env.vol_surfaces[underlying].blackVol(0.5, s0)
        vol1 = current_env.vol_surfaces[underlying].blackVol(0.5, s1)
        moves["dvol"] = vol1 - vol0
    except Exception:
        moves["dvol"] = 0.0

    # Rate change
    try:
        r0 = list(base_env.discount_curves.values())[0].zeroRate(
            1.0, ql.Continuous, ql.Annual
        ).rate()
        r1 = list(current_env.discount_curves.values())[0].zeroRate(
            1.0, ql.Continuous, ql.Annual
        ).rate()
        moves["dr"] = r1 - r0
    except Exception:
        moves["dr"] = 0.0

    # Time change (in years)
    d0 = base_env.pricing_date.value
    d1 = current_env.pricing_date.value
    moves["dt"] = (d1 - d0).days / 365.0

    return moves


# ---------------------------------------------------------------------------
# P&L Explain Service
# ---------------------------------------------------------------------------

@dataclass
class PnLExplainService:
    """
    Decomposes P&L into Greek components via Taylor expansion.

    Workflow:
    1. Compute Greeks at base market (bump-and-reprice or analytic)
    2. Extract market moves (ΔS, Δσ, Δr, Δt)
    3. Apply Taylor expansion
    4. Compare explained vs actual
    """

    pricing_service: Any = None
    model_type: str = "black_scholes"
    engine_type: str = "analytic"
    engine_params: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.pricing_service is None:
            from services.pricers.pricing_service import PricingService
            self.pricing_service = PricingService()

    def explain(
        self,
        instrument: BaseInstrument,
        base_env: MarketEnvironment,
        current_env: MarketEnvironment,
    ) -> PnLExplainResult:
        """P&L explain for a single instrument."""
        trade_id = str(instrument.trade_id())
        underlying = getattr(instrument, "underlying", "")

        # 1. Base and current NPV
        base_npv = self._price(instrument, base_env)
        current_npv = self._price(instrument, current_env)
        actual_pnl = current_npv - base_npv

        # 2. Greeks at base market
        greeks = self._compute_greeks(instrument, base_env)

        # 3. Market moves
        moves = extract_market_moves(base_env, current_env, underlying)

        # 4. Taylor expansion
        delta = greeks.get("delta", 0) or 0
        gamma = greeks.get("gamma", 0) or 0
        vega = greeks.get("vega", 0) or 0
        theta = greeks.get("theta", 0) or 0
        rho = greeks.get("rho", 0) or 0

        dS = moves["dS"]
        dvol = moves["dvol"]
        dt = moves["dt"]
        dr = moves["dr"]

        delta_pnl = delta * dS
        gamma_pnl = 0.5 * gamma * dS ** 2
        vega_pnl = vega * dvol  # QuantLib vega is dV/dσ, σ in decimal; dvol in decimal
        theta_pnl = theta * dt * 365  # theta is per day, dt is in years
        rho_pnl = rho * dr  # QuantLib rho is dV/dr, r in decimal; dr in decimal

        explained = delta_pnl + gamma_pnl + vega_pnl + theta_pnl + rho_pnl
        unexplained = actual_pnl - explained

        return PnLExplainResult(
            trade_id=trade_id,
            base_npv=base_npv,
            current_npv=current_npv,
            actual_pnl=actual_pnl,
            delta_pnl=delta_pnl,
            gamma_pnl=gamma_pnl,
            vega_pnl=vega_pnl,
            theta_pnl=theta_pnl,
            rho_pnl=rho_pnl,
            explained_pnl=explained,
            unexplained=unexplained,
            greeks=greeks,
            market_moves=moves,
        )

    def explain_portfolio(
        self,
        instruments: List[BaseInstrument],
        base_env: MarketEnvironment,
        current_env: MarketEnvironment,
    ) -> PortfolioPnLExplain:
        """P&L explain for a portfolio of instruments."""
        result = PortfolioPnLExplain()
        for inst in instruments:
            try:
                explain = self.explain(inst, base_env, current_env)
                result.trade_explains.append(explain)
            except Exception as e:
                logger.warning(f"P&L explain failed for {inst.trade_id()}: {e}")
        return result

    def _price(self, instrument: BaseInstrument, market_env: MarketEnvironment) -> float:
        r = self.pricing_service.price(
            instrument, market_env,
            model_type=self.model_type,
            engine_type=self.engine_type,
            engine_params=self.engine_params,
        )
        return r.npv

    def _compute_greeks(
        self, instrument: BaseInstrument, market_env: MarketEnvironment
    ) -> Dict[str, Optional[float]]:
        """Compute Greeks using bump-and-reprice."""
        from services.greeks.bump_reprice import BumpAndRepriceGreeks

        svc = BumpAndRepriceGreeks(pricing_service=self.pricing_service)
        result = svc.compute(
            instrument=instrument,
            market_env=market_env,
            model_type=self.model_type,
            engine_type=self.engine_type,
            engine_params=self.engine_params,
            measures=["delta", "gamma", "vega", "theta", "rho"],
        )
        return result.greeks