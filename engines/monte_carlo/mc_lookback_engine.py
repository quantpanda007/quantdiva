"""
Monte Carlo engine for lookback options.

Simulates paths and tracks running maximum and minimum at each time step.
Supports both fixed and floating strike lookbacks.

For discrete monitoring (more realistic than continuous), MC is the
standard approach since the analytic formula only covers continuous.

Diagnostics include:
- Running max/min evolution across paths
- Distribution of extrema at expiry
- Comparison with continuous monitoring analytic price

Usage:
    from engines.monte_carlo.mc_lookback_engine import MCLookbackEngine

    engine = MCLookbackEngine(num_paths=200_000, time_steps=500)
    ql_engine = engine.build(model, market_env, instrument=lookback_opt)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

import numpy as np
import QuantLib as ql

from core.enums.definitions import EngineType, InstrumentType, ModelType, OptionType
from core.exceptions.errors import IncompatibleEngineError
from core.interfaces.base import BaseEngine, BaseInstrument, BaseModel, MarketEnvironment
from engines.monte_carlo.mc_result import MCResult
from engines.monte_carlo.mc_simulation import (
    SimulationConfig,
    compute_discount_factors,
    extract_market_data,
    simulate_gbm_paths,
)
from engines.monte_carlo.rng import apply_antithetic, create_rng
from registry import engine_registry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Running extrema computation
# ---------------------------------------------------------------------------

def compute_running_max(spot_paths: np.ndarray) -> np.ndarray:
    """
    Compute running maximum along each path.

    Args:
        spot_paths: (T+1, N)

    Returns:
        running_max: (T+1, N) — cumulative max up to each time step
    """
    return np.maximum.accumulate(spot_paths, axis=0)


def compute_running_min(spot_paths: np.ndarray) -> np.ndarray:
    """
    Compute running minimum along each path.

    Args:
        spot_paths: (T+1, N)

    Returns:
        running_min: (T+1, N) — cumulative min up to each time step
    """
    return np.minimum.accumulate(spot_paths, axis=0)


# ---------------------------------------------------------------------------
# MC Lookback Engine
# ---------------------------------------------------------------------------

@engine_registry.register_decorator(
    ("lookback_option", EngineType.MONTE_CARLO.value), overwrite=True
)
@dataclass
class MCLookbackEngine(BaseEngine):
    """
    Monte Carlo engine for lookback options.

    Tracks running max/min along simulated paths for discrete monitoring.
    Stores full diagnostics including extrema distributions.

    Attributes:
        num_paths:    Number of MC paths
        time_steps:   Number of time steps (more = finer monitoring)
        seed:         Random seed
        antithetic:   Use antithetic variates
        rng_type:     RNG type
    """

    num_paths: int = 200_000
    time_steps: int = 500
    seed: int = 42
    antithetic: bool = True
    rng_type: str = "pseudorandom"

    last_result: Optional[MCResult] = field(default=None, repr=False)

    def engine_type(self) -> EngineType:
        return EngineType.MONTE_CARLO

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.LOOKBACK_OPTION]

    def supported_models(self) -> List[ModelType]:
        return [ModelType.BLACK_SCHOLES]

    def build(
        self,
        model: BaseModel,
        market_env: MarketEnvironment,
        instrument: BaseInstrument = None,
        **kwargs,
    ) -> ql.PricingEngine:
        if model.model_type() != ModelType.BLACK_SCHOLES:
            raise IncompatibleEngineError(
                f"MCLookbackEngine requires BLACK_SCHOLES, "
                f"got {model.model_type()}"
            )

        process = model.build_process(market_env)

        # QuantLib doesn't have a dedicated MC lookback engine,
        # so we return the analytic engine for QuantLib pricing
        # and use our own MC simulation for diagnostics.
        from instruments.equity.lookback_option import LookbackStrikeType
        strike_type = getattr(instrument, "strike_type", LookbackStrikeType.FLOATING)

        if strike_type == LookbackStrikeType.FLOATING:
            ql_engine = ql.AnalyticContinuousFloatingLookbackEngine(process)
        else:
            ql_engine = ql.AnalyticContinuousFixedLookbackEngine(process)

        # Run MC diagnostics
        if instrument is not None:
            self._run_diagnostics(model, market_env, instrument)

        return ql_engine

    def _run_diagnostics(
        self,
        model: BaseModel,
        market_env: MarketEnvironment,
        instrument: BaseInstrument,
    ) -> None:
        t0 = time.perf_counter()

        from instruments.equity.lookback_option import LookbackStrikeType

        strike = getattr(instrument, "strike", 0.0)
        option_type = getattr(instrument, "option_type", OptionType.CALL)
        underlying = getattr(instrument, "underlying", "")
        strike_type = getattr(instrument, "strike_type", LookbackStrikeType.FLOATING)
        current_max = getattr(instrument, "current_max", None)
        current_min = getattr(instrument, "current_min", None)
        is_call = option_type == OptionType.CALL

        # Market data
        mkt = extract_market_data(
            market_env,
            underlying=underlying,
            maturity=instrument.maturity(),
            strike=max(strike, mkt["spot"]) if strike > 0 else None,
        ) if False else extract_market_data(
            market_env,
            underlying=underlying,
            maturity=instrument.maturity(),
            strike=strike if strike > 0 else market_env.spot_prices.get(underlying, 100.0),
        )

        # Config
        config = SimulationConfig(
            num_paths=self.num_paths,
            time_steps=self.time_steps,
            seed=self.seed,
            T=mkt["T"],
            spot=mkt["spot"],
            rate=mkt["rate"],
            div_yield=mkt["div_yield"],
            vol=mkt["vol"],
        )

        # Generate and simulate
        rng = create_rng(self.rng_type, seed=self.seed)
        Z = rng.generate(self.time_steps, self.num_paths)
        if self.antithetic:
            Z = apply_antithetic(Z, self.num_paths)

        Z, spot_paths = simulate_gbm_paths(config, Z=Z)

        # Incorporate current running extrema if provided
        if current_max is not None:
            # Prepend a row with current_max to ensure running max starts there
            spot_paths[0, :] = np.maximum(spot_paths[0, :], current_max)
        if current_min is not None:
            spot_paths[0, :] = np.minimum(spot_paths[0, :], current_min)

        # Compute running extrema
        running_max = compute_running_max(spot_paths)
        running_min = compute_running_min(spot_paths)

        S_T = spot_paths[-1, :]
        S_max = running_max[-1, :]  # terminal running max
        S_min = running_min[-1, :]  # terminal running min

        # Compute payoffs
        df_terminal = np.exp(-mkt["rate"] * mkt["T"])

        if strike_type == LookbackStrikeType.FLOATING:
            if is_call:
                # Call: S(T) - S_min
                payoffs = (S_T - S_min) * df_terminal
            else:
                # Put: S_max - S(T)
                payoffs = (S_max - S_T) * df_terminal
        else:
            # Fixed strike
            if is_call:
                # Call: max(S_max - K, 0)
                payoffs = np.maximum(S_max - strike, 0.0) * df_terminal
            else:
                # Put: max(K - S_min, 0)
                payoffs = np.maximum(strike - S_min, 0.0) * df_terminal

        npv = float(np.mean(payoffs))
        std_err = float(np.std(payoffs) / np.sqrt(self.num_paths))

        # Discount factors
        df = compute_discount_factors(mkt["rate"], mkt["T"], self.time_steps)

        elapsed = time.perf_counter() - t0

        self.last_result = MCResult(
            metadata={
                "engine": "MCLookbackEngine",
                "model": model.model_type().value,
                "underlying": underlying,
                "strike": strike,
                "option_type": option_type.value,
                "strike_type": strike_type.value,
                "T": mkt["T"],
                "spot": mkt["spot"],
                "rate": mkt["rate"],
                "div_yield": mkt["div_yield"],
                "vol": mkt["vol"],
                "num_paths": self.num_paths,
                "time_steps": self.time_steps,
                "seed": self.seed,
                "rng_type": rng.name(),
                "antithetic": self.antithetic,
                "current_max": current_max,
                "current_min": current_min,
                "terminal_max_mean": float(np.mean(S_max)),
                "terminal_min_mean": float(np.mean(S_min)),
                "terminal_max_std": float(np.std(S_max)),
                "terminal_min_std": float(np.std(S_min)),
                "timestamp": datetime.utcnow().isoformat(),
            },
            random_numbers=Z,
            spot_paths=spot_paths,
            discount_factors=df,
            npv=npv,
            std_error=std_err,
            confidence_interval=(npv - 1.96 * std_err, npv + 1.96 * std_err),
            elapsed_seconds=elapsed,
        )

        logger.info(
            f"MC Lookback diagnostics: NPV={npv:.6f} ± {std_err:.6f}, "
            f"S_max_mean={np.mean(S_max):.2f}, S_min_mean={np.mean(S_min):.2f}, "
            f"{self.num_paths} paths, {elapsed:.3f}s"
        )