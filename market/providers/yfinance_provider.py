"""
yfinance market data provider (fallback).

Direct yfinance integration as fallback when OpenBB isn't installed.
No API keys required. Covers equity and FX but not yield curves.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from market.providers import (
    EquitySnapshot, FXSnapshot, MarketDataProvider,
    OptionChainEntry, OptionChainSnapshot,
    YieldCurvePoint, YieldCurveSnapshot,
)

logger = logging.getLogger(__name__)


class YFinanceProvider(MarketDataProvider):
    """yfinance direct provider (fallback)."""

    def __init__(self):
        self._yf = None

    @property
    def name(self) -> str:
        return "yfinance"

    def _get_yf(self):
        if self._yf is None:
            try:
                import yfinance as yf
                self._yf = yf
            except ImportError:
                raise ImportError(
                    "yfinance not installed. Run: pip install yfinance"
                )
        return self._yf

    def is_available(self) -> bool:
        try:
            self._get_yf()
            return True
        except ImportError:
            return False

    def get_equity_spot(self, symbol: str) -> Optional[EquitySnapshot]:
        try:
            yf = self._get_yf()
            ticker = yf.Ticker(symbol)
            info = ticker.fast_info

            spot = float(info.get("lastPrice", 0) or info.get("last_price", 0))
            prev = float(info.get("previousClose", 0) or info.get("previous_close", 0))

            if spot == 0:
                # Fallback: get from recent history
                hist = ticker.history(period="2d")
                if not hist.empty:
                    spot = float(hist["Close"].iloc[-1])
                    if len(hist) > 1:
                        prev = float(hist["Close"].iloc[-2])

            change_pct = 0.0
            if prev and prev > 0:
                change_pct = (spot - prev) / prev * 100

            return EquitySnapshot(
                symbol=symbol,
                spot=spot,
                prev_close=prev,
                change_pct=round(change_pct, 2),
                volume=int(info.get("lastVolume", 0) or 0),
                timestamp=datetime.now(),
                source="yfinance",
            )
        except Exception as e:
            logger.warning(f"yfinance equity quote failed for {symbol}: {e}")
            return None

    def get_equity_history(
        self, symbol: str, start: date, end: date
    ) -> List[Dict[str, Any]]:
        try:
            yf = self._get_yf()
            ticker = yf.Ticker(symbol)
            df = ticker.history(start=start, end=end)
            return df.reset_index().to_dict("records")
        except Exception as e:
            logger.warning(f"yfinance equity history failed for {symbol}: {e}")
            return []

    def get_fx_rate(self, pair: str) -> Optional[FXSnapshot]:
        """Get FX rate. yfinance uses 'EURUSD=X' format."""
        try:
            yf = self._get_yf()
            yf_symbol = f"{pair}=X"
            ticker = yf.Ticker(yf_symbol)
            hist = ticker.history(period="2d")

            if hist.empty:
                return None

            rate = float(hist["Close"].iloc[-1])
            return FXSnapshot(
                pair=pair,
                rate=rate,
                timestamp=datetime.now(),
                source="yfinance",
            )
        except Exception as e:
            logger.warning(f"yfinance FX rate failed for {pair}: {e}")
            return None

    def get_yield_curve(
        self, currency: str = "USD", curve_date: Optional[date] = None
    ) -> Optional[YieldCurveSnapshot]:
        """Approximate USD yield curve from Treasury ETFs / FRED symbols.

        This is a rough approximation using Treasury yield tickers.
        For production use, prefer OpenBB with FRED API key.
        """
        try:
            yf = self._get_yf()

            # Treasury yield symbols on yfinance
            tenor_map = {
                "^IRX": ("3M", 0.25),    # 13-week T-bill
                "^FVX": ("5Y", 5.0),     # 5-year Treasury
                "^TNX": ("10Y", 10.0),   # 10-year Treasury
                "^TYX": ("30Y", 30.0),   # 30-year Treasury
            }

            points = []
            for yf_sym, (tenor, years) in tenor_map.items():
                try:
                    ticker = yf.Ticker(yf_sym)
                    hist = ticker.history(period="5d")
                    if not hist.empty:
                        rate = float(hist["Close"].iloc[-1]) / 100  # % to decimal
                        points.append(YieldCurvePoint(
                            maturity=tenor,
                            maturity_years=years,
                            rate=rate,
                        ))
                except Exception:
                    continue

            if not points:
                return None

            return YieldCurveSnapshot(
                currency="USD",
                curve_date=curve_date or date.today(),
                points=sorted(points, key=lambda p: p.maturity_years),
                source="yfinance/treasury",
            )
        except Exception as e:
            logger.warning(f"yfinance yield curve failed: {e}")
            return None

    def get_option_chain(
        self, symbol: str, expiry: Optional[date] = None
    ) -> Optional[OptionChainSnapshot]:
        try:
            yf = self._get_yf()
            ticker = yf.Ticker(symbol)

            # Get spot
            spot_data = self.get_equity_spot(symbol)
            spot = spot_data.spot if spot_data else 0

            if expiry:
                exp_str = expiry.isoformat()
                chain = ticker.option_chain(exp_str)
            else:
                # Use nearest expiry
                expirations = ticker.options
                if not expirations:
                    return None
                chain = ticker.option_chain(expirations[0])
                expiry = date.fromisoformat(expirations[0])

            entries = []
            for _, row in chain.calls.iterrows():
                entries.append(OptionChainEntry(
                    strike=float(row.get("strike", 0)),
                    expiry=expiry,
                    option_type="call",
                    bid=float(row.get("bid", 0) or 0),
                    ask=float(row.get("ask", 0) or 0),
                    last=float(row.get("lastPrice", 0) or 0),
                    implied_vol=float(row.get("impliedVolatility", 0) or 0),
                    volume=int(row.get("volume", 0) or 0),
                    open_interest=int(row.get("openInterest", 0) or 0),
                ))

            for _, row in chain.puts.iterrows():
                entries.append(OptionChainEntry(
                    strike=float(row.get("strike", 0)),
                    expiry=expiry,
                    option_type="put",
                    bid=float(row.get("bid", 0) or 0),
                    ask=float(row.get("ask", 0) or 0),
                    last=float(row.get("lastPrice", 0) or 0),
                    implied_vol=float(row.get("impliedVolatility", 0) or 0),
                    volume=int(row.get("volume", 0) or 0),
                    open_interest=int(row.get("openInterest", 0) or 0),
                ))

            return OptionChainSnapshot(
                underlying=symbol,
                spot=spot,
                entries=entries,
                source="yfinance",
            )
        except Exception as e:
            logger.warning(f"yfinance option chain failed for {symbol}: {e}")
            return None
