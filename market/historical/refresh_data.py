"""
Standalone market data refresh script.

Can be run manually or scheduled via OS (Windows Task Scheduler / cron).

Usage:
    # Full refresh (all asset classes)
    python -m market.historical.refresh_data --all

    # Specific asset classes
    python -m market.historical.refresh_data --equity --fx
    python -m market.historical.refresh_data --yield-curves --options

    # Custom lookback
    python -m market.historical.refresh_data --all --days 730

    # Show database stats
    python -m market.historical.refresh_data --stats

    # CSV import
    python -m market.historical.refresh_data --import-csv equity_data.csv --table equity_prices

Windows Task Scheduler setup:
    Program:   C:\\Users\\Abhishek\\...\\conda\\envs\\quantlib-pricing\\python.exe
    Arguments: -m market.historical.refresh_data --all
    Start in:  C:\\Users\\Abhishek\\Quantdiva\\quantlib-pricing
    Trigger:   Daily at 6:30 PM
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
import os
from datetime import date
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def print_status(status):
    """Pretty-print a RefreshStatus."""
    emoji = "✓" if not status.errors else "⚠"
    print(f"  {emoji} {status.asset_class.upper()}: "
          f"{status.symbols_refreshed} symbols, "
          f"{status.rows_inserted} rows inserted, "
          f"{status.rows_skipped} skipped"
          f"{f', {len(status.errors)} errors' if status.errors else ''}"
          f" ({status.duration_seconds:.1f}s)")
    for err in status.errors:
        print(f"    ✗ {err}")


def cmd_refresh(args):
    """Run data refresh."""
    from market.historical.fetcher import fetcher

    asset_classes = []
    if args.all or args.equity:
        asset_classes.append("equity")
    if args.all or args.fx:
        asset_classes.append("fx")
    if args.all or args.yield_curves:
        asset_classes.append("yield_curves")
    if args.all or args.options:
        asset_classes.append("options")

    if not asset_classes:
        print("No asset class selected. Use --all or --equity/--fx/--yield-curves/--options")
        return

    print(f"\n{'='*60}")
    print(f"  Market Data Refresh — {date.today()}")
    print(f"  Asset classes: {', '.join(asset_classes)}")
    print(f"  Lookback: {args.days} days")
    print(f"{'='*60}\n")

    results = []

    if "equity" in asset_classes:
        results.append(fetcher.refresh_equity(lookback_days=args.days))
    if "fx" in asset_classes:
        results.append(fetcher.refresh_fx(lookback_days=args.days))
    if "yield_curves" in asset_classes:
        results.append(fetcher.refresh_yield_curves())
    if "options" in asset_classes:
        results.append(fetcher.refresh_option_chains())

    print(f"\n{'─'*60}")
    print("  RESULTS")
    print(f"{'─'*60}")
    for status in results:
        print_status(status)

    total_rows = sum(r.rows_inserted for r in results)
    total_errors = sum(len(r.errors) for r in results)
    print(f"\n  Total: {total_rows} rows inserted, {total_errors} errors")
    print(f"{'='*60}\n")


def cmd_stats(args):
    """Show database statistics."""
    from market.historical.store import store

    stats = store.get_stats()

    print(f"\n{'='*60}")
    print(f"  Market Data Database")
    print(f"  Path: {store.db_path}")
    print(f"  Size: {stats['db_size_mb']} MB")
    print(f"{'='*60}\n")

    for table, info in stats.items():
        if table == "db_size_mb":
            continue
        print(f"  {table}:")
        print(f"    Rows:    {info['rows']:,}")
        print(f"    Symbols: {info['symbols']}")
        print(f"    Range:   {info['date_range']}")
        print()


def cmd_import_csv(args):
    """Import data from CSV file into a table."""
    from market.historical.store import store
    from market.historical import (
        HistoricalBar, HistoricalFXRate, HistoricalYieldPoint, HistoricalCDSSpread,
    )

    csv_path = Path(args.import_csv)
    if not csv_path.exists():
        print(f"File not found: {csv_path}")
        return

    table = args.table
    source = args.source or csv_path.stem

    print(f"\nImporting {csv_path} into {table} (source='{source}')...")

    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    count = 0

    if table == "equity_prices":
        bars = []
        for r in rows:
            try:
                bars.append(HistoricalBar(
                    symbol=r.get("symbol", r.get("Symbol", "")),
                    date=date.fromisoformat(r.get("date", r.get("Date", ""))[:10]),
                    open=float(r.get("open", r.get("Open", 0))),
                    high=float(r.get("high", r.get("High", 0))),
                    low=float(r.get("low", r.get("Low", 0))),
                    close=float(r.get("close", r.get("Close", 0))),
                    volume=int(float(r.get("volume", r.get("Volume", 0)) or 0)),
                    source=source,
                ))
            except Exception as e:
                logger.debug(f"Skipping row: {e}")
        count = store.insert_equity_bars(bars)

    elif table == "fx_rates":
        rates = []
        for r in rows:
            try:
                rates.append(HistoricalFXRate(
                    pair=r.get("pair", r.get("Pair", "")),
                    date=date.fromisoformat(r.get("date", r.get("Date", ""))[:10]),
                    rate=float(r.get("rate", r.get("Rate", r.get("close", r.get("Close", 0))))),
                    source=source,
                ))
            except Exception as e:
                logger.debug(f"Skipping row: {e}")
        count = store.insert_fx_rates(rates)

    elif table == "yield_curves":
        points = []
        for r in rows:
            try:
                points.append(HistoricalYieldPoint(
                    currency=r.get("currency", r.get("Currency", "USD")),
                    date=date.fromisoformat(r.get("date", r.get("Date", ""))[:10]),
                    tenor=r.get("tenor", r.get("Tenor", "")),
                    tenor_years=float(r.get("tenor_years", r.get("TenorYears", 0))),
                    rate=float(r.get("rate", r.get("Rate", 0))),
                    source=source,
                ))
            except Exception as e:
                logger.debug(f"Skipping row: {e}")
        count = store.insert_yield_points(points)

    elif table == "cds_spreads":
        spreads = []
        for r in rows:
            try:
                spreads.append(HistoricalCDSSpread(
                    entity=r.get("entity", r.get("Entity", "")),
                    date=date.fromisoformat(r.get("date", r.get("Date", ""))[:10]),
                    tenor=r.get("tenor", r.get("Tenor", "5Y")),
                    spread=float(r.get("spread", r.get("Spread", 0))),
                    recovery=float(r.get("recovery", r.get("Recovery", 0.40))),
                    source=source,
                ))
            except Exception as e:
                logger.debug(f"Skipping row: {e}")
        count = store.insert_cds_spreads(spreads)

    else:
        print(f"Unknown table: {table}")
        print("Valid tables: equity_prices, fx_rates, yield_curves, cds_spreads")
        return

    print(f"  ✓ Imported {count} rows into {table}")


def main():
    parser = argparse.ArgumentParser(
        description="QuantPricer Historical Market Data Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m market.historical.refresh_data --all
  python -m market.historical.refresh_data --equity --fx --days 730
  python -m market.historical.refresh_data --stats
  python -m market.historical.refresh_data --import-csv data.csv --table equity_prices
        """,
    )

    # Refresh flags
    parser.add_argument("--all", action="store_true", help="Refresh all asset classes")
    parser.add_argument("--equity", action="store_true", help="Refresh equity prices")
    parser.add_argument("--fx", action="store_true", help="Refresh FX rates")
    parser.add_argument("--yield-curves", action="store_true", help="Refresh yield curves")
    parser.add_argument("--options", action="store_true", help="Refresh option chains")
    parser.add_argument("--days", type=int, default=365, help="Lookback days (default: 365)")

    # Stats
    parser.add_argument("--stats", action="store_true", help="Show database statistics")

    # CSV import
    parser.add_argument("--import-csv", type=str, help="Import CSV file path")
    parser.add_argument("--table", type=str, help="Target table for CSV import")
    parser.add_argument("--source", type=str, help="Source label for imported data")

    args = parser.parse_args()

    if args.stats:
        cmd_stats(args)
    elif args.import_csv:
        if not args.table:
            print("--table is required with --import-csv")
            return
        cmd_import_csv(args)
    elif args.all or args.equity or args.fx or args.yield_curves or args.options:
        cmd_refresh(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
