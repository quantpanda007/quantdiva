"""
Credit pricing engines.

- MidPointCdsEngine: Standard CDS pricing via hazard rate curve.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import QuantLib as ql

from core.enums.definitions import EngineType, InstrumentType, ModelType
from core.interfaces.base import BaseEngine, BaseModel, MarketEnvironment
from registry import engine_registry


@engine_registry.register_decorator(
    (InstrumentType.CDS.value, "midpoint"), overwrite=True
)
@engine_registry.register_decorator(
    (InstrumentType.CDS.value, EngineType.ANALYTIC.value), overwrite=True
)
@dataclass
class MidPointCdsEngine(BaseEngine):
    """MidPoint CDS engine.

    Uses ql.MidPointCdsEngine which prices a CDS by integrating
    default probabilities from a hazard rate curve against the
    discount curve.

    The hazard rate is taken from the instrument's hazard_rate attribute,
    building a flat hazard rate curve.
    """

    def engine_type(self) -> EngineType:
        return EngineType.ANALYTIC

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.CDS]

    def supported_models(self) -> List[ModelType]:
        return [ModelType.BLACK_SCHOLES, ModelType.HAZARD_RATE]

    def build(
        self,
        model: BaseModel,
        market_env: MarketEnvironment,
        **kwargs,
    ) -> ql.PricingEngine:
        currency = kwargs.get("currency", "USD")

        # Discount curve
        curve = market_env.discount_curves.get(currency)
        if curve is None:
            if market_env.discount_curves:
                curve = list(market_env.discount_curves.values())[0]
            else:
                raise ValueError("No discount curve available for CDS pricing")

        # Build flat hazard rate curve from instrument
        instrument = kwargs.get("instrument")
        hazard_rate = 0.02  # default 2%
        recovery_rate = 0.40

        if instrument:
            if hasattr(instrument, "hazard_rate"):
                hazard_rate = instrument.hazard_rate
            if hasattr(instrument, "recovery_rate"):
                recovery_rate = instrument.recovery_rate

        eval_date = ql.Settings.instance().evaluationDate
        hazard_curve = ql.FlatHazardRate(
            eval_date,
            ql.QuoteHandle(ql.SimpleQuote(hazard_rate)),
            ql.Actual365Fixed(),
        )
        probability = ql.DefaultProbabilityTermStructureHandle(hazard_curve)

        return ql.MidPointCdsEngine(
            probability,
            recovery_rate,
            curve,
        )
