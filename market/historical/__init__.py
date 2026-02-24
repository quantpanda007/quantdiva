"""
Historical market data models.

Shared dataclasses used by store, fetcher, and API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional


@dataclass
class HistoricalBar:
    """Single OHLCV bar for equity or ETF."""
    symbol: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int = 0
    source: str = ""


@dataclass
class HistoricalFXRate:
    """Single daily FX rate."""
    pair: str
    date: date
    rate: float
    source: str = ""


@dataclass
class HistoricalYieldPoint:
    """Single yield curve point for a given date."""
    currency: str
    date: date
    tenor: str          # e.g. "3M", "2Y", "10Y"
    tenor_years: float  # e.g. 0.25, 2.0, 10.0
    rate: float         # decimal, e.g. 0.045
    source: str = ""


@dataclass
class HistoricalOptionSnap:
    """Single option chain entry snapshot."""
    underlying: str
    snap_date: date
    expiry: date
    strike: float
    option_type: str    # "call" / "put"
    bid: float = 0.0
    ask: float = 0.0
    last: float = 0.0
    implied_vol: float = 0.0
    volume: int = 0
    open_interest: int = 0
    source: str = ""


@dataclass
class HistoricalCDSSpread:
    """Single CDS spread observation."""
    entity: str         # reference entity name or ticker
    date: date
    tenor: str          # e.g. "5Y"
    spread: float       # decimal, e.g. 0.01 = 100bp
    recovery: float = 0.40
    source: str = ""


@dataclass
class RefreshStatus:
    """Status of a data refresh operation."""
    asset_class: str
    symbols_refreshed: int = 0
    rows_inserted: int = 0
    rows_skipped: int = 0
    errors: List[str] = field(default_factory=list)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_seconds: float = 0.0
