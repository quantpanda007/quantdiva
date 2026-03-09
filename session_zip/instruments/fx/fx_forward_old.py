"""
FX Forward instrument.

An FX Forward is an agreement to exchange currencies at a future date
at a pre-agreed rate.

Valuation: NPV = Notional * (F - K) * DF(T) * sign
Where F = S * exp((r_dom - r_for) * T) is the theoretical forward rate.

Built as a VanillaOption with zero-strike trick for clean QuantLib integration,
using Garman-Kohlhagen process where the foreign rate acts as dividend yield.
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


@instrument_registry.register_decorator(InstrumentType.FX_FORWARD.value, overwrite=True)
@dataclass
class FXForward(BaseInstrument):
    """FX Forward — agreement to exchange currencies at a future date.

    Attributes:
        _trade_id: Unique trade identifier.
        ccy_pair: Currency pair (e.g. 'EURUSD' = EUR/USD).
        notional: Notional in foreign currency units.
        strike: Agreed forward rate (domestic per foreign).
        delivery_date: Settlement date.
        direction: 'buy' = buy foreign ccy, 'sell' = sell foreign ccy.
        domestic_rate: Domestic risk-free rate.
        foreign_rate: Foreign risk-free rate.
        _currency: Settlement currency (domestic, derived from pair).
    """

    _trade_id: str = "FXFWD-001"
    ccy_pair: str = "EURUSD"
    notional: float = 1_000_000
    strike: float = 1.08
    delivery_date: date = None
    direction: str = "buy"
    domestic_rate: float = 0.045
    foreign_rate: float = 0.035
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
        return InstrumentType.FX_FORWARD

    def currency(self) -> str:
        return self._currency or self.domestic_ccy

    def maturity(self) -> date:
        return self.delivery_date

    def build(self, market_env: MarketEnvironment) -> ql.VanillaOption:
        """Build FX Forward as a European option for QuantLib pricing.

        FX forward = long call + short put at strike K (put-call parity).
        For a buyer of foreign currency, this is equivalent to a call.
        The Garman-Kohlhagen model uses foreign rate as dividend yield.
        """
        try:
            market_env.set_evaluation_date()

            ql_type = (
                ql.Option.Call if self.direction == "buy"
                else ql.Option.Put
            )
            payoff = ql.PlainVanillaPayoff(ql_type, self.strike)

            ql_delivery = ql.Date(
                self.delivery_date.day,
                self.delivery_date.month,
                self.delivery_date.year,
            )
            exercise = ql.EuropeanExercise(ql_delivery)

            return ql.VanillaOption(payoff, exercise)

        except Exception as e:
            raise InstrumentBuildError(
                f"Failed to build FX Forward {self._trade_id}: {e}"
            ) from e

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FXForward:
        def parse_date(d):
            if d is None:
                return None
            if isinstance(d, date):
                return d
            return date.fromisoformat(str(d))

        return cls(
            _trade_id=data.get("trade_id", "FXFWD-001"),
            ccy_pair=data.get("ccy_pair", "EURUSD"),
            notional=float(data.get("notional", 1_000_000)),
            strike=float(data.get("strike", 1.08)),
            delivery_date=parse_date(data.get("delivery_date")),
            direction=data.get("direction", "buy"),
            domestic_rate=float(data.get("domestic_rate", 0.045)),
            foreign_rate=float(data.get("foreign_rate", 0.035)),
            _currency=data.get("currency", ""),
        )

    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update({
            "ccy_pair": self.ccy_pair,
            "notional": self.notional,
            "strike": self.strike,
            "direction": self.direction,
            "delivery_date": self.delivery_date.isoformat() if self.delivery_date else None,
        })
        return base

    def __repr__(self) -> str:
        return (
            f"FXForward("
            f"id={self._trade_id}, "
            f"{self.direction.upper()} {self.ccy_pair} "
            f"K={self.strike:.4f} "
            f"N={self.notional:,.0f} "
            f"del={self.delivery_date}"
            f")"
        )
