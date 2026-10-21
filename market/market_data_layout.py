"""Canonical market-data layout: one place for raw source data and prepared snapshots.

    market_data/
      <valuation date>/
        fixings_<valuation date>.json            shared dated fixings (all currencies)
        <CCY>/
          market_data.json                       raw source export (read by builders only)
          <ccy>_<curve>_<valuation date>.json    prepared curve snapshot: the ONLY curve
                                                 file the pricing engine reads
          <other raw sources>                    e.g. USD's zero-rate export

Roles
-----
* Raw source files (``market_data.json`` and any other export kept beside it) are inputs
  to the snapshot builders and documentation of where a snapshot came from. The pricing
  engine never reads them.
* A prepared snapshot is the curve exactly as the engine consumes it (curve id,
  conventions, pillars). Each exists once, in its currency folder.
* Fixings are shared across currencies and stay one dated file at the date level.

Every path the engine, the regression suite, the audit and the builders use comes from
these functions, so the layout is defined in one place.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Union

ROOT = Path(__file__).resolve().parents[1]
MARKET_DATA_ROOT = ROOT / "market_data"
RAW_MARKET_DATA_FILE = "market_data.json"

DateLike = Union[date, str]


def _stamp(valuation_date: DateLike) -> str:
    if isinstance(valuation_date, date):
        return valuation_date.isoformat()
    return date.fromisoformat(valuation_date).isoformat()  # validates the string


def date_dir(valuation_date: DateLike, root: Path = MARKET_DATA_ROOT) -> Path:
    return Path(root) / _stamp(valuation_date)


def currency_dir(valuation_date: DateLike, currency: str,
                 root: Path = MARKET_DATA_ROOT) -> Path:
    return date_dir(valuation_date, root) / currency.upper()


def curve_snapshot_name(valuation_date: DateLike, currency: str, curve_benchmark: str) -> str:
    return f"{currency.lower()}_{curve_benchmark.lower()}_{_stamp(valuation_date)}.json"


def curve_snapshot_path(valuation_date: DateLike, currency: str, curve_benchmark: str,
                        root: Path = MARKET_DATA_ROOT) -> Path:
    return (currency_dir(valuation_date, currency, root)
            / curve_snapshot_name(valuation_date, currency, curve_benchmark))


def fixings_name(valuation_date: DateLike) -> str:
    return f"fixings_{_stamp(valuation_date)}.json"


def fixings_path(valuation_date: DateLike, root: Path = MARKET_DATA_ROOT) -> Path:
    return date_dir(valuation_date, root) / fixings_name(valuation_date)


def raw_market_data_path(valuation_date: DateLike, currency: str,
                         root: Path = MARKET_DATA_ROOT) -> Path:
    return currency_dir(valuation_date, currency, root) / RAW_MARKET_DATA_FILE
