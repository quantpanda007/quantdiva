"""
FX Forward instrument — analytical direct pricing.

Replaces the previous VanillaOption placeholder with proper forward math:
    F   = S × exp((r_d - r_f) × T)
    DF  = exp(-r_d × T)
    NPV = Notional × (F - K) × DF × sign

Returns NPV in domestic currency, already scaled by notional.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Optional

import QuantLib as ql

from core.enums.definitions import AssetClass, InstrumentType
from core.exceptions.errors import InstrumentBuildError
from core.interfaces.base import BaseInstrument, MarketEnvironment
from core.types.value_objects import PricingDate, TradeId
from registry import instrument_registry


# ---------------------------------------------------------------------------
# Helper: Lightweight instrument wrapper for analytical pricing
# ---------------------------------------------------------------------------

class AnalyticalInstrument:
    """
    Lightweight wrapper that holds a pre-computed NPV.

    Duck-types QuantLib's Instrument interface — exposes .NPV() so the
    PricingService can call it exactly like any QL instrument. No need
    to subclass ql.Instrument (which SWIG doesn't support).
    """

    def __init__(self, npv: float):
        self._npv = npv

    def isExpired(self):
        return False

    def NPV(self):
        return self._npv

    def setPricingEngine(self, engine):
        """No-op — analytical pricing doesn't need an engine."""
        pass


# ---------------------------------------------------------------------------
# FX Forward
# ---------------------------------------------------------------------------

@instrument_registry.register_decorator(InstrumentType.FX_FORWARD.value)
@dataclass
class FXForward(BaseInstrument):
    """
    FX Forward — agreement to exchange currencies at a future date.

    Analytical pricing:
        T   = year fraction to delivery
        F   = S × exp((r_d - r_f) × T)     # forward rate
        DF  = exp(-r_d × T)                  # domestic discount factor
        NPV = Notional × (F - K) × DF × sign

    where sign = +1 for buy (long foreign), -1 for sell (short foreign).
    """

    _trade_id: str
    ccy_pair: str           # e.g., "USDINR"
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
        Analytically price the FX Forward.

        Extracts domestic and foreign rates from MarketEnvironment curves,
        computes forward rate and discount factor, returns NPV scaled by
        notional and direction.
        """
        try:
            domestic = self.ccy_pair[3:6]
            foreign = self.ccy_pair[:3]

            # --- Spot ---
            spot = market_env.spot_prices.get(self.ccy_pair)
            if spot is None:
                raise InstrumentBuildError(f"No spot for {self.ccy_pair}")

            # --- Time to delivery ---
            pricing_date = market_env.pricing_date.value
            if self.delivery_date <= pricing_date:
                # Expired forward — NPV is zero
                return AnalyticalInstrument(0.0)

            day_count = ql.Actual365Fixed()
            ql_pricing = ql.Date(pricing_date.day, pricing_date.month, pricing_date.year)
            ql_delivery = ql.Date(self.delivery_date.day, self.delivery_date.month, self.delivery_date.year)
            T = day_count.yearFraction(ql_pricing, ql_delivery)

            if T <= 0:
                return AnalyticalInstrument(0.0)

            # --- Domestic rate (from discount curve) ---
            r_d = self._extract_rate(market_env, domestic, T)

            # --- Foreign rate ---
            r_f = self._extract_foreign_rate(market_env, foreign, self.ccy_pair, T)

            # --- Forward rate ---
            forward = spot * math.exp((r_d - r_f) * T)

            # --- Discount factor ---
            df = math.exp(-r_d * T)

            # --- Direction ---
            sign = 1.0 if self.direction.lower() in ("buy", "long") else -1.0

            # --- NPV ---
            npv = self.notional * (forward - self.strike) * df * sign

            return AnalyticalInstrument(npv)

        except InstrumentBuildError:
            raise
        except Exception as e:
            raise InstrumentBuildError(
                f"Failed to build FXForward {self._trade_id}: {e}"
            ) from e

    def _extract_rate(self, market_env: MarketEnvironment, currency: str, T: float) -> float:
        """Extract continuously compounded rate from discount curve."""
        for key in [currency, currency.upper()]:
            if key in market_env.discount_curves:
                handle = market_env.discount_curves[key]
                return handle.zeroRate(T, ql.Continuous, ql.Annual).rate()

        # Fall back to "USD" or first available
        if "USD" in market_env.discount_curves:
            handle = market_env.discount_curves["USD"]
            return handle.zeroRate(T, ql.Continuous, ql.Annual).rate()

        if market_env.discount_curves:
            handle = next(iter(market_env.discount_curves.values()))
            return handle.zeroRate(T, ql.Continuous, ql.Annual).rate()

        return 0.05  # fallback

    def _extract_foreign_rate(self, market_env: MarketEnvironment, foreign: str, ccy_pair: str, T: float) -> float:
        """
        Extract foreign rate. Checks multiple sources:
        1. Dedicated foreign discount curve (e.g., "USD" for USDINR)
        2. Dividend curve convention (e.g., "USDINR_div")
        3. Forecast curve
        """
        # Direct foreign discount curve
        for key in [foreign, foreign.upper()]:
            if key in market_env.discount_curves:
                handle = market_env.discount_curves[key]
                return handle.zeroRate(T, ql.Continuous, ql.Annual).rate()

        # Dividend curve convention (used by BSM-style setup)
        div_key = f"{ccy_pair}_div"
        if div_key in market_env.dividend_curves:
            handle = market_env.dividend_curves[div_key]
            if hasattr(handle, 'zeroRate'):
                return handle.zeroRate(T, ql.Continuous, ql.Annual).rate()

        # Forecast curve
        for key in [foreign, foreign.upper()]:
            if key in market_env.forecast_curves:
                handle = market_env.forecast_curves[key]
                return handle.zeroRate(T, ql.Continuous, ql.Annual).rate()

        return 0.02  # fallback

    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update({
            "ccy_pair": self.ccy_pair,
            "strike": self.strike,
            "notional": self.notional,
            "direction": self.direction,
            "delivery_date": self.delivery_date.isoformat(),
        })
        return base
