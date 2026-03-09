"""
Scenario Engine — stress testing and what-if analysis.

Applies predefined or custom shocks to market data and re-prices
a portfolio to measure P&L impact.

Scenario types:
    Parallel shift:  uniform bump across a risk factor
    Twist:           different bumps at short/long end
    Butterfly:       bump wings, unbump belly
    Vol bump:        shift vol surface uniformly or by strike/expiry
    Spot bump:       absolute or percentage spot move
    Custom:          arbitrary combination of shocks

Usage:
    from services.risk.scenario_engine import ScenarioEngine, Scenario, ShockSpec

    engine = ScenarioEngine(pricing_service=ps)

    # Single scenario
    result = engine.run_scenario(
        instruments=[opt1, opt2],
        market_env=env,
        scenario=Scenario(
            name="Spot -10%",
            shocks=[ShockSpec(risk_factor="spot", shock_type="relative", value=-0.10)],
        ),
    )

    # Scenario ladder
    results = engine.run_spot_ladder(
        instruments=[opt1],
        market_env=env,
        bumps=[-20, -10, -5, 0, 5, 10, 20],  # percentage bumps
    )

    # Full stress test
    results = engine.run_stress_test(
        instruments=portfolio,
        market_env=env,
        scenarios=predefined_scenarios,
    )
"""

from __future__ import annotations

import copy
import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Dict, List, Optional

import numpy as np
import QuantLib as ql

from core.interfaces.base import BaseInstrument, MarketEnvironment
from core.types.value_objects import PricingDate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shock specification
# ---------------------------------------------------------------------------

@dataclass
class ShockSpec:
    """
    Single shock to a risk factor.

    Attributes:
        risk_factor:  "spot", "vol", "rate", "div", "time"
        shock_type:   "absolute" or "relative" (percentage)
        value:        shock magnitude
        underlying:   which underlying to shock (None = all)
    """
    risk_factor: str
    shock_type: str = "absolute"  # "absolute" or "relative"
    value: float = 0.0
    underlying: Optional[str] = None


@dataclass
class Scenario:
    """Named collection of shocks."""
    name: str
    shocks: List[ShockSpec] = field(default_factory=list)
    description: str = ""


# ---------------------------------------------------------------------------
# Scenario result
# ---------------------------------------------------------------------------

@dataclass
class ScenarioResult:
    """Result of running a single scenario."""
    scenario_name: str
    base_pnl: Dict[str, float] = field(default_factory=dict)  # trade_id → base NPV
    shocked_pnl: Dict[str, float] = field(default_factory=dict)  # trade_id → shocked NPV
    pnl_impact: Dict[str, float] = field(default_factory=dict)  # trade_id → delta P&L
    total_base: float = 0.0
    total_shocked: float = 0.0
    total_impact: float = 0.0
    elapsed_seconds: float = 0.0

    def summary(self) -> Dict[str, Any]:
        return {
            "scenario": self.scenario_name,
            "total_base_pnl": round(self.total_base, 6),
            "total_shocked_pnl": round(self.total_shocked, 6),
            "total_impact": round(self.total_impact, 6),
            "num_trades": len(self.base_pnl),
            "elapsed_seconds": round(self.elapsed_seconds, 4),
        }


@dataclass
class StressTestResult:
    """Result of running multiple scenarios."""
    scenario_results: List[ScenarioResult] = field(default_factory=list)

    @property
    def worst_scenario(self) -> Optional[ScenarioResult]:
        if not self.scenario_results:
            return None
        return min(self.scenario_results, key=lambda r: r.total_impact)

    @property
    def best_scenario(self) -> Optional[ScenarioResult]:
        if not self.scenario_results:
            return None
        return max(self.scenario_results, key=lambda r: r.total_impact)

    def summary_table(self) -> List[Dict[str, Any]]:
        return [r.summary() for r in self.scenario_results]

    def print_summary(self) -> None:
        print(f"\n{'Scenario':<30} {'Base PnL':>14} {'Shocked PnL':>14} {'Impact':>14} {'Time(ms)':>10}")
        print("-" * 85)
        for r in self.scenario_results:
            print(
                f"{r.scenario_name:<30} "
                f"{r.total_base:>14.4f} "
                f"{r.total_shocked:>14.4f} "
                f"{r.total_impact:>14.4f} "
                f"{r.elapsed_seconds * 1000:>10.1f}"
            )
        if self.worst_scenario:
            print(f"\nWorst: {self.worst_scenario.scenario_name} ({self.worst_scenario.total_impact:+.4f})")
        if self.best_scenario:
            print(f"Best:  {self.best_scenario.scenario_name} ({self.best_scenario.total_impact:+.4f})")


# ---------------------------------------------------------------------------
# Market environment shocking
# ---------------------------------------------------------------------------

def apply_shocks(
    market_env: MarketEnvironment,
    shocks: List[ShockSpec],
) -> MarketEnvironment:
    """
    Apply a list of shocks to a market environment.

    Returns a new MarketEnvironment with shocked data.
    """
    env = copy.copy(market_env)
    env.spot_prices = dict(market_env.spot_prices)
    env.vol_surfaces = dict(market_env.vol_surfaces)
    env.discount_curves = dict(market_env.discount_curves)
    env.dividend_curves = dict(market_env.dividend_curves)

    for shock in shocks:
        if shock.risk_factor == "spot":
            _apply_spot_shock(env, shock)
        elif shock.risk_factor == "vol":
            _apply_vol_shock(env, shock)
        elif shock.risk_factor == "rate":
            _apply_rate_shock(env, shock)
        elif shock.risk_factor == "div":
            _apply_div_shock(env, shock)
        elif shock.risk_factor == "time":
            _apply_time_shock(env, shock)
        else:
            logger.warning(f"Unknown risk factor: {shock.risk_factor}")

    return env


def _apply_spot_shock(env: MarketEnvironment, shock: ShockSpec) -> None:
    underlyings = [shock.underlying] if shock.underlying else list(env.spot_prices.keys())
    for und in underlyings:
        if und in env.spot_prices:
            current = env.spot_prices[und]
            if shock.shock_type == "relative":
                env.spot_prices[und] = current * (1 + shock.value)
            else:
                env.spot_prices[und] = current + shock.value


def _apply_vol_shock(env: MarketEnvironment, shock: ShockSpec) -> None:
    underlyings = [shock.underlying] if shock.underlying else list(env.vol_surfaces.keys())
    ql_date = env.pricing_date.to_ql()

    for und in underlyings:
        if und in env.vol_surfaces:
            try:
                spot = env.spot_prices.get(und, 100.0)
                current_vol = env.vol_surfaces[und].blackVol(1.0, spot)
            except Exception:
                current_vol = 0.20

            if shock.shock_type == "relative":
                new_vol = current_vol * (1 + shock.value)
            else:
                new_vol = current_vol + shock.value

            new_vol = max(new_vol, 0.001)
            env.vol_surfaces[und] = ql.BlackVolTermStructureHandle(
                ql.BlackConstantVol(ql_date, ql.NullCalendar(), new_vol, ql.Actual365Fixed())
            )


def _apply_rate_shock(env: MarketEnvironment, shock: ShockSpec) -> None:
    ql_date = env.pricing_date.to_ql()

    for key in list(env.discount_curves.keys()):
        try:
            current_rate = env.discount_curves[key].zeroRate(
                1.0, ql.Continuous, ql.Annual
            ).rate()
        except Exception:
            current_rate = 0.05

        if shock.shock_type == "relative":
            new_rate = current_rate * (1 + shock.value)
        else:
            new_rate = current_rate + shock.value

        env.discount_curves[key] = ql.YieldTermStructureHandle(
            ql.FlatForward(ql_date, new_rate, ql.Actual365Fixed())
        )


def _apply_div_shock(env: MarketEnvironment, shock: ShockSpec) -> None:
    ql_date = env.pricing_date.to_ql()

    for key in list(env.dividend_curves.keys()):
        try:
            current_div = env.dividend_curves[key].zeroRate(
                1.0, ql.Continuous, ql.Annual
            ).rate()
        except Exception:
            current_div = 0.0

        if shock.shock_type == "relative":
            new_div = current_div * (1 + shock.value)
        else:
            new_div = current_div + shock.value

        new_div = max(new_div, 0.0)
        env.dividend_curves[key] = ql.YieldTermStructureHandle(
            ql.FlatForward(ql_date, new_div, ql.Actual365Fixed())
        )


def _apply_time_shock(env: MarketEnvironment, shock: ShockSpec) -> None:
    days = int(shock.value)
    new_date = env.pricing_date.value + timedelta(days=days)
    env.pricing_date = PricingDate(new_date)


# ---------------------------------------------------------------------------
# Predefined scenarios
# ---------------------------------------------------------------------------

PREDEFINED_SCENARIOS = {
    "spot_down_5pct": Scenario(
        name="Spot -5%",
        shocks=[ShockSpec("spot", "relative", -0.05)],
        description="5% spot decline across all underlyings",
    ),
    "spot_down_10pct": Scenario(
        name="Spot -10%",
        shocks=[ShockSpec("spot", "relative", -0.10)],
    ),
    "spot_down_20pct": Scenario(
        name="Spot -20%",
        shocks=[ShockSpec("spot", "relative", -0.20)],
        description="Crash scenario",
    ),
    "spot_up_10pct": Scenario(
        name="Spot +10%",
        shocks=[ShockSpec("spot", "relative", 0.10)],
    ),
    "vol_up_5pts": Scenario(
        name="Vol +5pts",
        shocks=[ShockSpec("vol", "absolute", 0.05)],
        description="Volatility spike of 500bps",
    ),
    "vol_up_10pts": Scenario(
        name="Vol +10pts",
        shocks=[ShockSpec("vol", "absolute", 0.10)],
    ),
    "vol_down_5pts": Scenario(
        name="Vol -5pts",
        shocks=[ShockSpec("vol", "absolute", -0.05)],
    ),
    "rate_up_100bp": Scenario(
        name="Rate +100bp",
        shocks=[ShockSpec("rate", "absolute", 0.01)],
    ),
    "rate_down_100bp": Scenario(
        name="Rate -100bp",
        shocks=[ShockSpec("rate", "absolute", -0.01)],
    ),
    "crash_scenario": Scenario(
        name="Crash: Spot -15%, Vol +10pts",
        shocks=[
            ShockSpec("spot", "relative", -0.15),
            ShockSpec("vol", "absolute", 0.10),
        ],
        description="Combined equity crash with vol spike",
    ),
    "rally_scenario": Scenario(
        name="Rally: Spot +10%, Vol -3pts",
        shocks=[
            ShockSpec("spot", "relative", 0.10),
            ShockSpec("vol", "absolute", -0.03),
        ],
        description="Combined equity rally with vol compression",
    ),
    "rates_shock": Scenario(
        name="Rates +200bp, Spot -5%",
        shocks=[
            ShockSpec("rate", "absolute", 0.02),
            ShockSpec("spot", "relative", -0.05),
        ],
    ),
}


# ---------------------------------------------------------------------------
# Scenario Engine
# ---------------------------------------------------------------------------

@dataclass
class ScenarioEngine:
    """
    Runs scenarios and stress tests on a portfolio.

    Prices instruments under base and shocked market data,
    computes P&L impact.
    """

    pricing_service: Any = None  # PricingService
    model_type: str = "black_scholes"
    engine_type: str = "analytic"
    engine_params: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.pricing_service is None:
            from services.pricers.pricing_service import PricingService
            self.pricing_service = PricingService()

    def run_scenario(
        self,
        instruments: List[BaseInstrument],
        market_env: MarketEnvironment,
        scenario: Scenario,
    ) -> ScenarioResult:
        """Run a single scenario on a list of instruments."""
        t0 = time.perf_counter()

        # Base prices
        base_pnl = {}
        for inst in instruments:
            try:
                r = self.pricing_service.price(
                    inst, market_env,
                    model_type=self.model_type,
                    engine_type=self.engine_type,
                    engine_params=self.engine_params,
                )
                base_pnl[str(inst.trade_id())] = r.npv
            except Exception as e:
                logger.warning(f"Base pricing failed for {inst.trade_id()}: {e}")
                base_pnl[str(inst.trade_id())] = 0.0

        # Shocked prices
        shocked_env = apply_shocks(market_env, scenario.shocks)
        shocked_pnl = {}
        for inst in instruments:
            try:
                r = self.pricing_service.price(
                    inst, shocked_env,
                    model_type=self.model_type,
                    engine_type=self.engine_type,
                    engine_params=self.engine_params,
                )
                shocked_pnl[str(inst.trade_id())] = r.npv
            except Exception as e:
                logger.warning(f"Shocked pricing failed for {inst.trade_id()}: {e}")
                shocked_pnl[str(inst.trade_id())] = base_pnl.get(str(inst.trade_id()), 0.0)

        # P&L impact
        pnl_impact = {}
        for tid in base_pnl:
            pnl_impact[tid] = shocked_pnl.get(tid, 0.0) - base_pnl[tid]

        elapsed = time.perf_counter() - t0

        return ScenarioResult(
            scenario_name=scenario.name,
            base_pnl=base_pnl,
            shocked_pnl=shocked_pnl,
            pnl_impact=pnl_impact,
            total_base=sum(base_pnl.values()),
            total_shocked=sum(shocked_pnl.values()),
            total_impact=sum(pnl_impact.values()),
            elapsed_seconds=elapsed,
        )

    def run_stress_test(
        self,
        instruments: List[BaseInstrument],
        market_env: MarketEnvironment,
        scenarios: Optional[List[Scenario]] = None,
    ) -> StressTestResult:
        """
        Run multiple scenarios (stress test).

        If scenarios is None, uses all predefined scenarios.
        """
        if scenarios is None:
            scenarios = list(PREDEFINED_SCENARIOS.values())

        results = StressTestResult()
        for scenario in scenarios:
            result = self.run_scenario(instruments, market_env, scenario)
            results.scenario_results.append(result)

        return results

    def run_spot_ladder(
        self,
        instruments: List[BaseInstrument],
        market_env: MarketEnvironment,
        bumps_pct: List[float] = None,
    ) -> StressTestResult:
        """
        Run spot ladder: price at multiple spot levels.

        bumps_pct: percentage bumps, e.g. [-20, -10, -5, 0, 5, 10, 20]
        """
        if bumps_pct is None:
            bumps_pct = [-20, -15, -10, -5, -2, 0, 2, 5, 10, 15, 20]

        scenarios = [
            Scenario(
                name=f"Spot {b:+.0f}%",
                shocks=[ShockSpec("spot", "relative", b / 100.0)],
            )
            for b in bumps_pct
        ]

        return self.run_stress_test(instruments, market_env, scenarios)

    def run_vol_ladder(
        self,
        instruments: List[BaseInstrument],
        market_env: MarketEnvironment,
        bumps_pts: List[float] = None,
    ) -> StressTestResult:
        """
        Run vol ladder: price at multiple vol levels.

        bumps_pts: absolute vol bumps, e.g. [-0.05, -0.02, 0, 0.02, 0.05, 0.10]
        """
        if bumps_pts is None:
            bumps_pts = [-0.10, -0.05, -0.02, 0.0, 0.02, 0.05, 0.10, 0.15]

        scenarios = [
            Scenario(
                name=f"Vol {b*100:+.0f}pts",
                shocks=[ShockSpec("vol", "absolute", b)],
            )
            for b in bumps_pts
        ]

        return self.run_stress_test(instruments, market_env, scenarios)

    def run_spot_vol_matrix(
        self,
        instruments: List[BaseInstrument],
        market_env: MarketEnvironment,
        spot_bumps_pct: List[float] = None,
        vol_bumps_pts: List[float] = None,
    ) -> StressTestResult:
        """
        Run 2D spot × vol matrix.

        Prices at each (spot_bump, vol_bump) combination.
        """
        if spot_bumps_pct is None:
            spot_bumps_pct = [-10, -5, 0, 5, 10]
        if vol_bumps_pts is None:
            vol_bumps_pts = [-0.05, 0.0, 0.05, 0.10]

        scenarios = []
        for s_pct in spot_bumps_pct:
            for v_pts in vol_bumps_pts:
                scenarios.append(Scenario(
                    name=f"S{s_pct:+.0f}% V{v_pts*100:+.0f}pts",
                    shocks=[
                        ShockSpec("spot", "relative", s_pct / 100.0),
                        ShockSpec("vol", "absolute", v_pts),
                    ],
                ))

        return self.run_stress_test(instruments, market_env, scenarios)