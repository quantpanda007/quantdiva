"""
Analytic Black-Scholes-Merton engine — European options only.

This is the simplest and fastest engine. Uses closed-form BSM formula.
Only valid for European exercise.

Provides:
- AnalyticEuropeanEngine: BSM closed-form
- AnalyticHestonEngine: Semi-closed-form Heston
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import QuantLib as ql

from core.enums.definitions import EngineType, InstrumentType, ModelType
from core.exceptions.errors import IncompatibleEngineError
from core.interfaces.base import BaseEngine, BaseModel, MarketEnvironment
from registry import engine_registry


@engine_registry.register_decorator(
    (InstrumentType.VANILLA_OPTION.value, EngineType.ANALYTIC.value), overwrite=True
)
@dataclass
class AnalyticEuropeanEngine(BaseEngine):
    """
    Analytic BSM engine for European vanilla options.

    Uses ql.AnalyticEuropeanEngine which provides:
    - Exact NPV via Black-Scholes formula
    - Analytic Greeks: delta, gamma, vega, theta, rho, dividendRho
    - Fast: O(1) computation

    Limitations:
    - European exercise only
    - BSM model only (flat vol, lognormal)
    """

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
                f"AnalyticEuropeanEngine requires BLACK_SCHOLES model, "
                f"got {model.model_type()}"
            )
        process = model.build_process(market_env)
        return ql.AnalyticEuropeanEngine(process)


@engine_registry.register_decorator(
    (InstrumentType.VANILLA_OPTION.value, "heston_analytic"), overwrite=True
)
@dataclass
class AnalyticHestonEngine(BaseEngine):
    """
    Semi-closed-form Heston engine for European vanilla options.

    Uses Fourier transform / characteristic function approach.
    Handles volatility smile/skew.

    Limitations:
    - European exercise only
    - Heston model only
    """

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
                f"AnalyticHestonEngine requires HESTON model, "
                f"got {model.model_type()}"
            )
        process = model.build_process(market_env)
        ql_model = ql.HestonModel(process)
        return ql.AnalyticHestonEngine(ql_model)
