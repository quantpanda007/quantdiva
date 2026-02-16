"""
Analytic pricing engines for barrier and digital options.

Barrier (closed-form under BSM):
    Uses QuantLib's AnalyticBarrierEngine which implements the
    Reiner-Rubinstein closed-form solution for European barriers.

Digital (closed-form under BSM):
    Uses QuantLib's AnalyticEuropeanEngine — works because QuantLib
    models digitals as VanillaOption with CashOrNothing/AssetOrNothing
    payoff, and the analytic engine handles these payoff types natively.

Both are European exercise only.

Usage:
    from engines.analytic.barrier_digital_engine import (
        AnalyticBarrierEngine,
        AnalyticDigitalEngine,
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import QuantLib as ql

from core.enums.definitions import EngineType, InstrumentType, ModelType
from core.exceptions.errors import IncompatibleEngineError
from core.interfaces.base import BaseEngine, BaseInstrument, BaseModel, MarketEnvironment
from registry import engine_registry


# ---------------------------------------------------------------------------
# Analytic Barrier Engine
# ---------------------------------------------------------------------------

@engine_registry.register_decorator(
    (InstrumentType.BARRIER_OPTION.value, EngineType.ANALYTIC.value), overwrite=True
)
@dataclass
class AnalyticBarrierEngine(BaseEngine):
    """
    Closed-form barrier option engine under BSM.

    Implements the Reiner-Rubinstein analytical formulas for
    European barrier options (all 4 types: UpIn, UpOut, DownIn, DownOut).

    Provides analytic Greeks: delta, gamma, vega, theta, rho.

    Limitations:
    - European exercise only
    - BSM model only (flat vol, no smile)
    - Continuous barrier monitoring (not discrete)
    """

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
        instrument: BaseInstrument = None,
        **kwargs,
    ) -> ql.PricingEngine:
        if model.model_type() != ModelType.BLACK_SCHOLES:
            raise IncompatibleEngineError(
                f"AnalyticBarrierEngine requires BLACK_SCHOLES model, "
                f"got {model.model_type()}"
            )
        process = model.build_process(market_env)
        return ql.AnalyticBarrierEngine(process)


# ---------------------------------------------------------------------------
# Analytic Digital Engine
# ---------------------------------------------------------------------------

@engine_registry.register_decorator(
    ("digital_option", EngineType.ANALYTIC.value), overwrite=True
)
@dataclass
class AnalyticDigitalEngine(BaseEngine):
    """
    Closed-form digital option engine under BSM.

    QuantLib's AnalyticEuropeanEngine natively supports
    CashOrNothingPayoff and AssetOrNothingPayoff, so we
    simply wire the standard analytic engine.

    Cash-or-Nothing Call: Q * exp(-rT) * N(d2)
    Cash-or-Nothing Put:  Q * exp(-rT) * N(-d2)
    Asset-or-Nothing Call: S * exp(-qT) * N(d1)
    Asset-or-Nothing Put:  S * exp(-qT) * N(-d1)

    Limitations:
    - European exercise only
    - BSM model only
    """

    def engine_type(self) -> EngineType:
        return EngineType.ANALYTIC

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.DIGITAL_OPTION]

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
                f"AnalyticDigitalEngine requires BLACK_SCHOLES model, "
                f"got {model.model_type()}"
            )
        process = model.build_process(market_env)
        return ql.AnalyticEuropeanEngine(process)