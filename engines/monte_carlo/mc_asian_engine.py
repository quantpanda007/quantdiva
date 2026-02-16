"""
Monte Carlo engine for Asian options.

Handles both arithmetic and geometric averaging.
The key technique: use geometric Asian (which has a known analytic price)
as a control variate for arithmetic Asian pricing.

This is one of the most effective variance reduction techniques in
quantitative finance because:
1. Geometric and arithmetic averages are >99% correlated
2. Geometric has a known closed-form price
3. Variance reduction factor is typically 50-200×

Algorithm:
    V_arith_adjusted = V_arith_mc - β * (V_geom_mc - V_geom_analytic)

    where β = Cov(V_arith, V_geom) / Var(V_geom) ≈ 1

Usage:
    engine = MCAsianEngine(
        num_paths=200_000,
        time_steps=252,
        use_geometric_cv=True,
    )
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

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
# Average computation
# ---------------------------------------------------------------------------

def compute_arithmetic_average(
    spot_paths: np.ndarray,
    fixing_indices: np.ndarray,
) -> np.ndarray:
    """
    Compute arithmetic average of spot at fixing dates for each path.

    Args:
        spot_paths:     (T+1, N) simulated spot prices
        fixing_indices: (F,) time step indices where fixings occur

    Returns:
        averages: (N,) arithmetic average per path
    """
    fixing_values = spot_paths[fixing_indices, :]  # (F, N)
    return np.mean(fixing_values, axis=0)


def compute_geometric_average(
    spot_paths: np.ndarray,
    fixing_indices: np.ndarray,
) -> np.ndarray:
    """
    Compute geometric average of spot at fixing dates for each path.

    avg_geom = exp(mean(ln(S))) = (∏ S_i)^(1/N)

    Args:
        spot_paths:     (T+1, N) simulated spot prices
        fixing_indices: (F,) time step indices where fixings occur

    Returns:
        averages: (N,) geometric average per path
    """
    fixing_values = spot_paths[fixing_indices, :]  # (F, N)
    return np.exp(np.mean(np.log(fixing_values), axis=0))


def fixing_dates_to_indices(
    fixing_dates: List,
    pricing_date,
    expiry_date,
    time_steps: int,
) -> np.ndarray:
    """
    Map fixing dates to time step indices in the simulation grid.

    Args:
        fixing_dates:  list of dates (datetime.date or ql.Date)
        pricing_date:  pricing date
        expiry_date:   expiry date
        time_steps:    number of simulation time steps

    Returns:
        indices: (F,) array of time step indices
    """
    from datetime import date as dt_date

    def to_python_date(d):
        if isinstance(d, ql.Date):
            return dt_date(d.year(), d.month(), d.dayOfMonth())
        return d

    pricing_dt = to_python_date(pricing_date)
    expiry_dt = to_python_date(expiry_date)
    total_days = (expiry_dt - pricing_dt).days

    if total_days <= 0:
        return np.array([time_steps])

    indices = []
    for fd in fixing_dates:
        fd_dt = to_python_date(fd)
        day_idx = (fd_dt - pricing_dt).days
        step_idx = int(round(day_idx / total_days * time_steps))
        step_idx = max(1, min(step_idx, time_steps))
        indices.append(step_idx)

    return np.array(sorted(set(indices)), dtype=int)


# ---------------------------------------------------------------------------
# Geometric Asian analytic price (for control variate)
# ---------------------------------------------------------------------------

def geometric_asian_analytic_price(
    spot: float,
    strike: float,
    T: float,
    rate: float,
    div_yield: float,
    vol: float,
    num_fixings: int,
    is_call: bool,
) -> float:
    """
    Closed-form price for geometric average price Asian option.

    Under GBM, geometric average is lognormal with adjusted parameters:
        vol_adj = vol * sqrt((2N + 1) / (6(N + 1)))
        mu_adj = (vol_adj² / 2) + (rate - div_yield - vol² / 2) * (N + 1) / (2N)
                 ... simplified form using the Kemna-Vorst result

    This is a simplified version for the control variate —
    close enough for variance reduction to work well.
    """
    from scipy.stats import norm

    if T <= 0 or vol <= 0 or num_fixings <= 0:
        return 0.0

    N = num_fixings

    # Adjusted volatility for geometric average
    vol_adj = vol * np.sqrt((2 * N + 1) / (6 * (N + 1)))

    # Adjusted drift
    mu_adj = 0.5 * vol_adj ** 2 + (rate - div_yield - 0.5 * vol ** 2) * ((N + 1) / (2 * N))

    # BSM with adjusted parameters
    d1 = (np.log(spot / strike) + (mu_adj + 0.5 * vol_adj ** 2) * T) / (vol_adj * np.sqrt(T))
    d2 = d1 - vol_adj * np.sqrt(T)

    df = np.exp(-rate * T)

    if is_call:
        price = df * (spot * np.exp(mu_adj * T) * norm.cdf(d1) - strike * norm.cdf(d2))
    else:
        price = df * (strike * norm.cdf(-d2) - spot * np.exp(mu_adj * T) * norm.cdf(-d1))

    return max(float(price), 0.0)


# ---------------------------------------------------------------------------
# MC Asian Engine
# ---------------------------------------------------------------------------

@engine_registry.register_decorator(
    ("asian_option", EngineType.MONTE_CARLO.value), overwrite=True
)
@dataclass
class MCAsianEngine(BaseEngine):
    """
    Monte Carlo engine for Asian options.

    Handles arithmetic and geometric averaging with discrete fixings.
    Uses geometric Asian as control variate for arithmetic (optional but
    strongly recommended — typically 50-200× variance reduction).

    Attributes:
        num_paths:          Number of MC paths
        time_steps:         Number of simulation time steps
        seed:               Random seed
        antithetic:         Use antithetic variates
        rng_type:           RNG type
        use_geometric_cv:   Use geometric Asian as control variate (default: True)
    """

    num_paths: int = 200_000
    time_steps: int = 500
    seed: int = 42
    antithetic: bool = True
    rng_type: str = "pseudorandom"
    use_geometric_cv: bool = True

    last_result: Optional[MCResult] = field(default=None, repr=False)

    def engine_type(self) -> EngineType:
        return EngineType.MONTE_CARLO

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.ASIAN_OPTION]

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
                f"MCAsianEngine requires BLACK_SCHOLES, got {model.model_type()}"
            )

        process = model.build_process(market_env)

        # QuantLib MC Asian engine
        ql_engine = ql.MCDiscreteArithmeticAPEngine(
            process, "pseudorandom",
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
        option_type = getattr(instrument, "option_type", OptionType.CALL)
        underlying = getattr(instrument, "underlying", "")
        is_call = option_type == OptionType.CALL

        from instruments.equity.asian_option import AverageType
        average_type = getattr(instrument, "average_type", AverageType.ARITHMETIC)

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

        # Resolve fixing indices
        all_fixings = instrument._resolve_fixing_dates(market_env)
        pricing_date = market_env.pricing_date.value
        future_fixings = [d for d in all_fixings if d > pricing_date]

        fixing_indices = fixing_dates_to_indices(
            future_fixings, pricing_date, instrument.maturity(), self.time_steps
        )

        num_fixings = len(fixing_indices)
        df_terminal = np.exp(-mkt["rate"] * mkt["T"])

        # Compute averages
        arith_avg = compute_arithmetic_average(spot_paths, fixing_indices)
        geom_avg = compute_geometric_average(spot_paths, fixing_indices)

        # Payoffs
        if is_call:
            arith_payoffs = np.maximum(arith_avg - strike, 0.0) * df_terminal
            geom_payoffs = np.maximum(geom_avg - strike, 0.0) * df_terminal
        else:
            arith_payoffs = np.maximum(strike - arith_avg, 0.0) * df_terminal
            geom_payoffs = np.maximum(strike - geom_avg, 0.0) * df_terminal

        # Control variate
        cv_diagnostics = {}
        if self.use_geometric_cv and average_type == AverageType.ARITHMETIC:
            # Analytic geometric price
            geom_analytic = geometric_asian_analytic_price(
                spot=mkt["spot"],
                strike=strike,
                T=mkt["T"],
                rate=mkt["rate"],
                div_yield=mkt["div_yield"],
                vol=mkt["vol"],
                num_fixings=num_fixings,
                is_call=is_call,
            )

            # Optimal beta
            cov_matrix = np.cov(arith_payoffs, geom_payoffs)
            var_geom = cov_matrix[1, 1]
            if var_geom > 1e-16:
                beta = cov_matrix[0, 1] / var_geom
            else:
                beta = 1.0

            geom_mc = float(np.mean(geom_payoffs))

            # Adjusted payoffs
            adjusted_payoffs = arith_payoffs - beta * (geom_payoffs - geom_analytic)

            npv = float(np.mean(adjusted_payoffs))
            std_err = float(np.std(adjusted_payoffs) / np.sqrt(self.num_paths))

            raw_npv = float(np.mean(arith_payoffs))
            raw_std = float(np.std(arith_payoffs) / np.sqrt(self.num_paths))

            variance_ratio = np.var(adjusted_payoffs) / np.var(arith_payoffs) if np.var(arith_payoffs) > 0 else 1.0

            cv_diagnostics = {
                "geometric_analytic_price": geom_analytic,
                "geometric_mc_price": geom_mc,
                "beta": beta,
                "raw_npv": raw_npv,
                "raw_std_error": raw_std,
                "variance_ratio": variance_ratio,
                "variance_reduction_factor": 1.0 / variance_ratio if variance_ratio > 0 else 0,
            }

            logger.info(
                f"Asian CV: raw={raw_npv:.6f}±{raw_std:.6f}, "
                f"adjusted={npv:.6f}±{std_err:.6f}, "
                f"variance_ratio={variance_ratio:.4f} "
                f"({1.0/variance_ratio:.0f}× reduction)"
            )
        else:
            # No control variate — use raw payoffs
            if average_type == AverageType.GEOMETRIC:
                npv = float(np.mean(geom_payoffs))
                std_err = float(np.std(geom_payoffs) / np.sqrt(self.num_paths))
            else:
                npv = float(np.mean(arith_payoffs))
                std_err = float(np.std(arith_payoffs) / np.sqrt(self.num_paths))

        # Discount factors
        df = compute_discount_factors(mkt["rate"], mkt["T"], self.time_steps)

        elapsed = time.perf_counter() - t0

        self.last_result = MCResult(
            metadata={
                "engine": "MCAsianEngine",
                "model": model.model_type().value,
                "underlying": underlying,
                "strike": strike,
                "option_type": option_type.value,
                "average_type": average_type.value,
                "T": mkt["T"],
                "spot": mkt["spot"],
                "rate": mkt["rate"],
                "div_yield": mkt["div_yield"],
                "vol": mkt["vol"],
                "num_paths": self.num_paths,
                "time_steps": self.time_steps,
                "num_fixings": num_fixings,
                "seed": self.seed,
                "rng_type": rng.name(),
                "antithetic": self.antithetic,
                "geometric_control_variate": cv_diagnostics,
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
            f"MC Asian diagnostics: NPV={npv:.6f} ± {std_err:.6f}, "
            f"{num_fixings} fixings, {self.num_paths} paths, {elapsed:.3f}s"
        )