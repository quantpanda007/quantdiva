"""
Forward Rate Agreement (FRA) instrument.

A FRA is an agreement to exchange a fixed rate for a floating rate
on a notional amount for a single future period. It's the simplest
rates derivative — essentially a single-period swap.

Example: 3x6 FRA = agreement starting in 3 months, ending in 6 months.
    - Buyer pays fixed rate, receives floating (LIBOR/SOFR)
    - Settlement at start of period based on rate differential

QuantLib doesn't have a dedicated FRA instrument, so we build it
as a single-period swap (1 fixed + 1 float cashflow).
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


@instrument_registry.register_decorator(InstrumentType.FRA.value, overwrite=True)
@dataclass
class ForwardRateAgreement(BaseInstrument):
    """Forward Rate Agreement.

    Attributes:
        _trade_id: Unique trade identifier.
        notional: Notional amount.
        _currency: Currency code.
        start_date: Start of the FRA period (e.g. 3M from now).
        end_date: End of the FRA period (e.g. 6M from now).
        fixed_rate: The agreed FRA rate (e.g. 0.045 = 4.5%).
        direction: 'pay' = pay fixed / receive float (long FRA),
                   'receive' = receive fixed / pay float (short FRA).
        day_count: Day count convention for the period.
        float_index_tenor: Tenor of the floating index (e.g. '3M').
    """

    _trade_id: str = "FRA-001"
    notional: float = 1_000_000
    _currency: str = "USD"
    start_date: date = None
    end_date: date = None
    fixed_rate: float = 0.045
    direction: str = "pay"
    day_count: str = "ACT/360"
    float_index_tenor: str = "3M"

    def trade_id(self) -> TradeId:
        return TradeId(self._trade_id)

    def asset_class(self) -> AssetClass:
        return AssetClass.RATES

    def instrument_type(self) -> InstrumentType:
        return InstrumentType.FRA

    def currency(self) -> str:
        return self._currency

    def maturity(self) -> date:
        return self.end_date

    def build(self, market_env: MarketEnvironment) -> ql.VanillaSwap:
        """Build FRA as a single-period VanillaSwap.

        This approach guarantees compatibility with DiscountingSwapEngine
        and works across all QuantLib versions. A FRA is economically
        equivalent to a single-period fixed-vs-float swap.
        """
        try:
            market_env.set_evaluation_date()

            ql_start = ql.Date(
                self.start_date.day, self.start_date.month, self.start_date.year
            )
            ql_end = ql.Date(
                self.end_date.day, self.end_date.month, self.end_date.year
            )

            calendar = self._get_calendar()
            bdc = ql.ModifiedFollowing
            dc = self._get_day_count()

            # Single-period schedule (just start → end)
            schedule = ql.Schedule(
                ql_start, ql_end,
                ql.Period(ql.Once),  # single period
                calendar, bdc, bdc,
                ql.DateGeneration.Forward, False,
            )

            # IBOR index with forecast curve
            index = self._get_ibor_index(market_env)

            # Add past fixings if needed
            eval_date = ql.Settings.instance().evaluationDate
            fixing_date = index.fixingDate(ql_start)
            if fixing_date <= eval_date:
                curve = market_env.forecast_curves.get(
                    self._currency,
                    market_env.discount_curves.get(
                        self._currency,
                        list(market_env.discount_curves.values())[0]
                        if market_env.discount_curves else None,
                    ),
                )
                if curve:
                    fixing_rate = curve.zeroRate(
                        0.25, ql.Continuous, ql.Annual
                    ).rate()
                else:
                    fixing_rate = self.fixed_rate
                try:
                    index.addFixing(fixing_date, fixing_rate)
                except RuntimeError:
                    pass

            # Build as single-period swap
            swap_type = (
                ql.VanillaSwap.Payer if self.direction == "pay"
                else ql.VanillaSwap.Receiver
            )

            swap = ql.VanillaSwap(
                swap_type,
                self.notional,
                schedule,          # fixed leg schedule
                self.fixed_rate,
                dc,
                schedule,          # float leg schedule (same period)
                index,
                0.0,               # spread
                dc,
            )

            return swap

        except Exception as e:
            raise InstrumentBuildError(
                f"Failed to build FRA {self._trade_id}: {e}"
            ) from e

    def _get_calendar(self) -> ql.Calendar:
        cal_map = {
            "USD": ql.UnitedStates(ql.UnitedStates.GovernmentBond),
            "EUR": ql.TARGET(),
            "GBP": ql.UnitedKingdom(),
            "JPY": ql.Japan(),
        }
        return cal_map.get(self._currency, ql.NullCalendar())

    def _get_day_count(self) -> ql.DayCounter:
        dc_map = {
            "ACT/360": ql.Actual360(),
            "ACT/365": ql.Actual365Fixed(),
            "30/360": ql.Thirty360(ql.Thirty360.BondBasis),
            "ACT/ACT": ql.ActualActual(ql.ActualActual.ISDA),
        }
        return dc_map.get(self.day_count, ql.Actual360())

    def _get_ibor_index(self, market_env: MarketEnvironment) -> ql.IborIndex:
        """Get IBOR index with forwarding curve."""
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
    def from_dict(cls, data: Dict[str, Any]) -> ForwardRateAgreement:
        """Deserialize from dictionary."""
        def parse_date(d):
            if d is None:
                return None
            if isinstance(d, date):
                return d
            return date.fromisoformat(str(d))

        return cls(
            _trade_id=data.get("trade_id", "FRA-001"),
            notional=float(data.get("notional", 1_000_000)),
            _currency=data.get("currency", "USD"),
            start_date=parse_date(data.get("start_date")),
            end_date=parse_date(data.get("end_date")),
            fixed_rate=float(data.get("fixed_rate", 0.045)),
            direction=data.get("direction", "pay"),
            day_count=data.get("day_count", "ACT/360"),
            float_index_tenor=data.get("float_index_tenor", "3M"),
        )

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

    def __repr__(self) -> str:
        return (
            f"FRA("
            f"id={self._trade_id}, "
            f"{self.direction} "
            f"{self.fixed_rate*100:.2f}% "
            f"{self.notional:,.0f} {self._currency} "
            f"{self.start_date}→{self.end_date}"
            f")"
        )
