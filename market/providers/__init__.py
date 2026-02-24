"""
Market data provider interfaces.

Defines the abstract base for all market data providers (OpenBB, yfinance, etc.)
and the MarketDataService that orchestrates them with caching and fallback.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class EquitySnapshot:
    """Live equity market data snapshot."""
    symbol: str
    spot: float
    prev_close: float = 0.0
    change_pct: float = 0.0
    volume: int = 0
    timestamp: Optional[datetime] = None
    source: str = ""


@dataclass
class FXSnapshot:
    """Live FX rate snapshot."""
    pair: str  # e.g. "EURUSD"
    rate: float
    bid: float = 0.0
    ask: float = 0.0
    timestamp: Optional[datetime] = None
    source: str = ""


@dataclass
class YieldCurvePoint:
    """Single point on a yield curve."""
    maturity: str        # e.g. "3M", "2Y", "10Y"
    maturity_years: float  # e.g. 0.25, 2.0, 10.0
    rate: float          # e.g. 0.045


@dataclass
class YieldCurveSnapshot:
    """Full yield curve snapshot."""
    currency: str
    curve_date: date
    points: List[YieldCurvePoint] = field(default_factory=list)
    source: str = ""


@dataclass
class OptionChainEntry:
    """Single option in a chain."""
    strike: float
    expiry: date
    option_type: str  # "call" or "put"
    bid: float = 0.0
    ask: float = 0.0
    last: float = 0.0
    implied_vol: float = 0.0
    volume: int = 0
    open_interest: int = 0


@dataclass
class OptionChainSnapshot:
    """Full option chain for an underlying."""
    underlying: str
    spot: float
    entries: List[OptionChainEntry] = field(default_factory=list)
    source: str = ""


class MarketDataProvider(ABC):
    """Abstract base class for market data providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name (e.g. 'openbb', 'yfinance')."""
        ...

    @abstractmethod
    def get_equity_spot(self, symbol: str) -> Optional[EquitySnapshot]:
        """Get current equity price."""
        ...

    @abstractmethod
    def get_equity_history(
        self, symbol: str, start: date, end: date
    ) -> List[Dict[str, Any]]:
        """Get historical OHLCV data."""
        ...

    @abstractmethod
    def get_fx_rate(self, pair: str) -> Optional[FXSnapshot]:
        """Get current FX rate (e.g. 'EURUSD')."""
        ...

    @abstractmethod
    def get_yield_curve(
        self, currency: str = "USD", curve_date: Optional[date] = None
    ) -> Optional[YieldCurveSnapshot]:
        """Get yield curve (Treasury rates)."""
        ...

    @abstractmethod
    def get_option_chain(
        self, symbol: str, expiry: Optional[date] = None
    ) -> Optional[OptionChainSnapshot]:
        """Get option chain for an underlying."""
        ...

    def is_available(self) -> bool:
        """Check if this provider is installed and configured."""
        return True
