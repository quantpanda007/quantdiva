"""
Core value objects and types used throughout the pricing platform.

These are immutable, domain-specific types that carry meaning beyond
primitive Python types. They form the shared vocabulary of the system.
"""

from __future__ import annotations

import QuantLib as ql
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, Union
from enum import Enum


# ---------------------------------------------------------------------------
# Date & Time
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PricingDate:
    """Wraps a pricing/valuation date with QuantLib conversion."""
    value: date

    def to_ql(self) -> ql.Date:
        return ql.Date(self.value.day, self.value.month, self.value.year)

    @classmethod
    def from_ql(cls, ql_date: ql.Date) -> PricingDate:
        return cls(value=date(ql_date.year(), ql_date.month(), ql_date.dayOfMonth()))

    @classmethod
    def today(cls) -> PricingDate:
        return cls(value=date.today())


@dataclass(frozen=True)
class Tenor:
    """Represents a market tenor like 1Y, 6M, 3M, ON, TN, SN."""
    value: str  # e.g., "1Y", "6M", "3M", "1W", "ON"

    def to_ql_period(self) -> ql.Period:
        """Convert to QuantLib Period."""
        special = {"ON": ql.Period(1, ql.Days), "TN": ql.Period(2, ql.Days), "SN": ql.Period(3, ql.Days)}
        if self.value.upper() in special:
            return special[self.value.upper()]

        num = int(self.value[:-1])
        unit_map = {"D": ql.Days, "W": ql.Weeks, "M": ql.Months, "Y": ql.Years}
        unit = unit_map.get(self.value[-1].upper())
        if unit is None:
            raise ValueError(f"Unknown tenor unit in '{self.value}'")
        return ql.Period(num, unit)

    def __str__(self) -> str:
        return self.value


# ---------------------------------------------------------------------------
# Financial Types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Money:
    """Immutable monetary amount with currency."""
    amount: Decimal
    currency: str  # ISO 4217

    def __post_init__(self):
        if not isinstance(self.amount, Decimal):
            object.__setattr__(self, 'amount', Decimal(str(self.amount)))

    def __add__(self, other: Money) -> Money:
        if self.currency != other.currency:
            raise ValueError(f"Cannot add {self.currency} and {other.currency}")
        return Money(self.amount + other.amount, self.currency)

    def __mul__(self, factor: Union[int, float, Decimal]) -> Money:
        return Money(self.amount * Decimal(str(factor)), self.currency)

    def __str__(self) -> str:
        return f"{self.currency} {self.amount:,.2f}"


@dataclass(frozen=True)
class Quote:
    """A market quote with metadata."""
    value: float
    quote_type: str  # "mid", "bid", "ask", "close", "settle"
    source: str = "unknown"
    timestamp: Optional[datetime] = None


@dataclass(frozen=True)
class Rate:
    """An interest rate with convention."""
    value: float
    day_count: str = "ACT/360"
    compounding: str = "simple"  # simple, continuous, compounded
    frequency: str = "annual"

    def to_ql_interest_rate(self) -> ql.InterestRate:
        dc_map = {
            "ACT/360": ql.Actual360(),
            "ACT/365": ql.Actual365Fixed(),
            "ACT/ACT": ql.ActualActual(ql.ActualActual.ISDA),
            "30/360": ql.Thirty360(ql.Thirty360.BondBasis),
        }
        comp_map = {
            "simple": ql.Simple,
            "continuous": ql.Continuous,
            "compounded": ql.Compounded,
        }
        freq_map = {
            "annual": ql.Annual,
            "semiannual": ql.Semiannual,
            "quarterly": ql.Quarterly,
            "monthly": ql.Monthly,
        }
        return ql.InterestRate(
            self.value,
            dc_map.get(self.day_count, ql.Actual360()),
            comp_map.get(self.compounding, ql.Simple),
            freq_map.get(self.frequency, ql.Annual),
        )


# ---------------------------------------------------------------------------
# Trade Identity
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TradeId:
    """Unique trade identifier."""
    value: str

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class PortfolioId:
    """Unique portfolio identifier."""
    value: str

    def __str__(self) -> str:
        return self.value


# ---------------------------------------------------------------------------
# Pricing Results
# ---------------------------------------------------------------------------

@dataclass
class PricingResult:
    """Container for pricing output."""
    trade_id: TradeId
    npv: float
    currency: str
    pricing_date: PricingDate
    greeks: dict = field(default_factory=dict)  # delta, gamma, vega, theta, rho...
    cashflows: list = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)  # model info, convergence, timing
    engine_used: str = ""
    model_used: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def npv_money(self) -> Money:
        return Money(amount=Decimal(str(self.npv)), currency=self.currency)


@dataclass
class RiskResult:
    """Container for risk computation output."""
    trade_id: TradeId
    greeks: dict = field(default_factory=dict)
    scenario_results: dict = field(default_factory=dict)
    var: Optional[float] = None
    cvar: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
