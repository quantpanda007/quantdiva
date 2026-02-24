"""
Market Data Service.

Orchestrates multiple market data providers with:
- Priority-based fallback (OpenBB → yfinance)
- In-memory TTL cache (configurable, default 60s)
- Unified API for the pricing engine

Usage:
    from market.providers.market_data_service import market_data_service

    # Get live equity price
    snap = market_data_service.get_equity_spot("AAPL")

    # Get yield curve
    curve = market_data_service.get_yield_curve("USD")

    # Build MarketEnvironment from live data
    env = market_data_service.build_market_env(
        underlying="AAPL", currency="USD"
    )
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from market.providers import (
    EquitySnapshot, FXSnapshot, MarketDataProvider,
    OptionChainSnapshot, YieldCurveSnapshot,
)

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """TTL cache entry."""
    data: Any
    timestamp: float  # time.time()
    ttl: float = 60.0  # seconds

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.timestamp) > self.ttl


class MarketDataService:
    """Unified market data service with provider fallback and caching.

    Tries providers in priority order. First successful result wins.
    Results are cached with configurable TTL.
    """

    def __init__(self, cache_ttl: float = 60.0):
        self._providers: List[MarketDataProvider] = []
        self._cache: Dict[str, CacheEntry] = {}
        self._cache_ttl = cache_ttl
        self._initialize_providers()

    def _initialize_providers(self):
        """Load available providers in priority order."""
        # Try OpenBB first
        try:
            from market.providers.openbb_provider import OpenBBProvider
            provider = OpenBBProvider()
            if provider.is_available():
                self._providers.append(provider)
                logger.info("OpenBB provider loaded")
        except Exception as e:
            logger.info(f"OpenBB provider not available: {e}")

        # yfinance as fallback
        try:
            from market.providers.yfinance_provider import YFinanceProvider
            provider = YFinanceProvider()
            if provider.is_available():
                self._providers.append(provider)
                logger.info("yfinance provider loaded")
        except Exception as e:
            logger.info(f"yfinance provider not available: {e}")

        if not self._providers:
            logger.warning(
                "No market data providers available. "
                "Install openbb or yfinance for live data."
            )

    @property
    def available_providers(self) -> List[str]:
        return [p.name for p in self._providers]

    def _get_cached(self, key: str) -> Optional[Any]:
        entry = self._cache.get(key)
        if entry and not entry.is_expired:
            return entry.data
        return None

    def _set_cached(self, key: str, data: Any, ttl: Optional[float] = None):
        self._cache[key] = CacheEntry(
            data=data,
            timestamp=time.time(),
            ttl=ttl or self._cache_ttl,
        )

    def clear_cache(self):
        """Clear all cached data."""
        self._cache.clear()

    # ---------------------------------------------------------------
    # Equity
    # ---------------------------------------------------------------

    def get_equity_spot(self, symbol: str) -> Optional[EquitySnapshot]:
        """Get current equity price with fallback."""
        key = f"eq_spot:{symbol}"
        cached = self._get_cached(key)
        if cached:
            return cached

        for provider in self._providers:
            try:
                result = provider.get_equity_spot(symbol)
                if result and result.spot > 0:
                    self._set_cached(key, result)
                    return result
            except Exception as e:
                logger.debug(f"{provider.name} failed for {symbol}: {e}")
                continue

        return None

    def get_equity_history(
        self, symbol: str, start: date, end: date
    ) -> List[Dict[str, Any]]:
        """Get historical equity prices."""
        key = f"eq_hist:{symbol}:{start}:{end}"
        cached = self._get_cached(key)
        if cached:
            return cached

        for provider in self._providers:
            try:
                result = provider.get_equity_history(symbol, start, end)
                if result:
                    self._set_cached(key, result, ttl=300)  # 5 min cache
                    return result
            except Exception:
                continue

        return []

    # ---------------------------------------------------------------
    # FX
    # ---------------------------------------------------------------

    def get_fx_rate(self, pair: str) -> Optional[FXSnapshot]:
        """Get FX rate with fallback. pair: 'EURUSD'."""
        key = f"fx:{pair}"
        cached = self._get_cached(key)
        if cached:
            return cached

        for provider in self._providers:
            try:
                result = provider.get_fx_rate(pair)
                if result and result.rate > 0:
                    self._set_cached(key, result)
                    return result
            except Exception:
                continue

        return None

    # ---------------------------------------------------------------
    # Yield Curve
    # ---------------------------------------------------------------

    def get_yield_curve(
        self, currency: str = "USD", curve_date: Optional[date] = None
    ) -> Optional[YieldCurveSnapshot]:
        """Get yield curve with fallback."""
        key = f"yc:{currency}:{curve_date or 'latest'}"
        cached = self._get_cached(key)
        if cached:
            return cached

        for provider in self._providers:
            try:
                result = provider.get_yield_curve(currency, curve_date)
                if result and result.points:
                    self._set_cached(key, result, ttl=300)
                    return result
            except Exception:
                continue

        return None

    # ---------------------------------------------------------------
    # Option Chains
    # ---------------------------------------------------------------

    def get_option_chain(
        self, symbol: str, expiry: Optional[date] = None
    ) -> Optional[OptionChainSnapshot]:
        """Get option chain with fallback."""
        key = f"chain:{symbol}:{expiry or 'nearest'}"
        cached = self._get_cached(key)
        if cached:
            return cached

        for provider in self._providers:
            try:
                result = provider.get_option_chain(symbol, expiry)
                if result and result.entries:
                    self._set_cached(key, result, ttl=120)
                    return result
            except Exception:
                continue

        return None

    # ---------------------------------------------------------------
    # Build MarketEnvironment from live data
    # ---------------------------------------------------------------

    def build_market_env_data(
        self,
        underlying: Optional[str] = None,
        ccy_pair: Optional[str] = None,
        currency: str = "USD",
    ) -> Dict[str, Any]:
        """Build market data dict compatible with our API.

        Returns a dict that can be sent to the pricing endpoint,
        populated with live data from providers.
        """
        result = {
            "pricing_date": date.today().isoformat(),
            "rate": 0.045,  # default
            "underlyings": {},
        }

        # Yield curve → extract a single rate
        yc = self.get_yield_curve(currency)
        if yc and yc.points:
            # Use 5Y rate as default, fallback to whatever's available
            for target in [5.0, 10.0, 2.0, 1.0]:
                for pt in yc.points:
                    if abs(pt.maturity_years - target) < 0.5:
                        result["rate"] = round(pt.rate, 6)
                        break
                if result["rate"] != 0.045:
                    break

            # Store full curve for advanced use
            result["yield_curve"] = [
                {"maturity": p.maturity, "years": p.maturity_years, "rate": p.rate}
                for p in yc.points
            ]

        # Equity spot
        if underlying:
            snap = self.get_equity_spot(underlying)
            if snap:
                result["underlyings"][underlying] = {
                    "spot": snap.spot,
                    "vol": 0.25,  # default, would need option chain for implied
                    "div_yield": 0.005,
                }

                # Try to get implied vol from option chain
                chain = self.get_option_chain(underlying)
                if chain and chain.entries:
                    # Get ATM implied vol (nearest strike to spot)
                    atm_entries = sorted(
                        [e for e in chain.entries if e.implied_vol > 0],
                        key=lambda e: abs(e.strike - snap.spot),
                    )
                    if atm_entries:
                        result["underlyings"][underlying]["vol"] = round(
                            atm_entries[0].implied_vol, 4
                        )

        # FX rate
        if ccy_pair:
            fx = self.get_fx_rate(ccy_pair)
            if fx:
                result["underlyings"][ccy_pair] = {
                    "spot": fx.rate,
                    "vol": 0.08,
                    "div_yield": 0.0,
                }

        return result

    def status(self) -> Dict[str, Any]:
        """Return provider status for the frontend."""
        providers = []
        for p in self._providers:
            providers.append({
                "name": p.name,
                "available": p.is_available(),
            })

        return {
            "providers": providers,
            "cache_size": len(self._cache),
            "cache_ttl": self._cache_ttl,
        }


# Singleton instance
market_data_service = MarketDataService()
