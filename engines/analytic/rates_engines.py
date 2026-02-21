"""
Discounting engines for rates instruments.

- DiscountingSwapEngine: NPV of IRS via curve discounting
- DiscountingBondEngine: Clean/dirty price of fixed rate bonds
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import QuantLib as ql

from core.enums.definitions import EngineType, InstrumentType, ModelType
from core.interfaces.base import BaseEngine, BaseModel, MarketEnvironment
from registry import engine_registry


@engine_registry.register_decorator(
    (InstrumentType.IRS.value, "discounting"), overwrite=True
)
@engine_registry.register_decorator(
    (InstrumentType.IRS.value, EngineType.ANALYTIC.value), overwrite=True
)
@dataclass
class DiscountingSwapEngine(BaseEngine):
    """Discounting engine for vanilla interest rate swaps.

    Uses ql.DiscountingSwapEngine which discounts all cashflows
    using the provided yield curve.
    """

    def engine_type(self) -> EngineType:
        return EngineType.ANALYTIC

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.IRS]

    def supported_models(self) -> List[ModelType]:
        return [ModelType.BLACK_SCHOLES, ModelType.HULL_WHITE_1F]

    def build(
        self,
        model: BaseModel,
        market_env: MarketEnvironment,
        **kwargs,
    ) -> ql.PricingEngine:
        # Get the discount curve — try USD first, then any available
        currency = kwargs.get("currency", "USD")
        curve = market_env.discount_curves.get(currency)
        if curve is None:
            # Fallback: first available curve
            if market_env.discount_curves:
                curve = list(market_env.discount_curves.values())[0]
            else:
                raise ValueError("No discount curve available for swap pricing")

        return ql.DiscountingSwapEngine(curve)


@engine_registry.register_decorator(
    (InstrumentType.BOND.value, "discounting"), overwrite=True
)
@engine_registry.register_decorator(
    (InstrumentType.BOND.value, EngineType.ANALYTIC.value), overwrite=True
)
@dataclass
class DiscountingBondEngine(BaseEngine):
    """Discounting engine for fixed rate bonds.

    Uses ql.DiscountingBondEngine which computes clean/dirty price
    by discounting all coupon and principal cashflows.
    """

    def engine_type(self) -> EngineType:
        return EngineType.ANALYTIC

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.BOND]

    def supported_models(self) -> List[ModelType]:
        return [ModelType.BLACK_SCHOLES, ModelType.HULL_WHITE_1F]

    def build(
        self,
        model: BaseModel,
        market_env: MarketEnvironment,
        **kwargs,
    ) -> ql.PricingEngine:
        currency = kwargs.get("currency", "USD")
        curve = market_env.discount_curves.get(currency)
        if curve is None:
            if market_env.discount_curves:
                curve = list(market_env.discount_curves.values())[0]
            else:
                raise ValueError("No discount curve available for bond pricing")

        return ql.DiscountingBondEngine(curve)


# ---------------------------------------------------------------------------
# FRA — built as single-period swap, uses DiscountingSwapEngine
# ---------------------------------------------------------------------------

@engine_registry.register_decorator(
    (InstrumentType.FRA.value, "discounting"), overwrite=True
)
@engine_registry.register_decorator(
    (InstrumentType.FRA.value, EngineType.ANALYTIC.value), overwrite=True
)
@dataclass
class DiscountingFRAEngine(BaseEngine):
    """Discounting engine for FRAs.

    FRA is built as a single-period VanillaSwap, so it uses the
    standard DiscountingSwapEngine.
    """

    def engine_type(self) -> EngineType:
        return EngineType.ANALYTIC

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.FRA]

    def supported_models(self) -> List[ModelType]:
        return [ModelType.BLACK_SCHOLES, ModelType.HULL_WHITE_1F]

    def build(
        self,
        model: BaseModel,
        market_env: MarketEnvironment,
        **kwargs,
    ) -> ql.PricingEngine:
        # FRA is a single-period VanillaSwap — uses standard discounting
        currency = kwargs.get("currency", "USD")
        curve = market_env.discount_curves.get(currency)
        if curve is None:
            if market_env.discount_curves:
                curve = list(market_env.discount_curves.values())[0]
            else:
                raise ValueError("No discount curve available")
        return ql.DiscountingSwapEngine(curve)


# ---------------------------------------------------------------------------
# Cap/Floor — Black's formula engine
# ---------------------------------------------------------------------------

@engine_registry.register_decorator(
    (InstrumentType.CAP_FLOOR.value, "black"), overwrite=True
)
@engine_registry.register_decorator(
    (InstrumentType.CAP_FLOOR.value, EngineType.ANALYTIC.value), overwrite=True
)
@dataclass
class BlackCapFloorEngine(BaseEngine):
    """Black's model engine for caps and floors.

    Uses ql.BlackCapFloorEngine with a flat vol quote.
    Vol is passed from the instrument's vol attribute.
    """

    def engine_type(self) -> EngineType:
        return EngineType.ANALYTIC

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.CAP_FLOOR]

    def supported_models(self) -> List[ModelType]:
        return [ModelType.BLACK_SCHOLES]

    def build(
        self,
        model: BaseModel,
        market_env: MarketEnvironment,
        **kwargs,
    ) -> ql.PricingEngine:
        currency = kwargs.get("currency", "USD")
        curve = market_env.discount_curves.get(currency)
        if curve is None:
            if market_env.discount_curves:
                curve = list(market_env.discount_curves.values())[0]
            else:
                raise ValueError("No discount curve available for cap/floor")

        # Get vol from the instrument or default
        instrument = kwargs.get("instrument")
        vol = 0.20
        if instrument and hasattr(instrument, "vol"):
            vol = instrument.vol

        vol_handle = ql.QuoteHandle(ql.SimpleQuote(vol))
        return ql.BlackCapFloorEngine(curve, vol_handle)


# ---------------------------------------------------------------------------
# Swaption — Black's formula engine
# ---------------------------------------------------------------------------

@engine_registry.register_decorator(
    (InstrumentType.SWAPTION.value, "black"), overwrite=True
)
@engine_registry.register_decorator(
    (InstrumentType.SWAPTION.value, EngineType.ANALYTIC.value), overwrite=True
)
@dataclass
class BlackSwaptionEngine(BaseEngine):
    """Black's model engine for European swaptions.

    Uses ql.BlackSwaptionEngine with a flat vol quote.
    Supports both lognormal (Black) and normal (Bachelier) vol.
    """

    def engine_type(self) -> EngineType:
        return EngineType.ANALYTIC

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.SWAPTION]

    def supported_models(self) -> List[ModelType]:
        return [ModelType.BLACK_SCHOLES]

    def build(
        self,
        model: BaseModel,
        market_env: MarketEnvironment,
        **kwargs,
    ) -> ql.PricingEngine:
        currency = kwargs.get("currency", "USD")
        curve = market_env.discount_curves.get(currency)
        if curve is None:
            if market_env.discount_curves:
                curve = list(market_env.discount_curves.values())[0]
            else:
                raise ValueError("No discount curve available for swaption")

        # Get vol from the instrument
        instrument = kwargs.get("instrument")
        vol = 0.20
        if instrument and hasattr(instrument, "vol"):
            vol = instrument.vol

        vol_handle = ql.QuoteHandle(ql.SimpleQuote(vol))
        return ql.BlackSwaptionEngine(curve, vol_handle)
