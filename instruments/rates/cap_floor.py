"""
Interest Rate Cap / Floor instrument.

A cap is a series of call options (caplets) on a floating rate.
A floor is a series of put options (floorlets) on a floating rate.

Each caplet/floorlet pays max(0, L - K) * tau * N for a cap,
or max(0, K - L) * tau * N for a floor, where L = LIBOR, K = strike,
tau = day count fraction, N = notional.

Cap = strip of caplets = portfolio of FRA call options.
Floor = strip of floorlets = portfolio of FRA put options.

Priced via Black's model (ql.BlackCapFloorEngine).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional

import QuantLib as ql

from core.enums.definitions import AssetClass, InstrumentType
from core.exceptions.errors import InstrumentBuildError
from core.interfaces.base import BaseInstrument, MarketEnvironment
from core.types.value_objects import PricingDate, TradeId
from registry import instrument_registry


@instrument_registry.register_decorator(InstrumentType.CAP_FLOOR.value, overwrite=True)
@dataclass
class CapFloor(BaseInstrument):
    """Interest Rate Cap or Floor.

    Attributes:
        _trade_id: Unique trade identifier.
        notional: Notional amount.
        _currency: Currency code.
        start_date: Cap/floor start date.
        end_date: Cap/floor maturity.
        strike: Cap/floor strike rate.
        cap_or_floor: 'cap' or 'floor'.
        float_frequency: Reset frequency of the floating leg.
        day_count: Day count convention.
        float_index_tenor: Floating index tenor.
        vol: Flat Black vol for pricing (normal or lognormal).
    """

    _trade_id: str = "CAP-001"
    notional: float = 1_000_000
    _currency: str = "USD"
    start_date: date = None
    end_date: date = None
    strike: float = 0.05
    cap_or_floor: str = "cap"
    float_frequency: str = "quarterly"
    day_count: str = "ACT/360"
    float_index_tenor: str = "3M"
    vol: float = 0.20  # Black vol for caplet pricing

    def trade_id(self) -> TradeId:
        return TradeId(self._trade_id)

    def asset_class(self) -> AssetClass:
        return AssetClass.RATES

    def instrument_type(self) -> InstrumentType:
        return InstrumentType.CAP_FLOOR

    def currency(self) -> str:
        return self._currency

    def maturity(self) -> date:
        return self.end_date

    def build(self, market_env: MarketEnvironment) -> ql.Instrument:
        """Build QuantLib Cap or Floor."""
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

            # Frequency
            freq_map = {
                "monthly": ql.Monthly,
                "quarterly": ql.Quarterly,
                "semiannual": ql.Semiannual,
                "annual": ql.Annual,
            }
            freq = freq_map.get(self.float_frequency, ql.Quarterly)

            # Schedule for the floating leg
            schedule = ql.Schedule(
                ql_start, ql_end, ql.Period(freq),
                calendar, bdc, bdc,
                ql.DateGeneration.Forward, False,
            )

            # IBOR index
            index = self._get_ibor_index(market_env)

            # Add past fixings
            eval_date = ql.Settings.instance().evaluationDate
            for i in range(len(schedule) - 1):
                fixing_date = index.fixingDate(schedule[i])
                if fixing_date < eval_date:
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
                        fixing_rate = self.strike
                    try:
                        index.addFixing(fixing_date, fixing_rate)
                    except RuntimeError:
                        pass

            # Build floating leg
            float_leg = ql.IborLeg([self.notional], schedule, index, dc)

            # Build Cap or Floor
            if self.cap_or_floor.lower() == "cap":
                instrument = ql.Cap(float_leg, [self.strike])
            elif self.cap_or_floor.lower() == "floor":
                instrument = ql.Floor(float_leg, [self.strike])
            else:
                raise ValueError(
                    f"cap_or_floor must be 'cap' or 'floor', got '{self.cap_or_floor}'"
                )

            return instrument

        except Exception as e:
            raise InstrumentBuildError(
                f"Failed to build {self.cap_or_floor} {self._trade_id}: {e}"
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
    def from_dict(cls, data: Dict[str, Any]) -> CapFloor:
        def parse_date(d):
            if d is None:
                return None
            if isinstance(d, date):
                return d
            return date.fromisoformat(str(d))

        return cls(
            _trade_id=data.get("trade_id", "CAP-001"),
            notional=float(data.get("notional", 1_000_000)),
            _currency=data.get("currency", "USD"),
            start_date=parse_date(data.get("start_date")),
            end_date=parse_date(data.get("end_date")),
            strike=float(data.get("strike", 0.05)),
            cap_or_floor=data.get("cap_or_floor", "cap"),
            float_frequency=data.get("float_frequency", "quarterly"),
            day_count=data.get("day_count", "ACT/360"),
            float_index_tenor=data.get("float_index_tenor", "3M"),
            vol=float(data.get("vol", 0.20)),
        )

    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update({
            "notional": self.notional,
            "strike": self.strike,
            "cap_or_floor": self.cap_or_floor,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
        })
        return base

    def __repr__(self) -> str:
        return (
            f"CapFloor("
            f"id={self._trade_id}, "
            f"{self.cap_or_floor.upper()} "
            f"K={self.strike*100:.2f}% "
            f"{self.notional:,.0f} {self._currency} "
            f"{self.start_date}→{self.end_date}"
            f")"
        )
