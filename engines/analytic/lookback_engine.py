"""
Analytic pricing engine for lookback options.

Uses QuantLib's closed-form engines for continuous monitoring:
- AnalyticContinuousFloatingLookbackEngine (Goldman-Sosin-Gatto)
- AnalyticContinuousFixedLookbackEngine (Conze-Viswanathan)

Both are European exercise, BSM model, continuous monitoring.
For discrete monitoring, use MCLookbackEngine.

Usage:
    from engines.analytic.lookback_engine import AnalyticLookbackEngine

    engine = AnalyticLookbackEngine()
    ql_engine = engine.build(model, market_env, instrument=lookback_opt)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import QuantLib as ql

from core.enums.definitions import EngineType, InstrumentType, ModelType
from core.exceptions.errors import IncompatibleEngineError
from core.interfaces.base import BaseEngine, BaseInstrument, BaseModel, MarketEnvironment
from registry import engine_registry


@engine_registry.register_decorator(
    ("lookback_option", EngineType.ANALYTIC.value), overwrite=True
)
@dataclass
class AnalyticLookbackEngine(BaseEngine):
    """
    Closed-form lookback engine under BSM.

    Automatically selects the correct QuantLib engine based on
    the instrument's strike type:
    - Floating strike → AnalyticContinuousFloatingLookbackEngine
    - Fixed strike    → AnalyticContinuousFixedLookbackEngine

    Assumes continuous barrier monitoring.
    European exercise only.
    """

    def engine_type(self) -> EngineType:
        return EngineType.ANALYTIC

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
                f"AnalyticLookbackEngine requires BLACK_SCHOLES, "
                f"got {model.model_type()}"
            )

        process = model.build_process(market_env)

        # Select engine based on strike type
        from instruments.equity.lookback_option import LookbackStrikeType

        strike_type = getattr(instrument, "strike_type", LookbackStrikeType.FLOATING)

        if strike_type == LookbackStrikeType.FLOATING:
            return ql.AnalyticContinuousFloatingLookbackEngine(process)
        else:
            return ql.AnalyticContinuousFixedLookbackEngine(process)