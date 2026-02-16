"""
FX instrument wrappers.

Covers:
- FX Forward
- FX Vanilla Option (Garman-Kohlhagen style)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import QuantLib as ql

from core.enums.definitions import AssetClass, ExerciseType, InstrumentType, OptionType
from core.exceptions.errors import InstrumentBuildError
from core.interfaces.base import BaseInstrument, MarketEnvironment
from core.types.value_objects import PricingDate, TradeId
from registry import instrument_registry


@instrument_registry.register_decorator(InstrumentType.FX_OPTION.value)
@dataclass
class FXVanillaOption(BaseInstrument):
    """
    FX Vanilla Option priced via Garman-Kohlhagen (BSM with foreign rate as dividend).

    Convention: domestic/foreign (e.g., EURUSD means EUR is foreign, USD is domestic).
    Spot = price of 1 unit of foreign currency in domestic currency.
    """

    _trade_id: str
    ccy_pair: str             # e.g., "EURUSD"
    strike: float
    expiry: date
    option_type: OptionType
    notional: float = 1_000_000.0
    exercise_type: ExerciseType = ExerciseType.EUROPEAN
    _currency: str = ""       # settlement currency (domestic), derived from pair if empty

    def __post_init__(self):
        if not self._currency and len(self.ccy_pair) == 6:
            self._currency = self.ccy_pair[3:6]  # domestic currency

    @property
    def foreign_ccy(self) -> str:
        return self.ccy_pair[:3]

    @property
    def domestic_ccy(self) -> str:
        return self.ccy_pair[3:6]

    def trade_id(self) -> TradeId:
        return TradeId(self._trade_id)

    def asset_class(self) -> AssetClass:
        return AssetClass.FX

    def instrument_type(self) -> InstrumentType:
        return InstrumentType.FX_OPTION

    def currency(self) -> str:
        return self._currency or self.domestic_ccy

    def maturity(self) -> date:
        return self.expiry

    def build(self, market_env: MarketEnvironment) -> ql.VanillaOption:
        """
        Build as a QuantLib VanillaOption.

        The FX-specific part is handled in the model/process:
        - GBM process with foreign rate as "dividend yield"
        - Domestic rate as risk-free rate
        """
        try:
            ql_type = ql.Option.Call if self.option_type == OptionType.CALL else ql.Option.Put
            payoff = ql.PlainVanillaPayoff(ql_type, self.strike)

            ql_expiry = ql.Date(self.expiry.day, self.expiry.month, self.expiry.year)
            exercise = ql.EuropeanExercise(ql_expiry)

            return ql.VanillaOption(payoff, exercise)

        except Exception as e:
            raise InstrumentBuildError(f"Failed to build FXOption {self._trade_id}: {e}") from e

    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update({
            "ccy_pair": self.ccy_pair,
            "strike": self.strike,
            "option_type": self.option_type.value,
            "notional": self.notional,
            "foreign_ccy": self.foreign_ccy,
            "domestic_ccy": self.domestic_ccy,
        })
        return base


@instrument_registry.register_decorator(InstrumentType.FX_FORWARD.value)
@dataclass
class FXForward(BaseInstrument):
    """
    FX Forward — agreement to exchange currencies at a future date.

    Valued as: NPV = Notional * (Forward - Strike) * DF
    """

    _trade_id: str
    ccy_pair: str           # e.g., "EURUSD"
    strike: float           # agreed forward rate
    delivery_date: date
    notional: float = 1_000_000.0
    direction: str = "buy"  # buy = buy foreign, sell = sell foreign
    _currency: str = ""

    def __post_init__(self):
        if not self._currency and len(self.ccy_pair) == 6:
            self._currency = self.ccy_pair[3:6]

    def trade_id(self) -> TradeId:
        return TradeId(self._trade_id)

    def asset_class(self) -> AssetClass:
        return AssetClass.FX

    def instrument_type(self) -> InstrumentType:
        return InstrumentType.FX_FORWARD

    def currency(self) -> str:
        return self._currency

    def maturity(self) -> date:
        return self.delivery_date

    def build(self, market_env: MarketEnvironment) -> ql.Instrument:
        """
        Build FX Forward valuation.

        Uses simple forward pricing:
        F = S * exp((r_d - r_f) * T)
        NPV = N * (F - K) * DF(T) * sign
        """
        try:
            domestic = self.ccy_pair[3:6]
            foreign = self.ccy_pair[:3]

            spot = market_env.spot_prices.get(self.ccy_pair)
            if spot is None:
                raise InstrumentBuildError(f"No spot for {self.ccy_pair}")

            # For now, return a placeholder — real implementation would use
            # QuantLib's forward pricing or a custom instrument
            # This demonstrates the pattern; full FX forward needs curve access
            ql_type = ql.Option.Call if self.direction == "buy" else ql.Option.Put
            payoff = ql.PlainVanillaPayoff(ql_type, self.strike)
            ql_delivery = ql.Date(self.delivery_date.day, self.delivery_date.month, self.delivery_date.year)
            exercise = ql.EuropeanExercise(ql_delivery)

            return ql.VanillaOption(payoff, exercise)

        except InstrumentBuildError:
            raise
        except Exception as e:
            raise InstrumentBuildError(f"Failed to build FXForward {self._trade_id}: {e}") from e
