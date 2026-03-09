"""
Swaption (Swap Option) instrument.

A swaption gives the holder the right (but not obligation) to enter
into an interest rate swap at a pre-agreed fixed rate on the expiry date.

Types:
  - Payer swaption: right to PAY fixed (bullish on rates)
  - Receiver swaption: right to RECEIVE fixed (bearish on rates)

Settlement:
  - Physical: enter the swap on exercise
  - Cash: receive PV of the swap on exercise

Pricing via Black's model (lognormal) or Bachelier (normal vol).

Example: 1Y into 5Y payer swaption
  = option expiring in 1 year to enter a 5Y payer swap
  = right to pay fixed at the strike rate for 5 years starting in 1 year
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


@instrument_registry.register_decorator(InstrumentType.SWAPTION.value, overwrite=True)
@dataclass
class Swaption(BaseInstrument):
    """European Swaption.

    Attributes:
        _trade_id: Unique trade identifier.
        notional: Swap notional amount.
        _currency: Currency code.
        expiry_date: Swaption expiry (option maturity).
        swap_start: Underlying swap start date (= expiry for spot-starting).
        swap_end: Underlying swap maturity.
        strike: Fixed rate of the underlying swap.
        swaption_type: 'payer' or 'receiver'.
        fixed_leg_frequency: Fixed leg payment frequency.
        float_leg_frequency: Float leg payment frequency.
        fixed_day_count: Fixed leg day count.
        float_day_count: Float leg day count.
        float_index_tenor: Floating index tenor.
        settlement_type: 'physical' or 'cash'.
        vol: Black (lognormal) vol for pricing.
    """

    _trade_id: str = "SWPN-001"
    notional: float = 1_000_000
    _currency: str = "USD"
    expiry_date: date = None
    swap_start: date = None  # defaults to expiry_date if None
    swap_end: date = None
    strike: float = 0.04
    swaption_type: str = "payer"
    fixed_leg_frequency: str = "semiannual"
    float_leg_frequency: str = "quarterly"
    fixed_day_count: str = "30/360"
    float_day_count: str = "ACT/360"
    float_index_tenor: str = "3M"
    settlement_type: str = "physical"
    vol: float = 0.20

    def trade_id(self) -> TradeId:
        return TradeId(self._trade_id)

    def asset_class(self) -> AssetClass:
        return AssetClass.RATES

    def instrument_type(self) -> InstrumentType:
        return InstrumentType.SWAPTION

    def currency(self) -> str:
        return self._currency

    def maturity(self) -> date:
        return self.expiry_date

    def build(self, market_env: MarketEnvironment) -> ql.Swaption:
        """Build QuantLib Swaption object."""
        try:
            market_env.set_evaluation_date()

            # Default swap_start to expiry_date (spot-starting swaption)
            swap_start = self.swap_start or self.expiry_date

            ql_expiry = ql.Date(
                self.expiry_date.day, self.expiry_date.month, self.expiry_date.year
            )
            ql_swap_start = ql.Date(
                swap_start.day, swap_start.month, swap_start.year
            )
            ql_swap_end = ql.Date(
                self.swap_end.day, self.swap_end.month, self.swap_end.year
            )

            calendar = self._get_calendar()
            bdc = ql.ModifiedFollowing

            # Frequencies
            freq_map = {
                "annual": ql.Annual, "semiannual": ql.Semiannual,
                "quarterly": ql.Quarterly, "monthly": ql.Monthly,
            }
            fixed_freq = freq_map.get(self.fixed_leg_frequency, ql.Semiannual)
            float_freq = freq_map.get(self.float_leg_frequency, ql.Quarterly)

            # Day counts
            dc_map = {
                "ACT/360": ql.Actual360(),
                "ACT/365": ql.Actual365Fixed(),
                "30/360": ql.Thirty360(ql.Thirty360.BondBasis),
                "ACT/ACT": ql.ActualActual(ql.ActualActual.ISDA),
            }
            fixed_dc = dc_map.get(self.fixed_day_count, ql.Thirty360(ql.Thirty360.BondBasis))
            float_dc = dc_map.get(self.float_day_count, ql.Actual360())

            # Schedules for the underlying swap
            fixed_schedule = ql.Schedule(
                ql_swap_start, ql_swap_end, ql.Period(fixed_freq),
                calendar, bdc, bdc, ql.DateGeneration.Forward, False,
            )
            float_schedule = ql.Schedule(
                ql_swap_start, ql_swap_end, ql.Period(float_freq),
                calendar, bdc, bdc, ql.DateGeneration.Forward, False,
            )

            # IBOR index
            index = self._get_ibor_index(market_env)

            # Build underlying swap
            swap_type = (
                ql.VanillaSwap.Payer if self.swaption_type == "payer"
                else ql.VanillaSwap.Receiver
            )
            underlying_swap = ql.VanillaSwap(
                swap_type,
                self.notional,
                fixed_schedule,
                self.strike,
                fixed_dc,
                float_schedule,
                index,
                0.0,  # spread
                float_dc,
            )

            # European exercise on expiry date
            exercise = ql.EuropeanExercise(ql_expiry)

            # Settlement type
            if self.settlement_type == "cash":
                settle = ql.Settlement.Cash
                settle_method = ql.Settlement.ParYieldCurve
            else:
                settle = ql.Settlement.Physical
                settle_method = ql.Settlement.PhysicalOTC

            swaption = ql.Swaption(
                underlying_swap,
                exercise,
                settle,
                settle_method,
            )

            return swaption

        except Exception as e:
            raise InstrumentBuildError(
                f"Failed to build Swaption {self._trade_id}: {e}"
            ) from e

    def _get_calendar(self) -> ql.Calendar:
        cal_map = {
            "USD": ql.UnitedStates(ql.UnitedStates.GovernmentBond),
            "EUR": ql.TARGET(),
            "GBP": ql.UnitedKingdom(),
            "JPY": ql.Japan(),
        }
        return cal_map.get(self._currency, ql.NullCalendar())

    def _get_ibor_index(self, market_env: MarketEnvironment) -> ql.IborIndex:
        forecast = market_env.forecast_curves.get(
            self._currency,
            market_env.discount_curves.get(self._currency),
        )
        if forecast is None and market_env.discount_curves:
            forecast = list(market_env.discount_curves.values())[0]

        tenor_map = {
            "1M": ql.Period(1, ql.Months),
            "3M": ql.Period(3, ql.Months),
            "6M": ql.Period(6, ql.Months),
        }
        tenor = tenor_map.get(self.float_index_tenor, ql.Period(3, ql.Months))

        if self._currency == "USD":
            return ql.USDLibor(tenor, forecast)
        elif self._currency == "EUR":
            return ql.Euribor(tenor, forecast)
        elif self._currency == "GBP":
            return ql.GBPLibor(tenor, forecast)
        else:
            return ql.USDLibor(tenor, forecast)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Swaption:
        """Deserialize from dictionary."""
        def parse_date(d):
            if d is None:
                return None
            if isinstance(d, date):
                return d
            return date.fromisoformat(str(d))

        return cls(
            _trade_id=data.get("trade_id", "SWPN-001"),
            notional=float(data.get("notional", 1_000_000)),
            _currency=data.get("currency", "USD"),
            expiry_date=parse_date(data.get("expiry_date")),
            swap_start=parse_date(data.get("swap_start")),
            swap_end=parse_date(data.get("swap_end")),
            strike=float(data.get("strike", 0.04)),
            swaption_type=data.get("swaption_type", "payer"),
            fixed_leg_frequency=data.get("fixed_leg_frequency", "semiannual"),
            float_leg_frequency=data.get("float_leg_frequency", "quarterly"),
            fixed_day_count=data.get("fixed_day_count", "30/360"),
            float_day_count=data.get("float_day_count", "ACT/360"),
            float_index_tenor=data.get("float_index_tenor", "3M"),
            settlement_type=data.get("settlement_type", "physical"),
            vol=float(data.get("vol", 0.20)),
        )

    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update({
            "notional": self.notional,
            "strike": self.strike,
            "swaption_type": self.swaption_type,
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "swap_start": self.swap_start.isoformat() if self.swap_start else None,
            "swap_end": self.swap_end.isoformat() if self.swap_end else None,
            "settlement_type": self.settlement_type,
        })
        return base

    def __repr__(self) -> str:
        return (
            f"Swaption("
            f"id={self._trade_id}, "
            f"{self.swaption_type.upper()} "
            f"K={self.strike*100:.2f}% "
            f"exp={self.expiry_date} "
            f"swap→{self.swap_end} "
            f"{self.notional:,.0f} {self._currency}"
            f")"
        )
