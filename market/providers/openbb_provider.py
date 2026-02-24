"""
OpenBB market data provider.

Uses the OpenBB Platform (pip install openbb) to fetch:
- Equity prices (spot + historical)
- FX rates
- Treasury yield curves (via FRED)
- Option chains

Requires API keys for some providers (FRED for yield curves).
Free providers (yfinance backend) work without keys.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from market.providers import (
    EquitySnapshot, FXSnapshot, MarketDataProvider,
    OptionChainEntry, OptionChainSnapshot,
    YieldCurvePoint, YieldCurveSnapshot,
)

logger = logging.getLogger(__name__)


class OpenBBProvider(MarketDataProvider):
    """OpenBB Platform data provider."""

    def __init__(self):
        self._obb = None

    @property
    def name(self) -> str:
        return "openbb"

    def _get_obb(self):
        """Lazy import — openbb is heavy, only load when needed."""
        if self._obb is None:
            try:
                from openbb import obb
                self._obb = obb
            except ImportError:
                raise ImportError(
                    "OpenBB not installed. Run: pip install openbb"
                )
        return self._obb

    def is_available(self) -> bool:
        try:
            self._get_obb()
            return True
        except ImportError:
            return False

    def get_equity_spot(self, symbol: str) -> Optional[EquitySnapshot]:
        """Get current equity price via OpenBB."""
        try:
            obb = self._get_obb()
            # Use yfinance provider (free, no API key)
            result = obb.equity.price.quote(symbol, provider="yfinance")
            data = result.results
            if not data:
                return None

            # Handle single result or list
            item = data[0] if isinstance(data, list) else data

            spot = getattr(item, "last_price", None) or getattr(item, "regular_market_price", None) or 0
            prev = getattr(item, "prev_close", None) or getattr(item, "previous_close", None) or 0
            vol = getattr(item, "volume", 0) or 0

            change_pct = 0.0
            if prev and prev > 0:
                change_pct = (spot - prev) / prev * 100

            return EquitySnapshot(
                symbol=symbol,
                spot=float(spot),
                prev_close=float(prev),
                change_pct=round(change_pct, 2),
                volume=int(vol),
                timestamp=datetime.now(),
                source="openbb/yfinance",
            )
        except Exception as e:
            logger.warning(f"OpenBB equity quote failed for {symbol}: {e}")
            return None

    def get_equity_history(
        self, symbol: str, start: date, end: date
    ) -> List[Dict[str, Any]]:
        """Get historical OHLCV data."""
        try:
            obb = self._get_obb()
            result = obb.equity.price.historical(
                symbol,
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                provider="yfinance",
            )
            df = result.to_dataframe()
            return df.reset_index().to_dict("records")
        except Exception as e:
            logger.warning(f"OpenBB equity history failed for {symbol}: {e}")
            return []

    def get_fx_rate(self, pair: str) -> Optional[FXSnapshot]:
        """Get FX rate. pair format: 'EURUSD'."""
        try:
            obb = self._get_obb()
            # OpenBB uses "EUR/USD" format
            formatted = f"{pair[:3]}/{pair[3:6]}"
            result = obb.currency.price.historical(
                formatted,
                provider="yfinance",
            )
            df = result.to_dataframe()
            if df.empty:
                return None

            last_row = df.iloc[-1]
            rate = float(last_row.get("close", 0))

            return FXSnapshot(
                pair=pair,
                rate=rate,
                timestamp=datetime.now(),
                source="openbb/yfinance",
            )
        except Exception as e:
            logger.warning(f"OpenBB FX rate failed for {pair}: {e}")
            return None

    def get_yield_curve(
        self, currency: str = "USD", curve_date: Optional[date] = None
    ) -> Optional[YieldCurveSnapshot]:
        """Get Treasury yield curve via FRED or federal_reserve."""
        try:
            obb = self._get_obb()

            kwargs = {}
            if curve_date:
                kwargs["date"] = curve_date.isoformat()

            # Try federal_reserve first (no API key needed)
            try:
                result = obb.fixedincome.government.yield_curve(
                    provider="federal_reserve", **kwargs
                )
            except Exception:
                # Fallback to FRED (needs API key)
                result = obb.fixedincome.government.yield_curve(
                    provider="fred", **kwargs
                )

            df = result.to_dataframe()
            if df.empty:
                return None

            points = []
            for _, row in df.iterrows():
                maturity = str(row.get("maturity", ""))
                rate_val = row.get("rate", 0)
                mat_years = row.get("maturity_years", 0)

                if rate_val and float(rate_val) > 0:
                    points.append(YieldCurvePoint(
                        maturity=maturity,
                        maturity_years=float(mat_years) if mat_years else 0,
                        rate=float(rate_val) / 100,  # Convert % to decimal
                    ))

            if not points:
                return None

            return YieldCurveSnapshot(
                currency=currency,
                curve_date=curve_date or date.today(),
                points=sorted(points, key=lambda p: p.maturity_years),
                source="openbb/federal_reserve",
            )
        except Exception as e:
            logger.warning(f"OpenBB yield curve failed for {currency}: {e}")
            return None

    def get_option_chain(
        self, symbol: str, expiry: Optional[date] = None
    ) -> Optional[OptionChainSnapshot]:
        """Get option chain data."""
        try:
            obb = self._get_obb()
            result = obb.derivatives.options.chains(
                symbol, provider="yfinance"
            )
            df = result.to_dataframe()
            if df.empty:
                return None

            # Get spot price
            spot_data = self.get_equity_spot(symbol)
            spot = spot_data.spot if spot_data else 0

            entries = []
            for _, row in df.iterrows():
                exp = row.get("expiration")
                if expiry and exp:
                    row_exp = exp.date() if isinstance(exp, datetime) else exp
                    if row_exp != expiry:
                        continue

                entries.append(OptionChainEntry(
                    strike=float(row.get("strike", 0)),
                    expiry=exp.date() if isinstance(exp, datetime) else exp,
                    option_type=str(row.get("option_type", "")).lower(),
                    bid=float(row.get("bid", 0) or 0),
                    ask=float(row.get("ask", 0) or 0),
                    last=float(row.get("last_price", 0) or 0),
                    implied_vol=float(row.get("implied_volatility", 0) or 0),
                    volume=int(row.get("volume", 0) or 0),
                    open_interest=int(row.get("open_interest", 0) or 0),
                ))

            return OptionChainSnapshot(
                underlying=symbol,
                spot=spot,
                entries=entries,
                source="openbb/yfinance",
            )
        except Exception as e:
            logger.warning(f"OpenBB option chain failed for {symbol}: {e}")
            return None
