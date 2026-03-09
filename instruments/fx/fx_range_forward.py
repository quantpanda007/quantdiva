"""
FX Range Forward instrument.

A range forward (also called collar or risk reversal) bounds the
effective exchange rate between two strikes:

  Exporter (sell foreign):
    - Long put at lower_strike (floor — protects downside)
    - Short call at upper_strike (cap — gives away upside)
    → Payoff bounded between [lower_strike, upper_strike]

  Importer (buy foreign):
    - Long call at upper_strike (cap — protects upside)
    - Short put at lower_strike (floor — gives away downside)
    → Payoff bounded between [lower_strike, upper_strike]

Pricing: each leg is a ql.VanillaOption priced via Garman-Kohlhagen
(BSM with foreign rate as dividend). Unlike a vanilla forward, this
requires vol (non-linear payoff) and uses the engine framework.

NPV = Notional × (NPV_long_leg - NPV_short_leg)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Optional

import QuantLib as ql

from core.enums.definitions import AssetClass, InstrumentType
from core.exceptions.errors import InstrumentBuildError
from core.interfaces.base import BaseInstrument, MarketEnvironment
from core.types.value_objects import PricingDate, TradeId
from registry import instrument_registry, engine_registry


# ---------------------------------------------------------------------------
# Two-leg composite instrument wrapper
# ---------------------------------------------------------------------------

class CompositeOptionInstrument:
    """
    Wraps two ql.VanillaOption legs into a single instrument interface.

    The PricingService calls setPricingEngine() and NPV() on this object.
    We forward the engine to both legs and combine their NPVs.
    """

    def __init__(
        self,
        long_leg: ql.VanillaOption,
        short_leg: ql.VanillaOption,
        notional: float = 1.0,
    ):
        self.long_leg = long_leg
        self.short_leg = short_leg
        self.notional = notional
        self._engine = None

    def setPricingEngine(self, engine):
        """Attach the same pricing engine to both legs."""
        self._engine = engine
        self.long_leg.setPricingEngine(engine)
        self.short_leg.setPricingEngine(engine)

    def NPV(self) -> float:
        """
        Combined NPV = Notional × (long_leg_NPV - short_leg_NPV).

        Long leg NPV is positive (we own it), short leg NPV is negative
        (we sold it), so we subtract to get net value.
        """
        return self.notional * (self.long_leg.NPV() - self.short_leg.NPV())

    def isExpired(self) -> bool:
        return self.long_leg.isExpired()


# ---------------------------------------------------------------------------
# FX Range Forward
# ---------------------------------------------------------------------------

# Register with string directly (add FX_RANGE_FORWARD to InstrumentType enum
# if not already present, or use string registration)
try:
    _RF_TYPE = InstrumentType.FX_RANGE_FORWARD.value
except AttributeError:
    _RF_TYPE = "fx_range_forward"


@instrument_registry.register_decorator(_RF_TYPE)
@dataclass
class FXRangeForward(BaseInstrument):
    """
    FX Range Forward — bounded forward via put + call combination.

    Attributes:
        lower_strike: Floor rate (put strike for exporter)
        upper_strike: Cap rate (call strike for exporter)
        direction: 'exporter' (sell foreign) or 'importer' (buy foreign)
    """

    _trade_id: str = "RF-001"
    ccy_pair: str = "USDINR"
    lower_strike: float = 84.0
    upper_strike: float = 88.0
    expiry: date = None
    notional: float = 1_000_000.0
    direction: str = "exporter"  # exporter = sell foreign, importer = buy foreign
    _currency: str = ""

    def __post_init__(self):
        if not self._currency and len(self.ccy_pair) >= 6:
            self._currency = self.ccy_pair[3:6]
        if self.lower_strike >= self.upper_strike:
            raise ValueError(
                f"lower_strike ({self.lower_strike}) must be < "
                f"upper_strike ({self.upper_strike})"
            )

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
        try:
            return InstrumentType.FX_RANGE_FORWARD
        except AttributeError:
            return InstrumentType.FX_OPTION  # fallback for enum compat

    def currency(self) -> str:
        return self._currency or self.domestic_ccy

    def maturity(self) -> date:
        return self.expiry

    def build(self, market_env: MarketEnvironment) -> CompositeOptionInstrument:
        """
        Build two-leg range forward.

        Exporter (sell foreign currency):
          - Long put  at lower_strike (floor protection)
          - Short call at upper_strike (cap — sold upside)
          NPV = Notional × (put_NPV - call_NPV)

        Importer (buy foreign currency):
          - Long call  at upper_strike (cap protection)
          - Short put  at lower_strike (floor — sold downside)
          NPV = Notional × (call_NPV - put_NPV)
        """
        try:
            market_env.set_evaluation_date()

            if self.expiry is None:
                raise InstrumentBuildError("Expiry date is required")

            ql_expiry = ql.Date(self.expiry.day, self.expiry.month, self.expiry.year)
            exercise = ql.EuropeanExercise(ql_expiry)

            # Build the two option legs
            put_payoff = ql.PlainVanillaPayoff(ql.Option.Put, self.lower_strike)
            call_payoff = ql.PlainVanillaPayoff(ql.Option.Call, self.upper_strike)

            put_option = ql.VanillaOption(put_payoff, exercise)
            call_option = ql.VanillaOption(call_payoff, exercise)

            # Determine which is long and which is short
            is_exporter = self.direction.lower() in ("exporter", "sell", "short")

            if is_exporter:
                # Exporter: long put (floor), short call (cap)
                long_leg = put_option
                short_leg = call_option
            else:
                # Importer: long call (cap), short put (floor)
                long_leg = call_option
                short_leg = put_option

            return CompositeOptionInstrument(
                long_leg=long_leg,
                short_leg=short_leg,
                notional=self.notional,
            )

        except InstrumentBuildError:
            raise
        except Exception as e:
            raise InstrumentBuildError(
                f"Failed to build FX Range Forward {self._trade_id}: {e}"
            ) from e

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FXRangeForward":
        """Build from API params dict."""
        def parse_date(d):
            if d is None:
                return None
            if isinstance(d, date):
                return d
            return date.fromisoformat(str(d))

        return cls(
            _trade_id=data.get("trade_id", "RF-001"),
            ccy_pair=data.get("ccy_pair", "USDINR"),
            lower_strike=float(data.get("lower_strike", 84.0)),
            upper_strike=float(data.get("upper_strike", 88.0)),
            expiry=parse_date(data.get("expiry")),
            notional=float(data.get("notional", 1_000_000)),
            direction=data.get("direction", "exporter"),
            _currency=data.get("currency", ""),
        )

    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update({
            "ccy_pair": self.ccy_pair,
            "lower_strike": self.lower_strike,
            "upper_strike": self.upper_strike,
            "notional": self.notional,
            "direction": self.direction,
        })
        return base

    def __repr__(self) -> str:
        return (
            f"FXRangeForward("
            f"id={self._trade_id}, "
            f"{self.direction.upper()} {self.ccy_pair} "
            f"[{self.lower_strike:.4f} - {self.upper_strike:.4f}] "
            f"exp={self.expiry} "
            f"N={self.notional:,.0f}"
            f")"
        )


# ---------------------------------------------------------------------------
# Engine registration — reuse FX option analytic engine for range forward
# ---------------------------------------------------------------------------

# The range forward builds ql.VanillaOption legs, which are priced by the
# same analytic engine used for FX options. Register the same engine class
# under the range forward's key.

def _register_range_forward_engine():
    """Register fx_range_forward with the same engine as fx_option."""
    fx_option_key = (InstrumentType.FX_OPTION.value, "analytic")
    try:
        EngineClass = engine_registry.get(fx_option_key)
        engine_registry.register((_RF_TYPE, "analytic"), EngineClass, overwrite=True)
    except Exception:
        # Engine not yet registered (bootstrap order), will be handled at runtime
        pass


# Run at import time (after bootstrap loads engines)
try:
    _register_range_forward_engine()
except Exception:
    pass