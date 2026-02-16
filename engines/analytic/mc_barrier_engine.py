"""
Monte Carlo engine for barrier options.

Barrier options are path-dependent: we must check at each time step
whether the spot has crossed the barrier.

Two monitoring approaches:
- Discrete monitoring: check barrier only at time step points
- Continuous monitoring adjustment: apply Broadie-Glasserman-Kou
  correction to account for barrier crossings between steps

The engine stores full diagnostics including:
- Which paths hit the barrier
- When each path hit the barrier
- Barrier hit rate

Usage:
    from engines.monte_carlo.mc_barrier_engine import MCBarrierEngine

    engine = MCBarrierEngine(num_paths=100_000, time_steps=252)
    ql_engine = engine.build(model, market_env, instrument=barrier_opt)
    # engine.last_result has full diagnostics
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import QuantLib as ql

from core.enums.definitions import (
    BarrierType,
    EngineType,
    InstrumentType,
    ModelType,
    OptionType,
)
from core.exceptions.errors import IncompatibleEngineError
from core.interfaces.base import BaseEngine, BaseInstrument, BaseModel, MarketEnvironment
from engines.monte_carlo.mc_result import MCResult
from engines.monte_carlo.mc_simulation import (
    SimulationConfig,
    compute_discount_factors,
    compute_intrinsic_values,
    extract_market_data,
    simulate_gbm_paths,
)
from engines.monte_carlo.rng import apply_antithetic, create_rng
from registry import engine_registry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Barrier monitoring logic
# ---------------------------------------------------------------------------

def check_barrier_hits(
    spot_paths: np.ndarray,
    barrier_level: float,
    barrier_type: BarrierType,
) -> tuple:
    """
    Check which paths hit the barrier and when.

    Args:
        spot_paths:     (T+1, N) simulated spot prices
        barrier_level:  barrier trigger level
        barrier_type:   UP_IN, UP_OUT, DOWN_IN, DOWN_OUT

    Returns:
        hit_mask:       (N,) boolean — True if path hit the barrier
        hit_time:       (N,) int — time step when barrier was first hit (-1 if never)
    """
    M_plus_1, N = spot_paths.shape

    if barrier_type in (BarrierType.UP_IN, BarrierType.UP_OUT):
        # Hit = spot crossed above barrier
        crossed = spot_paths >= barrier_level
    else:
        # Hit = spot crossed below barrier
        crossed = spot_paths <= barrier_level

    # Any hit across time steps (per path)
    hit_mask = np.any(crossed, axis=0)  # (N,)

    # First hit time per path
    hit_time = np.full(N, -1, dtype=int)
    for j in range(N):
        if hit_mask[j]:
            hit_time[j] = int(np.argmax(crossed[:, j]))

    return hit_mask, hit_time


def compute_barrier_payoffs(
    spot_paths: np.ndarray,
    strike: float,
    barrier_level: float,
    barrier_type: BarrierType,
    is_call: bool,
    rebate: float,
    discount_factors: np.ndarray,
) -> tuple:
    """
    Compute barrier option payoffs per path.

    Logic:
    - Knock-Out: pays intrinsic at expiry if barrier NOT hit, else rebate
    - Knock-In: pays intrinsic at expiry if barrier WAS hit, else rebate at expiry

    Args:
        spot_paths:       (T+1, N)
        strike:           option strike
        barrier_level:    barrier trigger
        barrier_type:     BarrierType enum
        is_call:          True for call
        rebate:           cash rebate
        discount_factors: (T+1,) discount factors

    Returns:
        payoffs:          (N,) discounted payoff per path
        hit_mask:         (N,) boolean
        hit_time:         (N,) int
    """
    N = spot_paths.shape[1]
    S_T = spot_paths[-1, :]

    # Terminal intrinsic value
    if is_call:
        intrinsic = np.maximum(S_T - strike, 0.0)
    else:
        intrinsic = np.maximum(strike - S_T, 0.0)

    # Check barrier hits
    hit_mask, hit_time = check_barrier_hits(spot_paths, barrier_level, barrier_type)

    # Compute payoffs based on barrier type
    payoffs = np.zeros(N)
    df_terminal = discount_factors[-1]

    if barrier_type in (BarrierType.UP_OUT, BarrierType.DOWN_OUT):
        # Knock-Out: pays intrinsic only if NOT hit
        alive = ~hit_mask
        payoffs[alive] = intrinsic[alive] * df_terminal

        # Rebate: paid at hit time (discounted from hit time)
        if rebate > 0:
            hit_paths = np.where(hit_mask)[0]
            for j in hit_paths:
                t_hit = hit_time[j]
                payoffs[j] = rebate * discount_factors[t_hit]

    elif barrier_type in (BarrierType.UP_IN, BarrierType.DOWN_IN):
        # Knock-In: pays intrinsic only if WAS hit
        payoffs[hit_mask] = intrinsic[hit_mask] * df_terminal

        # Rebate: paid at expiry if never hit
        if rebate > 0:
            not_hit = ~hit_mask
            payoffs[not_hit] = rebate * df_terminal

    return payoffs, hit_mask, hit_time


# ---------------------------------------------------------------------------
# Broadie-Glasserman-Kou correction
# ---------------------------------------------------------------------------

def broadie_glasserman_correction(
    barrier_level: float,
    vol: float,
    T: float,
    time_steps: int,
    is_up: bool,
) -> float:
    """
    Compute the Broadie-Glasserman-Kou adjusted barrier for discrete monitoring.

    When monitoring at discrete time steps, the barrier is effectively
    further away than in continuous monitoring. This correction adjusts
    the barrier to approximate continuous monitoring.

    Adjusted barrier:
        Up barrier:   B * exp(+β * σ * √(T/M))
        Down barrier: B * exp(-β * σ * √(T/M))

    where β ≈ 0.5826 (= -ζ(1/2) / √(2π))
    """
    beta = 0.5826  # Broadie-Glasserman constant
    dt = T / time_steps
    adjustment = beta * vol * np.sqrt(dt)

    if is_up:
        return barrier_level * np.exp(adjustment)
    else:
        return barrier_level * np.exp(-adjustment)


# ---------------------------------------------------------------------------
# MC Barrier Engine
# ---------------------------------------------------------------------------

@engine_registry.register_decorator(
    (InstrumentType.BARRIER_OPTION.value, EngineType.MONTE_CARLO.value),
    overwrite=True,
)
@dataclass
class MCBarrierEngine(BaseEngine):
    """
    Monte Carlo engine for barrier options.

    Simulates paths and checks barrier crossing at each time step.
    Optionally applies Broadie-Glasserman-Kou correction for
    discrete monitoring bias.

    Attributes:
        num_paths:          Number of MC paths
        time_steps:         Number of time steps (more = better barrier monitoring)
        seed:               Random seed
        antithetic:         Use antithetic variates
        rng_type:           "pseudorandom", "sobol", "halton"
        apply_bgk_correction: Apply Broadie-Glasserman-Kou discrete monitoring correction
    """

    num_paths: int = 100_000
    time_steps: int = 500  # more steps for better barrier monitoring
    seed: int = 42
    antithetic: bool = True
    rng_type: str = "pseudorandom"
    apply_bgk_correction: bool = True

    last_result: Optional[MCResult] = field(default=None, repr=False)

    def engine_type(self) -> EngineType:
        return EngineType.MONTE_CARLO

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.BARRIER_OPTION]

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
                f"MCBarrierEngine requires BLACK_SCHOLES model, "
                f"got {model.model_type()}"
            )

        process = model.build_process(market_env)

        # QuantLib MC barrier engine
        ql_engine = ql.MCBarrierEngine(
            process, "pseudorandom",
            timeSteps=self.time_steps,
            requiredSamples=self.num_paths,
            seed=self.seed,
        )

        # Run diagnostics
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

        strike = getattr(instrument, "strike", 100.0)
        barrier_level = getattr(instrument, "barrier_level", 0.0)
        barrier_type = getattr(instrument, "barrier_type", BarrierType.DOWN_OUT)
        rebate = getattr(instrument, "rebate", 0.0)
        option_type = getattr(instrument, "option_type", OptionType.CALL)
        underlying = getattr(instrument, "underlying", "")
        is_call = option_type == OptionType.CALL

        # Extract market data
        mkt = extract_market_data(
            market_env,
            underlying=underlying,
            maturity=instrument.maturity(),
            strike=strike,
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

        # Generate random numbers
        rng = create_rng(self.rng_type, seed=self.seed)
        Z = rng.generate(self.time_steps, self.num_paths)
        if self.antithetic:
            Z = apply_antithetic(Z, self.num_paths)

        # Simulate paths
        Z, spot_paths = simulate_gbm_paths(config, Z=Z)

        # Apply BGK correction if requested
        effective_barrier = barrier_level
        if self.apply_bgk_correction:
            is_up = barrier_type in (BarrierType.UP_IN, BarrierType.UP_OUT)
            effective_barrier = broadie_glasserman_correction(
                barrier_level, mkt["vol"], mkt["T"], self.time_steps, is_up
            )

        # Compute discount factors
        df = compute_discount_factors(mkt["rate"], mkt["T"], self.time_steps)

        # Compute barrier payoffs
        payoffs, hit_mask, hit_time = compute_barrier_payoffs(
            spot_paths=spot_paths,
            strike=strike,
            barrier_level=effective_barrier,
            barrier_type=barrier_type,
            is_call=is_call,
            rebate=rebate,
            discount_factors=df,
        )

        # Intrinsic values (for diagnostics)
        IV = compute_intrinsic_values(spot_paths, strike, is_call)

        # NPV
        npv = float(np.mean(payoffs))
        std_err = float(np.std(payoffs) / np.sqrt(self.num_paths))
        hit_rate = float(np.mean(hit_mask) * 100)

        elapsed = time.perf_counter() - t0

        self.last_result = MCResult(
            metadata={
                "engine": "MCBarrierEngine",
                "model": model.model_type().value,
                "underlying": underlying,
                "strike": strike,
                "option_type": option_type.value,
                "barrier_type": barrier_type.value,
                "barrier_level": barrier_level,
                "effective_barrier": effective_barrier,
                "rebate": rebate,
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
                "bgk_correction": self.apply_bgk_correction,
                "barrier_hit_rate_pct": hit_rate,
                "timestamp": datetime.utcnow().isoformat(),
            },
            random_numbers=Z,
            spot_paths=spot_paths,
            intrinsic_values=IV,
            discount_factors=df,
            npv=npv,
            std_error=std_err,
            confidence_interval=(npv - 1.96 * std_err, npv + 1.96 * std_err),
            elapsed_seconds=elapsed,
        )

        logger.info(
            f"MC Barrier diagnostics: NPV={npv:.6f} ± {std_err:.6f}, "
            f"barrier hit rate={hit_rate:.1f}%, "
            f"{self.num_paths} paths, {elapsed:.3f}s"
        )