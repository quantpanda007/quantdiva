"""
Pricing dispatch service.

This is the central orchestrator that wires:
  Instrument + Model + Engine + MarketData → PricingResult

It uses the registry to dynamically resolve the correct components.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import registry.bootstrap  # noqa: F401

import QuantLib as ql

from core.enums.definitions import EngineType, InstrumentType, ModelType, RiskMeasure
from core.exceptions.errors import (
    DispatchError,
    EngineNotFoundError,
    PricingError,
)
from core.interfaces.base import (
    BaseEngine,
    BaseInstrument,
    BaseModel,
    MarketEnvironment,
)
from core.types.value_objects import PricingDate, PricingResult, RiskResult
from registry import (
    PricerConfig,
    engine_registry,
    model_registry,
    pricer_config_registry,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default Pricer Configs
# ---------------------------------------------------------------------------

_DEFAULTS = [
    PricerConfig("vanilla_option", "black_scholes", "analytic"),
    PricerConfig("barrier_option", "black_scholes", "analytic"),
    PricerConfig("asian_option", "black_scholes", "monte_carlo",
                 engine_params={"num_paths": 100_000}),
]

for cfg in _DEFAULTS:
    if not pricer_config_registry.has(cfg.instrument_type):
        pricer_config_registry.register(cfg.instrument_type, cfg)


# ---------------------------------------------------------------------------
# Pricing Service
# ---------------------------------------------------------------------------

@dataclass
class PricingService:
    """
    Orchestrates pricing for any instrument.

    Usage:
        service = PricingService()
        result = service.price(instrument, market_env)
        result = service.price(instrument, market_env, model_type="heston", engine_type="monte_carlo")
    """

    def price(
        self,
        instrument: BaseInstrument,
        market_env: MarketEnvironment,
        model_type: Optional[str] = None,
        engine_type: Optional[str] = None,
        engine_params: Optional[Dict[str, Any]] = None,
    ) -> PricingResult:
        """
        Price a single instrument.

        If model_type/engine_type not specified, looks up defaults
        from the pricer_config_registry.
        """
        t0 = time.perf_counter()
        inst_type = instrument.instrument_type().value

        # Resolve configuration
        if model_type is None or engine_type is None:
            config = pricer_config_registry.get_or_none(inst_type)
            if config is None:
                raise DispatchError(
                    f"No default pricer config for instrument type '{inst_type}'. "
                    f"Provide model_type and engine_type explicitly."
                )
            model_type = model_type or config.model_type
            engine_type = engine_type or config.engine_type
            engine_params = engine_params or config.engine_params

        logger.info(
            f"Pricing {instrument.trade_id()} | "
            f"instrument={inst_type}, model={model_type}, engine={engine_type}"
        )

        try:
            # 1. Set evaluation date
            market_env.set_evaluation_date()

            # 2. Build model
            ModelClass = model_registry.get(model_type)
            model: BaseModel = self._build_model(ModelClass, instrument, engine_params or {})

            # 3. Build engine
            engine_key = (inst_type, engine_type)
            EngineClass = engine_registry.get(engine_key)
            engine_instance: BaseEngine = self._build_engine(EngineClass, engine_params or {})
            ql_engine = engine_instance.build(model, market_env, instrument=instrument)

            # Store engine instance for diagnostics access
            self._last_engine_instance = engine_instance

            # 4. Build QuantLib instrument
            ql_instrument = instrument.build(market_env)

            # Set pricing engine (some instruments like FRA compute
            # NPV directly from their curves and don't need an engine)
            try:
                ql_instrument.setPricingEngine(ql_engine)
            except (AttributeError, RuntimeError):
                # FRA and similar instruments price via their index curve
                pass

            # 5. Extract results
            npv = ql_instrument.NPV()
            elapsed = time.perf_counter() - t0

            result = PricingResult(
                trade_id=instrument.trade_id(),
                npv=npv,
                currency=instrument.currency(),
                pricing_date=market_env.pricing_date,
                engine_used=engine_type,
                model_used=model_type,
                diagnostics={"elapsed_seconds": round(elapsed, 6)},
            )

            # Attach MC diagnostics if available
            if hasattr(engine_instance, "last_result") and engine_instance.last_result is not None:
                mc_result = engine_instance.last_result
                if hasattr(mc_result, "std_error"):
                    result.diagnostics["mc_std_error"] = mc_result.std_error
                if hasattr(mc_result, "confidence_interval"):
                    result.diagnostics["mc_confidence_interval"] = mc_result.confidence_interval

            # Attach FD diagnostics if available
            try:
                from engines.finite_difference.fd_result import FDResult as _FDResult
                if hasattr(engine_instance, "last_result") and isinstance(engine_instance.last_result, _FDResult):
                    fd_result = engine_instance.last_result
                    result.diagnostics["fd_scheme"] = fd_result.scheme
                    result.diagnostics["fd_grid"] = f"{fd_result.time_steps}×{fd_result.spot_steps}"
                    result.diagnostics["fd_greeks"] = fd_result.greeks
                    if fd_result.convergence_data:
                        result.diagnostics["fd_convergence"] = fd_result.convergence_data
                    result.diagnostics["fd_result_ref"] = fd_result
            except ImportError:
                pass

            logger.info(
                f"Priced {instrument.trade_id()}: NPV={npv:.6f} "
                f"({elapsed:.4f}s)"
            )
            return result

        except Exception as e:
            raise PricingError(
                f"Failed to price {instrument.trade_id()}: {e}"
            ) from e

    def price_batch(
        self,
        instruments: List[BaseInstrument],
        market_env: MarketEnvironment,
        **kwargs,
    ) -> List[PricingResult]:
        """Price a batch of instruments. Returns results in same order."""
        results = []
        market_env.set_evaluation_date()

        for inst in instruments:
            try:
                result = self.price(inst, market_env, **kwargs)
                results.append(result)
            except PricingError as e:
                logger.error(f"Batch pricing error for {inst.trade_id()}: {e}")
                results.append(PricingResult(
                    trade_id=inst.trade_id(),
                    npv=float("nan"),
                    currency=inst.currency(),
                    pricing_date=market_env.pricing_date,
                    diagnostics={"error": str(e)},
                ))
        return results

    def compute_greeks(
        self,
        instrument: BaseInstrument,
        market_env: MarketEnvironment,
        measures: Optional[List[RiskMeasure]] = None,
        bump_size: float = 0.01,
        **kwargs,
    ) -> RiskResult:
        """
        Compute Greeks via bump-and-reprice.

        For analytic Greeks where available, uses QuantLib's built-in.
        Falls back to finite difference bumping.
        """
        if measures is None:
            measures = [RiskMeasure.DELTA, RiskMeasure.GAMMA, RiskMeasure.VEGA, RiskMeasure.THETA]

        base_result = self.price(instrument, market_env, **kwargs)
        greeks = {}

        # Try QuantLib's built-in Greeks first
        try:
            market_env.set_evaluation_date()

            ModelClass = model_registry.get(kwargs.get("model_type", "black_scholes"))
            model = self._build_model(ModelClass, instrument, {})
            EngineClass = engine_registry.get((
                instrument.instrument_type().value,
                kwargs.get("engine_type", "analytic"),
            ))
            engine_instance = self._build_engine(EngineClass, {})
            ql_engine = engine_instance.build(model, market_env)
            ql_inst = instrument.build(market_env)
            try:
                ql_inst.setPricingEngine(ql_engine)
            except (AttributeError, RuntimeError):
                pass

            if RiskMeasure.DELTA in measures:
                try:
                    greeks["delta"] = ql_inst.delta()
                except Exception:
                    greeks["delta"] = self._bump_greek(
                        instrument, market_env, "spot", bump_size, **kwargs
                    )

            if RiskMeasure.GAMMA in measures:
                try:
                    greeks["gamma"] = ql_inst.gamma()
                except Exception:
                    greeks["gamma"] = self._bump_greek_second_order(
                        instrument, market_env, "spot", bump_size, **kwargs
                    )

            if RiskMeasure.VEGA in measures:
                try:
                    greeks["vega"] = ql_inst.vega()
                except Exception:
                    greeks["vega"] = self._bump_greek(
                        instrument, market_env, "vol", bump_size, **kwargs
                    )

            if RiskMeasure.THETA in measures:
                try:
                    greeks["theta"] = ql_inst.theta()
                except Exception:
                    greeks["theta"] = None

            if RiskMeasure.RHO in measures:
                try:
                    greeks["rho"] = ql_inst.rho()
                except Exception:
                    greeks["rho"] = self._bump_greek(
                        instrument, market_env, "rate", bump_size, **kwargs
                    )

        except Exception as e:
            logger.warning(f"Analytic Greeks failed, falling back to bump-and-reprice: {e}")

        return RiskResult(
            trade_id=instrument.trade_id(),
            greeks=greeks,
        )

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _build_model(
        self, ModelClass, instrument: BaseInstrument, params: dict
    ) -> BaseModel:
        """Instantiate a model, setting underlying from instrument if needed."""
        model = ModelClass()
        if hasattr(model, "underlying") and hasattr(instrument, "underlying"):
            model.underlying = instrument.underlying
        return model

    def _build_engine(self, EngineClass, params: dict) -> BaseEngine:
        """
        Instantiate an engine with optional parameters.

        Special handling for Finite Difference engines:
        maps engine_params → FDGridConfig.
        """
        if not params:
            return EngineClass()

        # --- FD engine special wiring ---
        try:
            from engines.finite_difference.fd_config import FDGridConfig

            if hasattr(EngineClass, "__name__") and "FD" in EngineClass.__name__:
                grid_config = FDGridConfig(
                    time_steps=params.get("time_steps", 200),
                    spot_steps=params.get("spot_steps", 400),
                    vol_steps=params.get("vol_steps", 50),
                    damping_steps=params.get("damping_steps", 0),
                )
                # Pass through scheme if provided
                if "scheme" in params:
                    grid_config.scheme = params["scheme"]
                # Pass through spot grid bounds if provided
                if "spot_min_factor" in params:
                    grid_config.spot_min_factor = params["spot_min_factor"]
                if "spot_max_factor" in params:
                    grid_config.spot_max_factor = params["spot_max_factor"]

                # Build engine with grid config and optional flags
                engine_kwargs = {"grid_config": grid_config}
                if "run_convergence" in params:
                    engine_kwargs["run_convergence"] = params["run_convergence"]
                if "extract_greeks" in params:
                    engine_kwargs["extract_greeks"] = params["extract_greeks"]

                return EngineClass(**engine_kwargs)
        except ImportError:
            pass

        # --- Default construction: pass matching params ---
        return EngineClass(**{k: v for k, v in params.items() if hasattr(EngineClass, k)})

    def _bump_greek(
        self,
        instrument: BaseInstrument,
        market_env: MarketEnvironment,
        risk_factor: str,
        bump_size: float,
        **kwargs,
    ) -> Optional[float]:
        """First-order finite difference Greek via bump-and-reprice."""
        from services.greeks.bump_reprice import BumpAndRepriceGreeks

        greeks_svc = BumpAndRepriceGreeks(pricing_service=self)
        result = greeks_svc.compute(
            instrument=instrument,
            market_env=market_env,
            model_type=kwargs.get("model_type", "black_scholes"),
            engine_type=kwargs.get("engine_type", "analytic"),
            engine_params=kwargs.get("engine_params"),
            measures=[risk_factor],
        )
        return result.greeks.get(risk_factor)

    def _bump_greek_second_order(
        self,
        instrument: BaseInstrument,
        market_env: MarketEnvironment,
        risk_factor: str,
        bump_size: float,
        **kwargs,
    ) -> Optional[float]:
        """Second-order finite difference Greek via bump-and-reprice."""
        from services.greeks.bump_reprice import BumpAndRepriceGreeks

        greeks_svc = BumpAndRepriceGreeks(pricing_service=self)
        result = greeks_svc.compute(
            instrument=instrument,
            market_env=market_env,
            model_type=kwargs.get("model_type", "black_scholes"),
            engine_type=kwargs.get("engine_type", "analytic"),
            engine_params=kwargs.get("engine_params"),
            measures=["gamma"] if risk_factor == "spot" else [risk_factor],
        )
        return result.greeks.get("gamma" if risk_factor == "spot" else risk_factor)
