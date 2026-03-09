"""
Interest Rate Swap instrument wrapper.

Covers:
- Fixed vs Float IRS
- Basis swaps (placeholder)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Optional

import QuantLib as ql

from core.enums.definitions import (
    AssetClass,
    Currency,
    DayCountConvention,
    Frequency,
    InstrumentType,
    TradeDirection,
)
from core.exceptions.errors import InstrumentBuildError
from core.interfaces.base import BaseInstrument, MarketEnvironment
from core.types.value_objects import PricingDate, TradeId
from registry import instrument_registry


@instrument_registry.register_decorator(InstrumentType.IRS.value)
@dataclass
class InterestRateSwap(BaseInstrument):
    """Fixed vs Float Interest Rate Swap."""

    _trade_id: str
    notional: float
    _currency: str = "USD"
    start_date: date = None
    end_date: date = None
    fixed_rate: float = 0.0
    fixed_leg_frequency: str = "semiannual"
    float_leg_frequency: str = "quarterly"
    fixed_day_count: str = "30/360"
    float_day_count: str = "ACT/360"
    direction: str = "pay"  # pay = pay fixed, receive = receive fixed
    float_index_tenor: str = "3M"

    def trade_id(self) -> TradeId:
        return TradeId(self._trade_id)

    def asset_class(self) -> AssetClass:
        return AssetClass.RATES

    def instrument_type(self) -> InstrumentType:
        return InstrumentType.IRS

    def currency(self) -> str:
        return self._currency

    def maturity(self) -> date:
        return self.end_date

    def build(self, market_env: MarketEnvironment) -> ql.VanillaSwap:
        try:
            market_env.set_evaluation_date()

            ql_start = ql.Date(self.start_date.day, self.start_date.month, self.start_date.year)
            ql_end = ql.Date(self.end_date.day, self.end_date.month, self.end_date.year)

            # Calendar & conventions
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
                "ACT/360": ql.Actual360(), "ACT/365": ql.Actual365Fixed(),
                "30/360": ql.Thirty360(ql.Thirty360.BondBasis),
                "ACT/ACT": ql.ActualActual(ql.ActualActual.ISDA),
            }
            fixed_dc = dc_map.get(self.fixed_day_count, ql.Thirty360(ql.Thirty360.BondBasis))
            float_dc = dc_map.get(self.float_day_count, ql.Actual360())

            # Schedules
            fixed_schedule = ql.Schedule(
                ql_start, ql_end, ql.Period(fixed_freq),
                calendar, bdc, bdc, ql.DateGeneration.Forward, False,
            )
            float_schedule = ql.Schedule(
                ql_start, ql_end, ql.Period(float_freq),
                calendar, bdc, bdc, ql.DateGeneration.Forward, False,
            )

            # Float index
            index = self._get_ibor_index(market_env)

            # Add past fixings — QuantLib requires fixings for all past
            # floating leg reset dates. Use the flat rate from the curve.
            eval_date = ql.Settings.instance().evaluationDate
            flat_rate = market_env.discount_curves.get(
                self._currency,
                list(market_env.discount_curves.values())[0] if market_env.discount_curves else None,
            )
            if flat_rate:
                fixing_rate = flat_rate.zeroRate(
                    0.25, ql.Continuous, ql.Annual
                ).rate()
            else:
                fixing_rate = self.fixed_rate

            # Add fixings for all past dates
            for i in range(len(float_schedule) - 1):
                reset_date = index.fixingDate(float_schedule[i])
                if reset_date < eval_date:
                    try:
                        index.addFixing(reset_date, fixing_rate)
                    except RuntimeError:
                        pass  # Fixing already added

            # Swap type
            swap_type = ql.VanillaSwap.Payer if self.direction == "pay" else ql.VanillaSwap.Receiver

            swap = ql.VanillaSwap(
                swap_type,
                self.notional,
                fixed_schedule,
                self.fixed_rate,
                fixed_dc,
                float_schedule,
                index,
                0.0,  # spread
                float_dc,
            )

            return swap

        except Exception as e:
            raise InstrumentBuildError(f"Failed to build IRS {self._trade_id}: {e}") from e

    def _get_calendar(self) -> ql.Calendar:
        cal_map = {
            "USD": ql.UnitedStates(ql.UnitedStates.GovernmentBond),
            "EUR": ql.TARGET(),
            "GBP": ql.UnitedKingdom(),
            "JPY": ql.Japan(),
        }
        return cal_map.get(self._currency, ql.NullCalendar())

    def _get_ibor_index(self, market_env: MarketEnvironment) -> ql.IborIndex:
        """Get IBOR index with forwarding curve."""
        forecast = market_env.forecast_curves.get(
            self._currency,
            market_env.discount_curves.get(self._currency),
        )

        tenor_map = {"1M": ql.Period(1, ql.Months), "3M": ql.Period(3, ql.Months), "6M": ql.Period(6, ql.Months)}
        tenor = tenor_map.get(self.float_index_tenor, ql.Period(3, ql.Months))

        if self._currency == "USD":
            return ql.USDLibor(tenor, forecast)
        elif self._currency == "EUR":
            return ql.Euribor(tenor, forecast)
        elif self._currency == "GBP":
            return ql.GBPLibor(tenor, forecast)
        else:
            return ql.USDLibor(tenor, forecast)

    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update({
            "notional": self.notional,
            "fixed_rate": self.fixed_rate,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "direction": self.direction,
        })
        return base

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> InterestRateSwap:
        """Deserialize from dictionary."""
        def parse_date(d):
            if d is None:
                return None
            if isinstance(d, date):
                return d
            return date.fromisoformat(str(d))

        return cls(
            _trade_id=data.get("trade_id", "IRS-001"),
            notional=float(data.get("notional", 1_000_000)),
            _currency=data.get("currency", "USD"),
            start_date=parse_date(data.get("start_date")),
            end_date=parse_date(data.get("end_date")),
            fixed_rate=float(data.get("fixed_rate", 0.0)),
            fixed_leg_frequency=data.get("fixed_leg_frequency", "semiannual"),
            float_leg_frequency=data.get("float_leg_frequency", "quarterly"),
            fixed_day_count=data.get("fixed_day_count", "30/360"),
            float_day_count=data.get("float_day_count", "ACT/360"),
            direction=data.get("direction", "pay"),
            float_index_tenor=data.get("float_index_tenor", "3M"),
        )
