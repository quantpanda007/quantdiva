"""
Historical data fetcher.

Orchestrates fetching from market data providers (OpenBB / yfinance)
and storing results in SQLite. Handles deduplication via last-fetch
tracking and incremental updates.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from typing import List, Optional

from market.historical import (
    HistoricalBar, HistoricalFXRate, HistoricalOptionSnap,
    HistoricalYieldPoint, RefreshStatus,
)
from market.historical.assets import DEFAULT_LOOKBACK_DAYS, universe
from market.historical.store import store

logger = logging.getLogger(__name__)


class HistoricalFetcher:
    """Fetches and stores historical market data."""

    def __init__(self):
        self._provider = None

    def _get_provider(self):
        """Get the best available live provider."""
        if self._provider is None:
            # Try OpenBB first, then yfinance
            try:
                from market.providers.openbb_provider import OpenBBProvider
                p = OpenBBProvider()
                if p.is_available():
                    self._provider = p
                    return self._provider
            except Exception:
                pass

            try:
                from market.providers.yfinance_provider import YFinanceProvider
                p = YFinanceProvider()
                if p.is_available():
                    self._provider = p
                    return self._provider
            except Exception:
                pass

            raise RuntimeError("No market data provider available")
        return self._provider

    # ── Equity ───────────────────────────────────────────────

    def refresh_equity(
        self, symbols: Optional[List[str]] = None, lookback_days: int = DEFAULT_LOOKBACK_DAYS
    ) -> RefreshStatus:
        """Fetch and store equity price history."""
        status = RefreshStatus(asset_class="equity", started_at=datetime.now())
        symbols = symbols or universe.equity
        provider = self._get_provider()

        for symbol in symbols:
            try:
                # Determine start date: last fetch or full lookback
                last = store.get_last_fetch("equity", symbol)
                if last:
                    start = last + timedelta(days=1)
                else:
                    start = date.today() - timedelta(days=lookback_days)

                end = date.today()
                if start > end:
                    status.rows_skipped += 1
                    continue

                history = provider.get_equity_history(symbol, start, end)
                if not history:
                    continue

                bars = []
                for row in history:
                    try:
                        row_date = row.get("Date") or row.get("date")
                        if hasattr(row_date, "date"):
                            row_date = row_date.date()
                        elif isinstance(row_date, str):
                            row_date = date.fromisoformat(row_date[:10])

                        bars.append(HistoricalBar(
                            symbol=symbol,
                            date=row_date,
                            open=float(row.get("Open", row.get("open", 0))),
                            high=float(row.get("High", row.get("high", 0))),
                            low=float(row.get("Low", row.get("low", 0))),
                            close=float(row.get("Close", row.get("close", 0))),
                            volume=int(row.get("Volume", row.get("volume", 0)) or 0),
                            source=provider.name,
                        ))
                    except Exception as e:
                        logger.debug(f"Skipping row for {symbol}: {e}")
                        continue

                inserted = store.insert_equity_bars(bars)
                store.set_last_fetch("equity", symbol)
                status.rows_inserted += inserted
                status.symbols_refreshed += 1
                logger.info(f"Equity {symbol}: {inserted} bars stored")

            except Exception as e:
                status.errors.append(f"{symbol}: {str(e)[:80]}")
                logger.warning(f"Failed to fetch equity {symbol}: {e}")

        status.finished_at = datetime.now()
        status.duration_seconds = (status.finished_at - status.started_at).total_seconds()
        return status

    # ── FX ───────────────────────────────────────────────────

    def refresh_fx(
        self, pairs: Optional[List[str]] = None, lookback_days: int = DEFAULT_LOOKBACK_DAYS
    ) -> RefreshStatus:
        """Fetch and store FX rate history."""
        status = RefreshStatus(asset_class="fx", started_at=datetime.now())
        pairs = pairs or universe.fx
        provider = self._get_provider()

        for pair in pairs:
            try:
                last = store.get_last_fetch("fx", pair)
                if last:
                    start = last + timedelta(days=1)
                else:
                    start = date.today() - timedelta(days=lookback_days)

                end = date.today()
                if start > end:
                    status.rows_skipped += 1
                    continue

                # Try multiple ticker formats for FX
                # yfinance: EURUSD=X, OpenBB equity history: EUR/USD
                history = None
                fx_tickers = [
                    f"{pair}=X",                        # yfinance format: EURUSD=X
                    f"{pair[:3]}{pair[3:]}=X",          # same, explicit
                    f"{pair[:3]}/{pair[3:]}",            # OpenBB format: EUR/USD
                ]

                for ticker in fx_tickers:
                    try:
                        history = provider.get_equity_history(ticker, start, end)
                        if history:
                            break
                    except Exception:
                        continue

                if not history:
                    # Last resort: try yfinance directly
                    try:
                        import yfinance as yf
                        ticker_obj = yf.Ticker(f"{pair}=X")
                        df = ticker_obj.history(start=start, end=end)
                        if not df.empty:
                            history = df.reset_index().to_dict("records")
                    except Exception as e:
                        logger.warning(f"FX {pair}: all methods failed — {e}")
                        status.errors.append(f"{pair}: no data from any provider")
                        continue

                if not history:
                    continue

                rates = []
                for row in history:
                    try:
                        row_date = row.get("Date") or row.get("date")
                        if hasattr(row_date, "date"):
                            row_date = row_date.date()
                        elif isinstance(row_date, str):
                            row_date = date.fromisoformat(row_date[:10])

                        close = float(row.get("Close", row.get("close", 0)))
                        if close > 0:
                            rates.append(HistoricalFXRate(
                                pair=pair, date=row_date,
                                rate=close, source=provider.name,
                            ))
                    except Exception:
                        continue

                inserted = store.insert_fx_rates(rates)
                store.set_last_fetch("fx", pair)
                status.rows_inserted += inserted
                status.symbols_refreshed += 1
                logger.info(f"FX {pair}: {inserted} rates stored")

            except Exception as e:
                status.errors.append(f"{pair}: {str(e)[:80]}")
                logger.warning(f"Failed to fetch FX {pair}: {e}")

        status.finished_at = datetime.now()
        status.duration_seconds = (status.finished_at - status.started_at).total_seconds()
        return status

    # ── Yield Curves ─────────────────────────────────────────

    def refresh_yield_curves(
        self, currencies: Optional[List[str]] = None
    ) -> RefreshStatus:
        """Fetch and store latest yield curve."""
        status = RefreshStatus(asset_class="yield_curves", started_at=datetime.now())
        currencies = currencies or universe.yield_curves
        provider = self._get_provider()

        for ccy in currencies:
            try:
                yc = provider.get_yield_curve(ccy)
                if not yc or not yc.points:
                    continue

                points = [
                    HistoricalYieldPoint(
                        currency=ccy,
                        date=yc.curve_date,
                        tenor=p.maturity,
                        tenor_years=p.maturity_years,
                        rate=p.rate,
                        source=yc.source,
                    ) for p in yc.points
                ]

                inserted = store.insert_yield_points(points)
                store.set_last_fetch("yield_curves", ccy)
                status.rows_inserted += inserted
                status.symbols_refreshed += 1
                logger.info(f"Yield curve {ccy}: {inserted} points stored")

            except Exception as e:
                status.errors.append(f"{ccy}: {str(e)[:80]}")
                logger.warning(f"Failed to fetch yield curve {ccy}: {e}")

        status.finished_at = datetime.now()
        status.duration_seconds = (status.finished_at - status.started_at).total_seconds()
        return status

    # ── Option Chains ────────────────────────────────────────

    def refresh_option_chains(
        self, underlyings: Optional[List[str]] = None
    ) -> RefreshStatus:
        """Fetch and store option chain snapshots."""
        status = RefreshStatus(asset_class="option_chains", started_at=datetime.now())
        underlyings = underlyings or universe.option_chains
        provider = self._get_provider()

        for symbol in underlyings:
            try:
                chain = provider.get_option_chain(symbol)
                if not chain or not chain.entries:
                    continue

                snaps = [
                    HistoricalOptionSnap(
                        underlying=symbol,
                        snap_date=date.today(),
                        expiry=e.expiry,
                        strike=e.strike,
                        option_type=e.option_type,
                        bid=e.bid, ask=e.ask, last=e.last,
                        implied_vol=e.implied_vol,
                        volume=e.volume,
                        open_interest=e.open_interest,
                        source=chain.source,
                    ) for e in chain.entries
                ]

                inserted = store.insert_option_snaps(snaps)
                store.set_last_fetch("option_chains", symbol)
                status.rows_inserted += inserted
                status.symbols_refreshed += 1
                logger.info(f"Options {symbol}: {inserted} entries stored")

            except Exception as e:
                status.errors.append(f"{symbol}: {str(e)[:80]}")
                logger.warning(f"Failed to fetch options {symbol}: {e}")

        status.finished_at = datetime.now()
        status.duration_seconds = (status.finished_at - status.started_at).total_seconds()
        return status

    # ── Full Refresh ─────────────────────────────────────────

    def refresh_all(self, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> List[RefreshStatus]:
        """Refresh all asset classes."""
        results = []

        logger.info("=== Starting full market data refresh ===")
        t0 = time.time()

        results.append(self.refresh_equity(lookback_days=lookback_days))
        results.append(self.refresh_fx(lookback_days=lookback_days))
        results.append(self.refresh_yield_curves())
        results.append(self.refresh_option_chains())

        elapsed = time.time() - t0
        total_rows = sum(r.rows_inserted for r in results)
        total_errors = sum(len(r.errors) for r in results)
        logger.info(
            f"=== Refresh complete: {total_rows} rows, "
            f"{total_errors} errors, {elapsed:.1f}s ==="
        )

        return results


# Singleton
fetcher = HistoricalFetcher()