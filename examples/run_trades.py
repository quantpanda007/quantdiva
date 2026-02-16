"""
Trade Runner — reads JSON trade definitions, prices across engines.

This script is the bridge between JSON config → pricing → output.
It will later serve as the backend for the frontend API.

Usage:
    python examples/run_trades.py                          # default trades.json
    python examples/run_trades.py examples/trades.json     # custom file
    python examples/run_trades.py --trade VAN-EU-001       # single trade
    python examples/run_trades.py --output results.csv     # export to CSV
"""

from __future__ import annotations

import json
import sys
import time
import argparse
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure project root is on path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

import registry.bootstrap  # noqa: F401

import QuantLib as ql

from core.enums.definitions import (
    BarrierType,
    ExerciseType,
    OptionType,
)
from core.types.value_objects import PricingDate
from market.curves.yield_curve import build_test_market_env
from services.pricers.pricing_service import PricingService

# Instrument classes
from instruments.equity.vanilla_option import VanillaOption
from instruments.equity.barrier_option import BarrierOption
from instruments.equity.digital_option import DigitalOption, DigitalType
from instruments.equity.asian_option import AsianOption, AverageType, StrikeType
from instruments.equity.lookback_option import LookbackOption, LookbackStrikeType


# ---------------------------------------------------------------------------
# Instrument factory
# ---------------------------------------------------------------------------

def build_instrument(trade: Dict[str, Any]) -> Any:
    """Build an instrument from a trade dict."""
    inst_type = trade["instrument_type"]

    def parse_date(d):
        if isinstance(d, date):
            return d
        return date.fromisoformat(str(d))

    if inst_type == "vanilla_option":
        return VanillaOption(
            _trade_id=trade["trade_id"],
            underlying=trade["underlying"],
            strike=float(trade["strike"]),
            expiry=parse_date(trade["expiry"]),
            option_type=OptionType(trade["option_type"]),
            exercise_type=ExerciseType(trade.get("exercise_type", "european")),
            _currency=trade.get("currency", "USD"),
        )

    elif inst_type == "barrier_option":
        return BarrierOption(
            _trade_id=trade["trade_id"],
            underlying=trade["underlying"],
            strike=float(trade["strike"]),
            expiry=parse_date(trade["expiry"]),
            option_type=OptionType(trade["option_type"]),
            barrier_type=BarrierType(trade["barrier_type"]),
            barrier_level=float(trade["barrier_level"]),
            rebate=float(trade.get("rebate", 0.0)),
            _currency=trade.get("currency", "USD"),
        )

    elif inst_type == "digital_option":
        return DigitalOption(
            _trade_id=trade["trade_id"],
            underlying=trade["underlying"],
            strike=float(trade["strike"]),
            expiry=parse_date(trade["expiry"]),
            option_type=OptionType(trade["option_type"]),
            digital_type=DigitalType(trade.get("digital_type", "cash_or_nothing")),
            cash_payoff=float(trade.get("cash_payoff", 1.0)),
            _currency=trade.get("currency", "USD"),
        )

    elif inst_type == "asian_option":
        return AsianOption(
            _trade_id=trade["trade_id"],
            underlying=trade["underlying"],
            strike=float(trade.get("strike", 0.0)),
            expiry=parse_date(trade["expiry"]),
            option_type=OptionType(trade["option_type"]),
            average_type=AverageType(trade.get("average_type", "arithmetic")),
            strike_type=StrikeType(trade.get("strike_type", "fixed")),
            averaging_start=parse_date(trade["averaging_start"]) if trade.get("averaging_start") else None,
            fixing_frequency=trade.get("fixing_frequency", "monthly"),
            _currency=trade.get("currency", "USD"),
        )

    elif inst_type == "lookback_option":
        return LookbackOption(
            _trade_id=trade["trade_id"],
            underlying=trade["underlying"],
            strike=float(trade.get("strike", 0.0)),
            expiry=parse_date(trade["expiry"]),
            option_type=OptionType(trade["option_type"]),
            strike_type=LookbackStrikeType(trade.get("strike_type", "floating")),
            current_max=trade.get("current_max"),
            current_min=trade.get("current_min"),
            _currency=trade.get("currency", "USD"),
        )

    else:
        raise ValueError(f"Unknown instrument type: {inst_type}")


# ---------------------------------------------------------------------------
# Market environment factory
# ---------------------------------------------------------------------------

def build_market_env_from_config(config: Dict[str, Any], underlying: str):
    """Build MarketEnvironment from JSON config for a specific underlying."""
    mkt = config["market_data"]
    und_data = mkt["underlyings"][underlying]

    return build_test_market_env(
        pricing_date=PricingDate(date.fromisoformat(mkt["pricing_date"])),
        spot=und_data["spot"],
        rate=mkt["rate"],
        vol=und_data["vol"],
        div_yield=und_data.get("div_yield", 0.0),
        underlying=underlying,
    )


# ---------------------------------------------------------------------------
# Result formatting
# ---------------------------------------------------------------------------

def format_result_row(
    trade_id: str,
    instrument_type: str,
    underlying: str,
    engine: str,
    npv: float,
    elapsed_ms: float,
    extras: Dict[str, Any] = None,
) -> Dict[str, Any]:
    row = {
        "trade_id": trade_id,
        "instrument_type": instrument_type,
        "underlying": underlying,
        "engine": engine,
        "npv": round(npv, 6),
        "elapsed_ms": round(elapsed_ms, 2),
    }
    if extras:
        row.update(extras)
    return row


def print_results_table(results: List[Dict[str, Any]]) -> None:
    """Print results as a formatted table."""
    if not results:
        print("No results.")
        return

    # Header
    print()
    print(f"{'Trade ID':<20} {'Type':<18} {'Underlying':<10} {'Engine':<22} {'NPV':>14} {'Time(ms)':>10}")
    print(f"{'-'*20} {'-'*18} {'-'*10} {'-'*22} {'-'*14} {'-'*10}")

    current_trade = None
    for r in results:
        # Separator between trades
        if current_trade and current_trade != r["trade_id"]:
            print()
        current_trade = r["trade_id"]

        npv_str = f"{r['npv']:>14.6f}" if r["npv"] == r["npv"] else f"{'FAILED':>14}"
        extras = ""
        if "mc_std_error" in r:
            extras = f"  (±{r['mc_std_error']:.4f})"

        print(
            f"{r['trade_id']:<20} "
            f"{r['instrument_type']:<18} "
            f"{r['underlying']:<10} "
            f"{r['engine']:<22} "
            f"{npv_str} "
            f"{r['elapsed_ms']:>10.2f}"
            f"{extras}"
        )

    print()


def export_csv(results: List[Dict], filepath: str) -> None:
    """Export results to CSV."""
    import csv
    if not results:
        return

    keys = list(results[0].keys())
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(results)
    print(f"Results exported to {filepath}")


def export_json(results: List[Dict], filepath: str) -> None:
    """Export results to JSON."""
    with open(filepath, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"Results exported to {filepath}")


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_trades(
    config: Dict[str, Any],
    trade_filter: Optional[str] = None,
    verbose: bool = True,
) -> List[Dict[str, Any]]:
    """
    Run all trades from config, return results.

    Args:
        config:       Parsed JSON config
        trade_filter: If set, only run trades matching this ID
        verbose:      Print progress to stdout

    Returns:
        List of result dicts
    """
    ps = PricingService()
    all_results = []
    engine_params = config.get("engine_params", {})

    trades = config["trades"]
    if trade_filter:
        trades = [t for t in trades if t["trade_id"] == trade_filter]
        if not trades:
            print(f"No trade found with ID '{trade_filter}'")
            return []

    total_trades = sum(len(t.get("engines", ["analytic"])) for t in trades)
    completed = 0

    for trade in trades:
        trade_id = trade["trade_id"]
        underlying = trade["underlying"]
        engines = trade.get("engines", ["analytic"])

        if verbose:
            print(f"\n{'='*60}")
            print(f"Trade: {trade_id} | {trade['instrument_type']} | {underlying}")
            print(f"{'='*60}")

        # Build instrument
        try:
            instrument = build_instrument(trade)
        except Exception as e:
            print(f"  ✗ Failed to build instrument: {e}")
            continue

        # Build market env
        try:
            market_env = build_market_env_from_config(config, underlying)
        except Exception as e:
            print(f"  ✗ Failed to build market env: {e}")
            continue

        if verbose:
            print(f"  {instrument}")
            mkt = config["market_data"]["underlyings"][underlying]
            print(f"  S={mkt['spot']}, σ={mkt['vol']}, r={config['market_data']['rate']}, q={mkt.get('div_yield', 0)}")

        # Price with each engine
        for engine_type in engines:
            completed += 1
            params = engine_params.get(engine_type, {})

            t0 = time.perf_counter()
            try:
                result = ps.price(
                    instrument=instrument,
                    market_env=market_env,
                    model_type="black_scholes",
                    engine_type=engine_type,
                    engine_params=params if params else None,
                )
                elapsed_ms = (time.perf_counter() - t0) * 1000

                extras = {}
                if "mc_std_error" in result.diagnostics:
                    extras["mc_std_error"] = round(result.diagnostics["mc_std_error"], 6)
                if "mc_confidence_interval" in result.diagnostics:
                    ci = result.diagnostics["mc_confidence_interval"]
                    extras["mc_ci_low"] = round(ci[0], 6)
                    extras["mc_ci_high"] = round(ci[1], 6)

                row = format_result_row(
                    trade_id=trade_id,
                    instrument_type=trade["instrument_type"],
                    underlying=underlying,
                    engine=engine_type,
                    npv=result.npv,
                    elapsed_ms=elapsed_ms,
                    extras=extras,
                )
                all_results.append(row)

                if verbose:
                    ci_str = ""
                    if "mc_std_error" in extras:
                        ci_str = f" ± {extras['mc_std_error']:.4f}"
                    print(f"  ✓ {engine_type:<20} NPV = {result.npv:>12.6f}{ci_str}  ({elapsed_ms:.1f}ms)")

            except Exception as e:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                row = format_result_row(
                    trade_id=trade_id,
                    instrument_type=trade["instrument_type"],
                    underlying=underlying,
                    engine=engine_type,
                    npv=float("nan"),
                    elapsed_ms=elapsed_ms,
                    extras={"error": str(e)},
                )
                all_results.append(row)

                if verbose:
                    print(f"  ✗ {engine_type:<20} FAILED: {e}")

    return all_results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Run option trades from JSON config",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python examples/run_trades.py
  python examples/run_trades.py examples/trades.json
  python examples/run_trades.py --trade VAN-EU-001
  python examples/run_trades.py --output results.csv
  python examples/run_trades.py --output results.json --format json
        """,
    )
    parser.add_argument(
        "config_file",
        nargs="?",
        default="examples/trades.json",
        help="Path to JSON trade config (default: examples/trades.json)",
    )
    parser.add_argument(
        "--trade", "-t",
        help="Run only this trade ID",
    )
    parser.add_argument(
        "--output", "-o",
        help="Export results to file (CSV or JSON)",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["csv", "json"],
        default="csv",
        help="Output format (default: csv)",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress progress output, only show summary table",
    )

    args = parser.parse_args()

    # Load config
    config_path = Path(args.config_file)
    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        sys.exit(1)

    with open(config_path) as f:
        config = json.load(f)

    print(f"\nLoading trades from: {config_path}")
    print(f"Pricing date: {config['market_data']['pricing_date']}")
    print(f"Trades: {len(config['trades'])}")

    # Run
    results = run_trades(
        config,
        trade_filter=args.trade,
        verbose=not args.quiet,
    )

    # Summary table
    print("\n" + "=" * 100)
    print("SUMMARY")
    print("=" * 100)
    print_results_table(results)

    # Export
    if args.output:
        if args.format == "json":
            export_json(results, args.output)
        else:
            export_csv(results, args.output)

    # Stats
    succeeded = sum(1 for r in results if r["npv"] == r["npv"])
    failed = len(results) - succeeded
    total_time = sum(r["elapsed_ms"] for r in results)
    print(f"Total: {succeeded} succeeded, {failed} failed, {total_time:.0f}ms total")


if __name__ == "__main__":
    main()