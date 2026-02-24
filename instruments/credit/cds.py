"""
Credit Default Swap (CDS) instrument.

A CDS is a contract where the protection buyer pays a periodic premium
(spread) to the protection seller. In return, the seller compensates
the buyer if a credit event (default) occurs on the reference entity.

Key terms:
  - Spread (premium): periodic payment in bps (e.g. 100bp = 1%)
  - Notional: face value of protection
  - Recovery rate: expected recovery on default (typically 40%)
  - Protection buyer: pays spread, receives (1-R)*N on default
  - Protection seller: receives spread, pays (1-R)*N on default

Pricing requires a hazard rate curve (or flat hazard rate) to model
the probability of default. Uses ql.CreditDefaultSwap with
ql.MidPointCdsEngine.
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


@instrument_registry.register_decorator(InstrumentType.CDS.value, overwrite=True)
@dataclass
class CreditDefaultSwap(BaseInstrument):
    """Credit Default Swap.

    Attributes:
        _trade_id: Unique trade identifier.
        notional: Notional (face value of protection).
        _currency: Currency code.
        start_date: CDS effective date.
        maturity_date: CDS maturity.
        spread: CDS premium in decimal (e.g. 0.01 = 100bp).
        direction: 'buy' = buy protection (pay spread),
                   'sell' = sell protection (receive spread).
        recovery_rate: Expected recovery rate (0-1, typically 0.40).
        payment_frequency: Premium leg payment frequency.
        day_count: Day count convention for premium leg.
        hazard_rate: Flat hazard rate for pricing (annual, e.g. 0.02 = 2%).
    """

    _trade_id: str = "CDS-001"
    notional: float = 10_000_000
    _currency: str = "USD"
    start_date: date = None
    maturity_date: date = None
    spread: float = 0.01  # 100bp
    direction: str = "buy"
    recovery_rate: float = 0.40
    payment_frequency: str = "quarterly"
    day_count: str = "ACT/360"
    hazard_rate: float = 0.02  # 2% annual default probability
    # Spread curve for bootstrapped engine: {"1Y": 0.005, "3Y": 0.008, ...}
    spread_curve: Optional[Dict[str, float]] = None

    def trade_id(self) -> TradeId:
        return TradeId(self._trade_id)

    def asset_class(self) -> AssetClass:
        return AssetClass.CREDIT

    def instrument_type(self) -> InstrumentType:
        return InstrumentType.CDS

    def currency(self) -> str:
        return self._currency

    def maturity(self) -> date:
        return self.maturity_date

    def build(self, market_env: MarketEnvironment) -> ql.CreditDefaultSwap:
        """Build QuantLib CDS object."""
        try:
            market_env.set_evaluation_date()

            ql_start = ql.Date(
                self.start_date.day, self.start_date.month, self.start_date.year
            )
            ql_maturity = ql.Date(
                self.maturity_date.day, self.maturity_date.month,
                self.maturity_date.year
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
            freq = freq_map.get(self.payment_frequency, ql.Quarterly)

            # Premium leg schedule
            schedule = ql.Schedule(
                ql_start, ql_maturity, ql.Period(freq),
                calendar, bdc, bdc,
                ql.DateGeneration.TwentiethIMM, False,
            )

            # CDS side: Protection buyer or seller
            side = (
                ql.Protection.Buyer if self.direction == "buy"
                else ql.Protection.Seller
            )

            cds = ql.CreditDefaultSwap(
                side,
                self.notional,
                self.spread,  # running spread
                schedule,
                bdc,
                dc,
            )

            return cds

        except Exception as e:
            raise InstrumentBuildError(
                f"Failed to build CDS {self._trade_id}: {e}"
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

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CreditDefaultSwap:
        """Deserialize from dictionary."""
        def parse_date(d):
            if d is None:
                return None
            if isinstance(d, date):
                return d
            return date.fromisoformat(str(d))

        return cls(
            _trade_id=data.get("trade_id", "CDS-001"),
            notional=float(data.get("notional", 10_000_000)),
            _currency=data.get("currency", "USD"),
            start_date=parse_date(data.get("start_date")),
            maturity_date=parse_date(data.get("maturity_date")),
            spread=float(data.get("spread", 0.01)),
            direction=data.get("direction", "buy"),
            recovery_rate=float(data.get("recovery_rate", 0.40)),
            payment_frequency=data.get("payment_frequency", "quarterly"),
            day_count=data.get("day_count", "ACT/360"),
            hazard_rate=float(data.get("hazard_rate", 0.02)),
            spread_curve=data.get("spread_curve"),
        )

    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update({
            "notional": self.notional,
            "spread": self.spread,
            "direction": self.direction,
            "recovery_rate": self.recovery_rate,
            "hazard_rate": self.hazard_rate,
            "spread_curve": self.spread_curve,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "maturity_date": self.maturity_date.isoformat() if self.maturity_date else None,
        })
        return base

    def __repr__(self) -> str:
        return (
            f"CDS("
            f"id={self._trade_id}, "
            f"{self.direction.upper()} protection "
            f"{self.spread*10000:.0f}bp "
            f"{self.notional:,.0f} {self._currency} "
            f"R={self.recovery_rate:.0%} "
            f"mat={self.maturity_date}"
            f")"
        )
