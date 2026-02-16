"""
Analytic pricing engines for equity instruments.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

import QuantLib as ql

from core.enums.definitions import EngineType, InstrumentType, ModelType
from core.exceptions.errors import EngineError, IncompatibleEngineError
from core.interfaces.base import BaseEngine, BaseModel, MarketEnvironment
from registry import engine_registry


@engine_registry.register_decorator((InstrumentType.VANILLA_OPTION.value, EngineType.ANALYTIC.value))
@dataclass
class AnalyticBSMEngine(BaseEngine):
    """Analytic Black-Scholes-Merton engine for European vanilla options."""

    def engine_type(self) -> EngineType:
        return EngineType.ANALYTIC

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.VANILLA_OPTION]

    def supported_models(self) -> List[ModelType]:
        return [ModelType.BLACK_SCHOLES]

    def build(
        self,
        model: BaseModel,
        market_env: MarketEnvironment,
        **kwargs,
    ) -> ql.PricingEngine:
        if model.model_type() != ModelType.BLACK_SCHOLES:
            raise IncompatibleEngineError(
                f"AnalyticBSMEngine requires BLACK_SCHOLES model, got {model.model_type()}"
            )
        process = model.build_process(market_env)
        return ql.AnalyticEuropeanEngine(process)


@engine_registry.register_decorator((InstrumentType.VANILLA_OPTION.value, EngineType.MONTE_CARLO.value))
@dataclass
class MCBSMEngine(BaseEngine):
    """Monte Carlo engine for vanilla options under BSM."""

    num_paths: int = 100_000
    time_steps: int = 252
    seed: int = 42

    def engine_type(self) -> EngineType:
        return EngineType.MONTE_CARLO

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.VANILLA_OPTION, InstrumentType.BARRIER_OPTION, InstrumentType.ASIAN_OPTION]

    def supported_models(self) -> List[ModelType]:
        return [ModelType.BLACK_SCHOLES, ModelType.HESTON]

    def build(
        self,
        model: BaseModel,
        market_env: MarketEnvironment,
        **kwargs,
    ) -> ql.PricingEngine:
        process = model.build_process(market_env)

        if model.model_type() == ModelType.BLACK_SCHOLES:
            return ql.MCEuropeanEngine(
                process, "pseudorandom",
                timeSteps=self.time_steps,
                requiredSamples=self.num_paths,
                seed=self.seed,
            )
        elif model.model_type() == ModelType.HESTON:
            return ql.MCEuropeanHestonEngine(
                process, "pseudorandom",
                timeSteps=self.time_steps,
                requiredSamples=self.num_paths,
                seed=self.seed,
            )
        else:
            raise IncompatibleEngineError(
                f"MCBSMEngine does not support model {model.model_type()}"
            )


@engine_registry.register_decorator((InstrumentType.VANILLA_OPTION.value, "heston_analytic"))
@dataclass
class AnalyticHestonEngine(BaseEngine):
    """Analytic Heston engine for European vanilla options."""

    def engine_type(self) -> EngineType:
        return EngineType.ANALYTIC

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.VANILLA_OPTION]

    def supported_models(self) -> List[ModelType]:
        return [ModelType.HESTON]

    def build(
        self,
        model: BaseModel,
        market_env: MarketEnvironment,
        **kwargs,
    ) -> ql.PricingEngine:
        if model.model_type() != ModelType.HESTON:
            raise IncompatibleEngineError(
                f"AnalyticHestonEngine requires HESTON model, got {model.model_type()}"
            )
        process = model.build_process(market_env)
        ql_model = ql.HestonModel(process)
        return ql.AnalyticHestonEngine(ql_model)


@engine_registry.register_decorator((InstrumentType.BARRIER_OPTION.value, EngineType.ANALYTIC.value))
@dataclass
class AnalyticBarrierEngine(BaseEngine):
    """Analytic engine for barrier options under BSM."""

    def engine_type(self) -> EngineType:
        return EngineType.ANALYTIC

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.BARRIER_OPTION]

    def supported_models(self) -> List[ModelType]:
        return [ModelType.BLACK_SCHOLES]

    def build(
        self,
        model: BaseModel,
        market_env: MarketEnvironment,
        **kwargs,
    ) -> ql.PricingEngine:
        process = model.build_process(market_env)
        return ql.AnalyticBarrierEngine(process)
