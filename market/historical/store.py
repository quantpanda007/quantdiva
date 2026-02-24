"""
SQLite storage engine for historical market data.

Single-file database, zero configuration.
Location: {project_root}/data/market_data.db

All tables use (symbol/pair/currency, date) as natural keys
with ON CONFLICT REPLACE for idempotent inserts.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from market.historical import (
    HistoricalBar, HistoricalCDSSpread, HistoricalFXRate,
    HistoricalOptionSnap, HistoricalYieldPoint,
)

logger = logging.getLogger(__name__)

# Default DB path — relative to project root
_DEFAULT_DB_DIR = Path(__file__).resolve().parents[2] / "data"
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "market_data.db"


class MarketDataStore:
    """SQLite storage for historical market data."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_tables()

    @contextmanager
    def _conn(self):
        """Context-managed connection with WAL mode for concurrent reads."""
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_tables(self):
        """Create tables if they don't exist."""
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS equity_prices (
                    symbol      TEXT NOT NULL,
                    date        TEXT NOT NULL,
                    open        REAL,
                    high        REAL,
                    low         REAL,
                    close       REAL NOT NULL,
                    volume      INTEGER DEFAULT 0,
                    source      TEXT DEFAULT '',
                    updated_at  TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (symbol, date)
                );

                CREATE TABLE IF NOT EXISTS fx_rates (
                    pair        TEXT NOT NULL,
                    date        TEXT NOT NULL,
                    rate        REAL NOT NULL,
                    source      TEXT DEFAULT '',
                    updated_at  TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (pair, date)
                );

                CREATE TABLE IF NOT EXISTS yield_curves (
                    currency    TEXT NOT NULL,
                    date        TEXT NOT NULL,
                    tenor       TEXT NOT NULL,
                    tenor_years REAL NOT NULL,
                    rate        REAL NOT NULL,
                    source      TEXT DEFAULT '',
                    updated_at  TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (currency, date, tenor)
                );

                CREATE TABLE IF NOT EXISTS option_chains (
                    underlying  TEXT NOT NULL,
                    snap_date   TEXT NOT NULL,
                    expiry      TEXT NOT NULL,
                    strike      REAL NOT NULL,
                    option_type TEXT NOT NULL,
                    bid         REAL DEFAULT 0,
                    ask         REAL DEFAULT 0,
                    last        REAL DEFAULT 0,
                    implied_vol REAL DEFAULT 0,
                    volume      INTEGER DEFAULT 0,
                    open_interest INTEGER DEFAULT 0,
                    source      TEXT DEFAULT '',
                    updated_at  TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (underlying, snap_date, expiry, strike, option_type)
                );

                CREATE TABLE IF NOT EXISTS cds_spreads (
                    entity      TEXT NOT NULL,
                    date        TEXT NOT NULL,
                    tenor       TEXT NOT NULL,
                    spread      REAL NOT NULL,
                    recovery    REAL DEFAULT 0.40,
                    source      TEXT DEFAULT '',
                    updated_at  TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (entity, date, tenor)
                );

                CREATE TABLE IF NOT EXISTS metadata (
                    key         TEXT PRIMARY KEY,
                    value       TEXT,
                    updated_at  TEXT DEFAULT (datetime('now'))
                );

                -- Indexes for common queries
                CREATE INDEX IF NOT EXISTS idx_equity_symbol ON equity_prices(symbol);
                CREATE INDEX IF NOT EXISTS idx_equity_date ON equity_prices(date);
                CREATE INDEX IF NOT EXISTS idx_fx_pair ON fx_rates(pair);
                CREATE INDEX IF NOT EXISTS idx_yc_currency ON yield_curves(currency, date);
            """)

    # ── Equity ───────────────────────────────────────────────

    def insert_equity_bars(self, bars: List[HistoricalBar]) -> int:
        """Insert/replace equity price bars. Returns count inserted."""
        if not bars:
            return 0
        with self._conn() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO equity_prices
                   (symbol, date, open, high, low, close, volume, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [(b.symbol, b.date.isoformat(), b.open, b.high, b.low,
                  b.close, b.volume, b.source) for b in bars],
            )
        return len(bars)

    def get_equity_history(
        self, symbol: str, start: Optional[date] = None, end: Optional[date] = None
    ) -> List[HistoricalBar]:
        """Query equity price history."""
        sql = "SELECT * FROM equity_prices WHERE symbol = ?"
        params: list = [symbol]
        if start:
            sql += " AND date >= ?"
            params.append(start.isoformat())
        if end:
            sql += " AND date <= ?"
            params.append(end.isoformat())
        sql += " ORDER BY date"

        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            HistoricalBar(
                symbol=r["symbol"], date=date.fromisoformat(r["date"]),
                open=r["open"], high=r["high"], low=r["low"],
                close=r["close"], volume=r["volume"], source=r["source"],
            ) for r in rows
        ]

    def get_equity_latest(self, symbol: str) -> Optional[HistoricalBar]:
        """Get most recent bar for a symbol."""
        with self._conn() as conn:
            r = conn.execute(
                "SELECT * FROM equity_prices WHERE symbol = ? ORDER BY date DESC LIMIT 1",
                [symbol],
            ).fetchone()
        if not r:
            return None
        return HistoricalBar(
            symbol=r["symbol"], date=date.fromisoformat(r["date"]),
            open=r["open"], high=r["high"], low=r["low"],
            close=r["close"], volume=r["volume"], source=r["source"],
        )

    # ── FX ───────────────────────────────────────────────────

    def insert_fx_rates(self, rates: List[HistoricalFXRate]) -> int:
        if not rates:
            return 0
        with self._conn() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO fx_rates (pair, date, rate, source)
                   VALUES (?, ?, ?, ?)""",
                [(r.pair, r.date.isoformat(), r.rate, r.source) for r in rates],
            )
        return len(rates)

    def get_fx_history(
        self, pair: str, start: Optional[date] = None, end: Optional[date] = None
    ) -> List[HistoricalFXRate]:
        sql = "SELECT * FROM fx_rates WHERE pair = ?"
        params: list = [pair]
        if start:
            sql += " AND date >= ?"
            params.append(start.isoformat())
        if end:
            sql += " AND date <= ?"
            params.append(end.isoformat())
        sql += " ORDER BY date"

        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            HistoricalFXRate(
                pair=r["pair"], date=date.fromisoformat(r["date"]),
                rate=r["rate"], source=r["source"],
            ) for r in rows
        ]

    # ── Yield Curves ─────────────────────────────────────────

    def insert_yield_points(self, points: List[HistoricalYieldPoint]) -> int:
        if not points:
            return 0
        with self._conn() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO yield_curves
                   (currency, date, tenor, tenor_years, rate, source)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [(p.currency, p.date.isoformat(), p.tenor,
                  p.tenor_years, p.rate, p.source) for p in points],
            )
        return len(points)

    def get_yield_curve(
        self, currency: str, curve_date: Optional[date] = None
    ) -> List[HistoricalYieldPoint]:
        """Get yield curve for a date. If no date, returns latest."""
        if curve_date:
            sql = "SELECT * FROM yield_curves WHERE currency = ? AND date = ? ORDER BY tenor_years"
            params = [currency, curve_date.isoformat()]
        else:
            sql = """SELECT * FROM yield_curves
                     WHERE currency = ? AND date = (
                         SELECT MAX(date) FROM yield_curves WHERE currency = ?
                     ) ORDER BY tenor_years"""
            params = [currency, currency]

        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            HistoricalYieldPoint(
                currency=r["currency"], date=date.fromisoformat(r["date"]),
                tenor=r["tenor"], tenor_years=r["tenor_years"],
                rate=r["rate"], source=r["source"],
            ) for r in rows
        ]

    def get_yield_curve_dates(self, currency: str) -> List[date]:
        """Get all dates with yield curve data."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT date FROM yield_curves WHERE currency = ? ORDER BY date",
                [currency],
            ).fetchall()
        return [date.fromisoformat(r["date"]) for r in rows]

    # ── Option Chains ────────────────────────────────────────

    def insert_option_snaps(self, snaps: List[HistoricalOptionSnap]) -> int:
        if not snaps:
            return 0
        with self._conn() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO option_chains
                   (underlying, snap_date, expiry, strike, option_type,
                    bid, ask, last, implied_vol, volume, open_interest, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [(s.underlying, s.snap_date.isoformat(), s.expiry.isoformat(),
                  s.strike, s.option_type, s.bid, s.ask, s.last,
                  s.implied_vol, s.volume, s.open_interest, s.source)
                 for s in snaps],
            )
        return len(snaps)

    # ── CDS Spreads ──────────────────────────────────────────

    def insert_cds_spreads(self, spreads: List[HistoricalCDSSpread]) -> int:
        if not spreads:
            return 0
        with self._conn() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO cds_spreads
                   (entity, date, tenor, spread, recovery, source)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [(s.entity, s.date.isoformat(), s.tenor,
                  s.spread, s.recovery, s.source) for s in spreads],
            )
        return len(spreads)

    # ── Metadata ─────────────────────────────────────────────

    def set_metadata(self, key: str, value: str):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value, updated_at) VALUES (?, ?, datetime('now'))",
                [key, value],
            )

    def get_metadata(self, key: str) -> Optional[str]:
        with self._conn() as conn:
            r = conn.execute("SELECT value FROM metadata WHERE key = ?", [key]).fetchone()
        return r["value"] if r else None

    def get_last_fetch(self, asset_class: str, symbol: str = "") -> Optional[date]:
        """Get last fetch date for an asset."""
        key = f"last_fetch:{asset_class}:{symbol}" if symbol else f"last_fetch:{asset_class}"
        val = self.get_metadata(key)
        return date.fromisoformat(val) if val else None

    def set_last_fetch(self, asset_class: str, symbol: str = "", fetch_date: Optional[date] = None):
        key = f"last_fetch:{asset_class}:{symbol}" if symbol else f"last_fetch:{asset_class}"
        self.set_metadata(key, (fetch_date or date.today()).isoformat())

    # ── Stats ────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Get row counts and date ranges for all tables."""
        stats = {}
        tables = {
            "equity_prices": ("symbol", "date"),
            "fx_rates": ("pair", "date"),
            "yield_curves": ("currency", "date"),
            "option_chains": ("underlying", "snap_date"),
            "cds_spreads": ("entity", "date"),
        }
        with self._conn() as conn:
            for table, (sym_col, date_col) in tables.items():
                row = conn.execute(f"""
                    SELECT COUNT(*) as cnt,
                           COUNT(DISTINCT {sym_col}) as symbols,
                           MIN({date_col}) as min_date,
                           MAX({date_col}) as max_date
                    FROM {table}
                """).fetchone()
                stats[table] = {
                    "rows": row["cnt"],
                    "symbols": row["symbols"],
                    "date_range": f"{row['min_date'] or 'N/A'} to {row['max_date'] or 'N/A'}",
                }

        stats["db_size_mb"] = round(os.path.getsize(self.db_path) / (1024 * 1024), 2)
        return stats


# Singleton
store = MarketDataStore()
