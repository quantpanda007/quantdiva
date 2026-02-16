"""
Monte Carlo pricing engines — European and American/Bermudan.

Fixes from audit (Round 1):
✓ T derived from instrument expiry and pricing date
✓ Market data extracted at correct maturity and strike
✓ Heston diagnostics use Euler discretization, not GBM
✓ Intrinsic values computed automatically inside pricing flow
✓ NPV computed automatically — no manual compute_intrinsic_values() call
✓ Longstaff-Schwartz backward pass fully vectorized
✓ MCResult integrated with PricingService lifecycle
✓ Discount factors from actual curve

Architecture:
- mc_simulation.py: path generation (GBM + Heston)
- longstaff_schwartz.py: LS backward regression (vectorized)
- mc_result.py: result container with Parquet/CSV export
- mc_vanilla_engine.py (this file): engine classes that wire everything together

Usage:
    # European
    engine = MCEuropeanEngine(num_paths=100_000, time_steps=252, seed=42)
    ql_engine = engine.build(model, market_env, instrument=option)
    # engine.last_result now has full diagnostics

    # American (Longstaff-Schwartz)
    engine = MCAmericanEngine(num_paths=100_000, time_steps=252, seed=42)
    ql_engine = engine.build(model, market_env, instrument=option)
    # engine.last_result has paths + exercise boundary + cashflows

    # Export
    engine.last_result.to_parquet("output/mc_run_001/")
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
    EngineType,
    ExerciseType,
    InstrumentType,
    ModelType,
    OptionType,
)
from core.exceptions.errors import EngineError, IncompatibleEngineError
from core.interfaces.base import BaseEngine, BaseInstrument, BaseModel, MarketEnvironment
from engines.monte_carlo.longstaff_schwartz import longstaff_schwartz
from engines.monte_carlo.mc_result import MCResult
from engines.monte_carlo.mc_simulation import (
    SimulationConfig,
    compute_discount_factors,
    compute_intrinsic_values,
    extract_heston_params,
    extract_market_data,
    simulate_gbm_paths,
    simulate_heston_paths,
)
from registry import engine_registry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: extract instrument info
# ---------------------------------------------------------------------------

def _extract_instrument_info(instrument: BaseInstrument) -> Dict[str, Any]:
    """Extract strike, option_type, expiry, exercise_type from instrument."""
    return {
        "strike": getattr(instrument, "strike", 100.0),
        "option_type": getattr(instrument, "option_type", OptionType.CALL),
        "expiry": instrument.maturity(),
        "exercise_type": getattr(instrument, "exercise_type", ExerciseType.EUROPEAN),
        "underlying": getattr(instrument, "underlying", ""),
        "bermudan_dates": getattr(instrument, "bermudan_dates", None),
    }


# ---------------------------------------------------------------------------
# MC European Engine
# ---------------------------------------------------------------------------

@engine_registry.register_decorator(
    (InstrumentType.VANILLA_OPTION.value, EngineType.MONTE_CARLO.value), overwrite=True
)
@dataclass
class MCEuropeanEngine(BaseEngine):
    """
    Monte Carlo engine for European vanilla options.

    Simulates paths and computes discounted terminal payoff.
    Stores full simulation state in MCResult for audit.

    Supports BSM and Heston models — uses correct simulation for each.

    Attributes:
        num_paths:   Number of MC paths (default: 50,000)
        time_steps:  Number of time steps per path (default: 252)
        seed:        Random seed for reproducibility
        antithetic:  Use antithetic variates for variance reduction
    """

    num_paths: int = 50_000
    time_steps: int = 252
    seed: int = 42
    antithetic: bool = True
    rng_type: str = "pseudorandom"          # "pseudorandom", "sobol", "halton"
    use_control_variate: bool = False        # BSM control variate
    use_moment_matching: bool = False        # match terminal mean to forward
    compute_mc_greeks: bool = False          # pathwise delta, LR vega, etc.

    last_result: Optional[MCResult] = field(default=None, repr=False)

    def engine_type(self) -> EngineType:
        return EngineType.MONTE_CARLO

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.VANILLA_OPTION]

    def supported_models(self) -> List[ModelType]:
        return [ModelType.BLACK_SCHOLES, ModelType.HESTON]

    def build(
        self,
        model: BaseModel,
        market_env: MarketEnvironment,
        instrument: Optional[BaseInstrument] = None,
        **kwargs,
    ) -> ql.PricingEngine:
        """
        Build QuantLib MC engine AND run diagnostics simulation.

        Args:
            model: BSM or Heston model
            market_env: Market data environment
            instrument: The option being priced (needed to derive T, K, type).
                        If None, diagnostics simulation is skipped.
        """
        process = model.build_process(market_env)

        # Build QuantLib engine
        if model.model_type() == ModelType.BLACK_SCHOLES:
            ql_engine = ql.MCEuropeanEngine(
                process, "pseudorandom",
                timeSteps=self.time_steps,
                requiredSamples=self.num_paths,
                seed=self.seed,
            )
        elif model.model_type() == ModelType.HESTON:
            ql_engine = ql.MCEuropeanHestonEngine(
                process, "pseudorandom",
                timeSteps=self.time_steps,
                requiredSamples=self.num_paths,
                seed=self.seed,
            )
        else:
            raise IncompatibleEngineError(
                f"MCEuropeanEngine does not support model {model.model_type()}"
            )

        # Run diagnostics simulation if instrument is provided
        if instrument is not None:
            self._run_diagnostics(model, market_env, instrument)

        return ql_engine

    def _run_diagnostics(
        self,
        model: BaseModel,
        market_env: MarketEnvironment,
        instrument: BaseInstrument,
    ) -> None:
        """Run parallel simulation with RNG selection, variance reduction, and Greeks."""
        t0 = time.perf_counter()
        info = _extract_instrument_info(instrument)

        # Extract market data at correct maturity and strike
        mkt = extract_market_data(
            market_env,
            underlying=info["underlying"],
            maturity=info["expiry"],
            strike=info["strike"],
        )

        is_call = info["option_type"] == OptionType.CALL

        # Build simulation config
        config = SimulationConfig(
            num_paths=self.num_paths,
            time_steps=self.time_steps,
            seed=self.seed,
            antithetic=False,  # handled by RNG layer now
            T=mkt["T"],
            spot=mkt["spot"],
            rate=mkt["rate"],
            div_yield=mkt["div_yield"],
            vol=mkt["vol"],
        )

        # --- Step 1: Generate random numbers using selected RNG ---
        from engines.monte_carlo.rng import create_rng, apply_antithetic

        rng = create_rng(self.rng_type, seed=self.seed)
        Z = rng.generate(self.time_steps, self.num_paths)

        if self.antithetic:
            Z = apply_antithetic(Z, self.num_paths)

        # --- Step 2: Simulate paths (model-aware) ---
        if model.model_type() == ModelType.HESTON:
            heston_params = extract_heston_params(model)
            config.heston_v0 = heston_params["heston_v0"]
            config.heston_kappa = heston_params["heston_kappa"]
            config.heston_theta = heston_params["heston_theta"]
            config.heston_sigma = heston_params["heston_sigma"]
            config.heston_rho = heston_params["heston_rho"]
            Z, spot_paths = simulate_heston_paths(config, Z1=Z)
        else:
            Z, spot_paths = simulate_gbm_paths(config, Z=Z)

        # --- Step 3: Variance reduction ---
        IV = compute_intrinsic_values(spot_paths, info["strike"], is_call)
        df = compute_discount_factors(mkt["rate"], mkt["T"], self.time_steps)
        terminal_payoffs = IV[-1, :]
        discounted_payoffs = terminal_payoffs * df[-1]

        vr_diagnostics = {}
        if self.use_moment_matching or self.use_control_variate:
            from engines.monte_carlo.variance_reduction import apply_all_variance_reduction

            _, npv, std_err, vr_diagnostics = apply_all_variance_reduction(
                spot_paths=spot_paths,
                strike=info["strike"],
                T=mkt["T"],
                rate=mkt["rate"],
                div_yield=mkt["div_yield"],
                vol=mkt["vol"],
                is_call=is_call,
                use_moment_matching=self.use_moment_matching,
                use_control_variate=self.use_control_variate,
            )
        else:
            npv = float(np.mean(discounted_payoffs))
            std_err = float(np.std(discounted_payoffs) / np.sqrt(self.num_paths))

        # --- Step 4: MC Greeks ---
        greeks_output = {}
        if self.compute_mc_greeks and model.model_type() == ModelType.BLACK_SCHOLES:
            from engines.monte_carlo.mc_greeks import MCGreeks

            mc_greeks = MCGreeks()
            greeks_result = mc_greeks.compute_all(
                spot_paths=spot_paths,
                random_numbers=Z,
                strike=info["strike"],
                T=mkt["T"],
                rate=mkt["rate"],
                div_yield=mkt["div_yield"],
                vol=mkt["vol"],
                is_call=is_call,
            )
            greeks_output = greeks_result.to_dict_with_errors()

        elapsed = time.perf_counter() - t0

        self.last_result = MCResult(
            metadata={
                "engine": "MCEuropeanEngine",
                "model": model.model_type().value,
                "underlying": info["underlying"],
                "strike": info["strike"],
                "option_type": info["option_type"].value,
                "exercise_type": "european",
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
                "variance_reduction": vr_diagnostics,
                "mc_greeks": greeks_output,
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
            f"MC European diagnostics: NPV={npv:.6f} ± {std_err:.6f} "
            f"(rng={rng.name()}, {self.num_paths} paths, {elapsed:.3f}s)"
        )


# ---------------------------------------------------------------------------
# MC American / Bermudan Engine (Longstaff-Schwartz)
# ---------------------------------------------------------------------------

@engine_registry.register_decorator(
    (InstrumentType.VANILLA_OPTION.value, "mc_american"), overwrite=True
)
@dataclass
class MCAmericanEngine(BaseEngine):
    """
    Monte Carlo engine with Longstaff-Schwartz for American/Bermudan options.

    Uses least-squares regression to determine optimal early exercise.
    All diagnostics (paths, exercise boundary, cashflows) stored in MCResult.

    Attributes:
        num_paths:      Number of MC paths
        time_steps:     Number of time steps
        seed:           Random seed
        poly_degree:    Polynomial degree for LS regression (default: 3)
        antithetic:     Use antithetic variates
    """

    num_paths: int = 50_000
    time_steps: int = 252
    seed: int = 42
    poly_degree: int = 3
    antithetic: bool = True
    rng_type: str = "pseudorandom"          # "pseudorandom", "sobol", "halton"

    last_result: Optional[MCResult] = field(default=None, repr=False)

    def engine_type(self) -> EngineType:
        return EngineType.MONTE_CARLO

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.VANILLA_OPTION]

    def supported_models(self) -> List[ModelType]:
        return [ModelType.BLACK_SCHOLES]

    def build(
        self,
        model: BaseModel,
        market_env: MarketEnvironment,
        instrument: Optional[BaseInstrument] = None,
        **kwargs,
    ) -> ql.PricingEngine:
        """Build QuantLib MC American engine + run LS diagnostics."""
        if model.model_type() != ModelType.BLACK_SCHOLES:
            raise IncompatibleEngineError(
                f"MCAmericanEngine requires BLACK_SCHOLES model, "
                f"got {model.model_type()}"
            )

        process = model.build_process(market_env)

        ql_engine = ql.MCAmericanEngine(
            process, "pseudorandom",
            timeSteps=self.time_steps,
            requiredSamples=self.num_paths,
            seed=self.seed,
            polynomOrder=self.poly_degree,
        )

        # Run full LS diagnostics
        if instrument is not None:
            self._run_ls_diagnostics(model, market_env, instrument)

        return ql_engine

    def _run_ls_diagnostics(
        self,
        model: BaseModel,
        market_env: MarketEnvironment,
        instrument: BaseInstrument,
    ) -> None:
        """Run Longstaff-Schwartz with full diagnostics capture."""
        t0 = time.perf_counter()
        info = _extract_instrument_info(instrument)

        # Extract market data at correct T and K
        mkt = extract_market_data(
            market_env,
            underlying=info["underlying"],
            maturity=info["expiry"],
            strike=info["strike"],
        )

        is_call = info["option_type"] == OptionType.CALL

        # Build config
        config = SimulationConfig(
            num_paths=self.num_paths,
            time_steps=self.time_steps,
            seed=self.seed,
            antithetic=False,  # handled by RNG layer
            T=mkt["T"],
            spot=mkt["spot"],
            rate=mkt["rate"],
            div_yield=mkt["div_yield"],
            vol=mkt["vol"],
        )

        # Generate random numbers using selected RNG
        from engines.monte_carlo.rng import create_rng, apply_antithetic

        rng = create_rng(self.rng_type, seed=self.seed)
        Z = rng.generate(self.time_steps, self.num_paths)

        if self.antithetic:
            Z = apply_antithetic(Z, self.num_paths)

        # Simulate paths (BSM only for now)
        Z, spot_paths = simulate_gbm_paths(config, Z=Z)

        # Intrinsic values
        IV = compute_intrinsic_values(spot_paths, info["strike"], is_call)

        # Discount factors
        df = compute_discount_factors(mkt["rate"], mkt["T"], self.time_steps)

        # Determine exercise indices for Bermudan
        exercise_indices = None
        if info["exercise_type"] == ExerciseType.BERMUDAN and info["bermudan_dates"]:
            # Map bermudan dates to time step indices
            pricing_date = market_env.pricing_date.value
            total_days = (info["expiry"] - pricing_date).days
            if total_days > 0:
                exercise_indices = []
                for bd in info["bermudan_dates"]:
                    day_idx = (bd - pricing_date).days
                    step_idx = int(round(day_idx / total_days * self.time_steps))
                    step_idx = max(1, min(step_idx, self.time_steps))
                    exercise_indices.append(step_idx)

        # Run Longstaff-Schwartz (vectorized)
        ls_result = longstaff_schwartz(
            spot_paths=spot_paths,
            intrinsic_values=IV,
            discount_factors=df,
            is_call=is_call,
            poly_degree=self.poly_degree,
            exercise_indices=exercise_indices,
        )

        elapsed = time.perf_counter() - t0

        # Build MCResult
        self.last_result = MCResult(
            metadata={
                "engine": "MCAmericanEngine (Longstaff-Schwartz)",
                "model": model.model_type().value,
                "underlying": info["underlying"],
                "strike": info["strike"],
                "option_type": info["option_type"].value,
                "exercise_type": info["exercise_type"].value,
                "T": mkt["T"],
                "spot": mkt["spot"],
                "rate": mkt["rate"],
                "div_yield": mkt["div_yield"],
                "vol": mkt["vol"],
                "num_paths": self.num_paths,
                "time_steps": self.time_steps,
                "seed": self.seed,
                "rng_type": rng.name(),
                "poly_degree": self.poly_degree,
                "antithetic": self.antithetic,
                "bermudan_exercise_indices": exercise_indices,
                "timestamp": datetime.utcnow().isoformat(),
            },
            random_numbers=Z,
            spot_paths=spot_paths,
            intrinsic_values=IV,
            discount_factors=df,
            continuation_values=ls_result.continuation_values,
            exercise_flags=ls_result.exercise_flags,
            exercise_boundary=ls_result.exercise_boundary,
            cashflows=np.column_stack([ls_result.cashflow_times, ls_result.cashflow_values]),
            npv=ls_result.npv,
            std_error=ls_result.std_error,
            confidence_interval=ls_result.confidence_interval,
            elapsed_seconds=elapsed,
        )

        # Log summary
        early_pct = 0.0
        if ls_result.exercise_flags is not None:
            early = np.any(ls_result.exercise_flags[:-1, :], axis=0)
            early_pct = float(np.mean(early) * 100)

        logger.info(
            f"MC American diagnostics: NPV={ls_result.npv:.6f} ± {ls_result.std_error:.6f} "
            f"(early exercise: {early_pct:.1f}%, {self.num_paths} paths, {elapsed:.3f}s)"
        )
