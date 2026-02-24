"""
FX Vanilla Option (Garman-Kohlhagen).

An FX option gives the holder the right to exchange currencies at
a pre-agreed rate (strike) on the expiry date.

Pricing: Garman-Kohlhagen = Black-Scholes with foreign rate as dividend.
- Domestic rate = risk-free rate
- Foreign rate = dividend yield (cost of carry for foreign currency)
- Spot = price of 1 unit of foreign ccy in domestic ccy
- Vol = implied vol of the ccy pair

Convention: EURUSD = price of 1 EUR in USD
  - Call = right to buy EUR, pay USD (bullish EUR)
  - Put = right to sell EUR, receive USD (bearish EUR)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Optional

import QuantLib as ql

from core.enums.definitions import AssetClass, InstrumentType
from core.exceptions.errors import InstrumentBuildError
from core.interfaces.base import BaseInstrument, MarketEnvironment
from core.types.value_objects import PricingDate, TradeId
from registry import instrument_registry


@instrument_registry.register_decorator(InstrumentType.FX_OPTION.value, overwrite=True)
@dataclass
class FXVanillaOption(BaseInstrument):
    """FX Vanilla Option (European) — Garman-Kohlhagen.

    Attributes:
        _trade_id: Unique trade identifier.
        ccy_pair: Currency pair (e.g. 'EURUSD').
        notional: Notional in foreign currency.
        strike: Option strike rate.
        expiry: Option expiry date.
        option_type: 'call' or 'put'.
        domestic_rate: Domestic risk-free rate.
        foreign_rate: Foreign risk-free rate (acts as dividend).
        vol: FX implied volatility.
        _currency: Settlement currency (domestic).
    """

    _trade_id: str = "FXOPT-001"
    ccy_pair: str = "EURUSD"
    notional: float = 1_000_000
    strike: float = 1.08
    expiry: date = None
    option_type: str = "call"
    domestic_rate: float = 0.045
    foreign_rate: float = 0.035
    vol: float = 0.08
    _currency: str = ""

    def __post_init__(self):
        if not self._currency and len(self.ccy_pair) >= 6:
            self._currency = self.ccy_pair[3:6]

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
        """Build as QuantLib VanillaOption.

        The Garman-Kohlhagen model is implemented by setting up a BSM
        process where the foreign rate is the dividend yield. This is
        handled by the engine, not the instrument.
        """
        try:
            market_env.set_evaluation_date()

            ql_type = (
                ql.Option.Call if self.option_type == "call"
                else ql.Option.Put
            )
            payoff = ql.PlainVanillaPayoff(ql_type, self.strike)

            ql_expiry = ql.Date(
                self.expiry.day, self.expiry.month, self.expiry.year
            )
            exercise = ql.EuropeanExercise(ql_expiry)

            return ql.VanillaOption(payoff, exercise)

        except Exception as e:
            raise InstrumentBuildError(
                f"Failed to build FX Option {self._trade_id}: {e}"
            ) from e

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FXVanillaOption:
        def parse_date(d):
            if d is None:
                return None
            if isinstance(d, date):
                return d
            return date.fromisoformat(str(d))

        return cls(
            _trade_id=data.get("trade_id", "FXOPT-001"),
            ccy_pair=data.get("ccy_pair", "EURUSD"),
            notional=float(data.get("notional", 1_000_000)),
            strike=float(data.get("strike", 1.08)),
            expiry=parse_date(data.get("expiry")),
            option_type=data.get("option_type", "call"),
            domestic_rate=float(data.get("domestic_rate", 0.045)),
            foreign_rate=float(data.get("foreign_rate", 0.035)),
            vol=float(data.get("vol", 0.08)),
            _currency=data.get("currency", ""),
        )

    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update({
            "ccy_pair": self.ccy_pair,
            "notional": self.notional,
            "strike": self.strike,
            "option_type": self.option_type,
            "expiry": self.expiry.isoformat() if self.expiry else None,
        })
        return base

    def __repr__(self) -> str:
        return (
            f"FXOption("
            f"id={self._trade_id}, "
            f"{self.option_type.upper()} {self.ccy_pair} "
            f"K={self.strike:.4f} "
            f"exp={self.expiry} "
            f"N={self.notional:,.0f}"
            f")"
        )
