"""Discounting engine for the fresh IRS instrument (``"ois"``).

Registered as ``("ois", "discounting")``. It discounts on
``market_env.discount_curves[instrument.currency()]`` and fails if that curve is
missing; unlike the legacy ``("irs", ...)`` engine it never falls back to another
currency's curve. The model argument is accepted for the PricingService
interface and is not used.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import QuantLib as ql

from core.enums.definitions import EngineType, InstrumentType, ModelType
from core.interfaces.base import BaseEngine, BaseModel, MarketEnvironment
from instruments.rates.irs.pricing_instrument import FreshOISInstrument, MissingIRSCurve
from registry import engine_registry


@engine_registry.register_decorator((InstrumentType.OIS.value, "discounting"))
@dataclass
class FreshIRSDiscountingEngine(BaseEngine):
    """``ql.DiscountingSwapEngine`` on the instrument currency's discount curve."""

    def engine_type(self) -> EngineType:
        return EngineType.ANALYTIC

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.OIS]

    def supported_models(self) -> List[ModelType]:
        # "analytical" is registered as an alias of the Black-Scholes model class.
        return [ModelType.BLACK_SCHOLES]

    def build(
        self,
        model: BaseModel,
        market_env: MarketEnvironment,
        **kwargs,
    ) -> ql.PricingEngine:
        instrument = kwargs.get("instrument")
        if not isinstance(instrument, FreshOISInstrument):
            raise TypeError(
                "FreshIRSDiscountingEngine requires the FreshOISInstrument being priced "
                f"(got {type(instrument).__name__})"
            )
        currency = instrument.currency()
        curve = market_env.discount_curves.get(currency)
        if curve is None:
            raise MissingIRSCurve(
                f"no discount curve for {currency}; available: {sorted(market_env.discount_curves)}"
            )
        return ql.DiscountingSwapEngine(curve)
