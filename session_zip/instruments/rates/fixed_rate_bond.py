"""
Fixed Rate Bond instrument.

Covers fixed coupon bonds with clean/dirty price,
yield, duration, convexity calculations via QuantLib.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

import QuantLib as ql

from core.enums.definitions import AssetClass, InstrumentType
from core.exceptions.errors import InstrumentBuildError
from core.interfaces.base import BaseInstrument, MarketEnvironment
from core.types.value_objects import PricingDate, TradeId
from registry import instrument_registry


@instrument_registry.register_decorator(InstrumentType.BOND.value, overwrite=True)
@dataclass
class FixedRateBond(BaseInstrument):
    """Fixed coupon bond.

    Attributes:
        _trade_id: Unique trade identifier.
        face_value: Notional / par value (default 100).
        coupon_rate: Annual coupon rate (e.g. 0.05 = 5%).
        issue_date: Bond issuance date.
        maturity_date: Bond maturity date.
        coupon_frequency: annual, semiannual, quarterly.
        day_count: Day count convention string.
        settlement_days: Business days to settle.
        _currency: Currency code.
    """

    _trade_id: str = "BOND-001"
    face_value: float = 100.0
    coupon_rate: float = 0.05
    issue_date: date = None
    maturity_date: date = None
    coupon_frequency: str = "semiannual"
    day_count: str = "ACT/ACT"
    settlement_days: int = 2
    _currency: str = "USD"

    def trade_id(self) -> TradeId:
        return TradeId(self._trade_id)

    def asset_class(self) -> AssetClass:
        return AssetClass.RATES

    def instrument_type(self) -> InstrumentType:
        return InstrumentType.BOND

    def currency(self) -> str:
        return self._currency

    def maturity(self) -> date:
        return self.maturity_date

    def build(self, market_env: MarketEnvironment) -> ql.FixedRateBond:
        try:
            market_env.set_evaluation_date()

            ql_issue = ql.Date(self.issue_date.day, self.issue_date.month, self.issue_date.year)
            ql_maturity = ql.Date(
                self.maturity_date.day, self.maturity_date.month, self.maturity_date.year
            )

            calendar = self._get_calendar()
            bdc = ql.ModifiedFollowing
            dc = self._get_day_count()

            freq_map = {
                "annual": ql.Annual,
                "semiannual": ql.Semiannual,
                "quarterly": ql.Quarterly,
                "monthly": ql.Monthly,
            }
            freq = freq_map.get(self.coupon_frequency, ql.Semiannual)

            schedule = ql.Schedule(
                ql_issue, ql_maturity, ql.Period(freq),
                calendar, bdc, bdc, ql.DateGeneration.Backward, False,
            )

            bond = ql.FixedRateBond(
                self.settlement_days,
                self.face_value,
                schedule,
                [self.coupon_rate],
                dc,
            )

            return bond

        except Exception as e:
            raise InstrumentBuildError(
                f"Failed to build Bond {self._trade_id}: {e}"
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
        return dc_map.get(self.day_count, ql.ActualActual(ql.ActualActual.ISDA))

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FixedRateBond:
        """Deserialize from dictionary."""
        def parse_date(d):
            if d is None:
                return None
            if isinstance(d, date):
                return d
            return date.fromisoformat(str(d))

        return cls(
            _trade_id=data.get("trade_id", "BOND-001"),
            face_value=float(data.get("face_value", 100.0)),
            coupon_rate=float(data.get("coupon_rate", 0.05)),
            issue_date=parse_date(data.get("issue_date")),
            maturity_date=parse_date(data.get("maturity_date")),
            coupon_frequency=data.get("coupon_frequency", "semiannual"),
            day_count=data.get("day_count", "ACT/ACT"),
            settlement_days=int(data.get("settlement_days", 2)),
            _currency=data.get("currency", "USD"),
        )

    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update({
            "face_value": self.face_value,
            "coupon_rate": self.coupon_rate,
            "issue_date": self.issue_date.isoformat() if self.issue_date else None,
            "maturity_date": self.maturity_date.isoformat() if self.maturity_date else None,
            "coupon_frequency": self.coupon_frequency,
        })
        return base

    def __repr__(self) -> str:
        return (
            f"FixedRateBond("
            f"id={self._trade_id}, "
            f"{self.coupon_rate*100:.2f}% "
            f"{self._currency} "
            f"mat={self.maturity_date}"
            f")"
        )
