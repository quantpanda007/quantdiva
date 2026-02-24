"""
Asset universe configuration.

Defines which symbols, pairs, and currencies to track historically.
Edit this file to customize what data is fetched and stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class AssetUniverse:
    """Configurable asset universe for historical data collection."""

    # Equity tickers (US stocks + major ETFs)
    equity: List[str] = field(default_factory=lambda: [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
        "JPM", "GS", "BAC",
        "SPY", "QQQ", "IWM", "DIA",
    ])

    # FX pairs
    fx: List[str] = field(default_factory=lambda: [
        "EURUSD", "GBPUSD", "USDJPY", "AUDUSD",
        "USDCHF", "USDCAD", "NZDUSD",
    ])

    # Yield curve currencies
    yield_curves: List[str] = field(default_factory=lambda: [
        "USD",
    ])

    # Option chain underlyings (subset of equity — chains are expensive)
    option_chains: List[str] = field(default_factory=lambda: [
        "AAPL", "MSFT", "SPY", "QQQ",
    ])

    # CDS reference entities (empty for now — needs paid data source)
    cds_entities: List[str] = field(default_factory=list)


# Default lookback for initial data fetch
DEFAULT_LOOKBACK_DAYS = 365  # 1 year of history

# Schedule configuration (24hr format, US/Eastern)
SCHEDULE = {
    "time": "18:30",          # 6:30 PM EST — after US market close
    "timezone": "US/Eastern",
    "enabled": True,
}

# Singleton
universe = AssetUniverse()
