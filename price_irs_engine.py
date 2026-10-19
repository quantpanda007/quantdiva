"""Price any fresh IRS trade on the production engine (PricingService) and print its
cashflow statement, settled cashflows and net cashflow per payment date.

Run from the quantlib-pricing project root (env optima-ql143):

    python price_irs_engine.py --trade examples/irs/tc1_trade.json
    python price_irs_engine.py --trade examples/irs/tc4_trade.json --market <file> [<file> ...]

Market data
-----------
Without --market, the market files are resolved from the trade before any market file is
read (``resolve_market_files``):

* currency, valuation date and floating benchmark come from the trade
  (``FreshOISInstrument.from_dict``; no market data needed);
* the curve snapshot is ``<market-dir>/<ccy>_<curve benchmark>_<valuation date>.json``,
  where the curve benchmark is the production mapping
  ``services.pricers.irs_valuation.BENCHMARK_CURVES`` (SOFRRATE -> SOFR, SF0006M -> SARON,
  MUTKCALM -> TONA, IRSWOF -> MIBOR); e.g. ``usd_sofr_2026-03-31.json``;
* the shared ``<market-dir>/fixings_<valuation date>.json`` is added only when the trade's
  conventions make a live floating coupon depend on an observation or reset on or before
  the valuation date (``fixing_requirements``).

``--market-dir`` defaults to ``examples/irs`` (the pricing snapshots).
``market_data/<date>/<CCY>/market_data.json`` holds the raw Bloomberg curve exports
(dates, par rates, DFs); it is not a pricing snapshot and is not read here. A missing file
is an error; there is no fallback to another date or currency.

With --market, exactly the given files are used. In both cases the files are merged with
the same rules as the ten-case audit (one valuation date; no curve, currency or fixing
series defined twice) and the trade is checked against the merged market document.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import List, Optional, Tuple

import QuantLib as ql

from core.exceptions.errors import PricingError
from instruments.rates.irs.cashflows import irs_cashflow_rows, settled_cashflows
from instruments.rates.irs.floating_leg import build_floating_index
from instruments.rates.irs.pricing_instrument import FreshOISInstrument, InvalidIRSParameters
from instruments.rates.irs.term_rate_leg import (
    CONTRACTUAL_ACCRUAL,
    FallbackTermBenchmark,
    rate_period_start,
)
from market.curves.irs_fixings import overnight_fixings_applied
from market.curves.irs_market_snapshot import (
    InvalidMarketData,
    parse_market_snapshot,
    resolve_market_environment,
)
from services.pricers.irs_valuation import BENCHMARK_CURVES
from services.pricers.pricing_service import PricingService

DEFAULT_MARKET_DIR = "examples/irs"


class MarketDataResolutionError(ValueError):
    """The market data a trade needs cannot be resolved, found or validated."""


def load(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def merge_market(paths: list) -> dict:
    """One market document from several snapshot files (same rules as the ten-case audit)."""
    docs = [load(p) for p in paths]
    dates = {d["valuation_date"] for d in docs}
    if len(dates) != 1:
        raise ValueError(f"market files have different valuation dates: {sorted(dates)}")
    merged = {"schema_version": docs[0]["schema_version"],
              "valuation_date": docs[0]["valuation_date"],
              "provenance": " | ".join(d["provenance"] for d in docs),
              "curves": {}, "assignments": {}, "fixings": {}}
    for path, doc in zip(paths, docs):
        for section in ("curves", "assignments", "fixings"):
            clash = set(merged[section]) & set(doc.get(section, {}))
            if clash:
                raise ValueError(f"{path}: {section} {sorted(clash)} already defined")
            merged[section].update(doc.get(section, {}))
    return merged


# --- market-data resolution from the trade -------------------------------------------------


def _ql(value: date) -> ql.Date:
    return ql.Date(value.day, value.month, value.year)


def _py(value: ql.Date) -> date:
    return date(value.year(), value.month(), value.dayOfMonth())


def fixing_requirements(instrument: FreshOISInstrument) -> List[str]:
    """Reasons the trade needs fixings on or before its valuation date (empty: none).

    Only floating coupons still to be valued (payment after the valuation date) count.
    The first observation of each is derived with the production conventions:
    overnight legs - accrual start moved back by the lookback on the index's fixing
    calendar; term-rate legs - per the leg's observation method (Method A: the reset
    sub-period start; Method B fallback: the reset date and the shifted IBOR-period start;
    projected term rates: the reset date and the rate-period start)."""
    trade = instrument.trade
    valuation = trade.valuation_date
    reasons: List[str] = []
    spec = trade.floating_term_rate
    if spec is None:
        index = build_floating_index(trade.floating_terms, trade.currency)
        observation = trade.floating_terms.observation
        lookback = (observation.lookback_days or 0) if observation else 0
        calendar = index.fixingCalendar()
        for number, period in enumerate(trade.floating_periods, start=1):
            if period.payment_date <= valuation:
                continue  # settled: not valued
            first = _py(calendar.advance(_ql(period.accrual_start), -lookback, ql.Days))
            if first <= valuation:
                reasons.append(f"floating period {number}: "
                               f"{trade.floating_terms.benchmark} observed from "
                               f"{first.isoformat()}")
        return reasons
    benchmark = spec.benchmark
    for number, (period, resets) in enumerate(zip(trade.floating_periods, spec.resets),
                                              start=1):
        if period.payment_date <= valuation:
            continue
        for reset in resets:
            if spec.observation_method == CONTRACTUAL_ACCRUAL:
                first = reset.start
                label = f"{benchmark.rfr} observed from {first.isoformat()} (Method A)"
            elif isinstance(benchmark, FallbackTermBenchmark):
                start = rate_period_start(spec, reset.reset_date)
                first = _py(benchmark.period_calendar().advance(
                    _ql(start), -benchmark.shift_days, ql.Days))
                first = min(first, reset.reset_date)
                label = (f"{benchmark.name} reset {reset.reset_date.isoformat()}, "
                         f"{benchmark.rfr} observed from {first.isoformat()} (Method B)")
            else:
                first = min(reset.reset_date, rate_period_start(spec, reset.reset_date))
                label = f"{benchmark.name} reset {reset.reset_date.isoformat()}"
            if first <= valuation:
                reasons.append(f"floating period {number}: {label}")
    return reasons


@dataclass(frozen=True)
class MarketSelection:
    currency: str
    valuation_date: date
    floating_benchmark: str
    curve_benchmark: str
    files: Tuple[Path, ...]
    fixing_reasons: Tuple[str, ...]


def resolve_market_files(trade_doc: dict, market_dir=DEFAULT_MARKET_DIR) -> MarketSelection:
    """Select the market files a trade needs, before reading any of them."""
    params = trade_doc.get("params") if isinstance(trade_doc, dict) else None
    if not isinstance(params, dict):
        raise MarketDataResolutionError("trade document has no 'params' object")
    try:
        instrument = FreshOISInstrument.from_dict(params)  # validates valuation date etc.
    except InvalidIRSParameters as exc:
        raise MarketDataResolutionError(f"invalid trade: {exc}") from exc
    trade = instrument.trade
    benchmark = trade.floating_terms.benchmark
    curve_benchmark = BENCHMARK_CURVES.get(benchmark)
    if curve_benchmark is None:
        raise MarketDataResolutionError(
            f"floating benchmark {benchmark!r} has no curve mapping; supported: "
            f"{sorted(BENCHMARK_CURVES)}")
    directory = Path(market_dir)
    stamp = trade.valuation_date.isoformat()
    curve_file = directory / f"{trade.currency.lower()}_{curve_benchmark.lower()}_{stamp}.json"
    if not curve_file.is_file():
        raise MarketDataResolutionError(
            f"no {trade.currency} {curve_benchmark} market snapshot for the trade's valuation "
            f"date {stamp}: expected {curve_file}")
    files = [curve_file]
    reasons = fixing_requirements(instrument)
    if reasons:
        fixings_file = directory / f"fixings_{stamp}.json"
        if not fixings_file.is_file():
            raise MarketDataResolutionError(
                f"the trade needs fixings on or before {stamp} ({'; '.join(reasons)}) but "
                f"{fixings_file} does not exist")
        files.append(fixings_file)
    return MarketSelection(trade.currency, trade.valuation_date, benchmark, curve_benchmark,
                           tuple(files), tuple(reasons))


# --- pricing and reporting -----------------------------------------------------------------


def price(trade_doc: dict, market_doc: dict):
    instrument = FreshOISInstrument.from_dict(trade_doc["params"])
    snapshot = parse_market_snapshot(market_doc)
    if instrument.trade.valuation_date != snapshot.valuation_date:
        raise ValueError(f"trade valuation date {instrument.trade.valuation_date} != market "
                         f"valuation date {snapshot.valuation_date}")
    currency = instrument.currency()
    assignment = snapshot.assignment(currency)  # fails if the currency has no curves
    benchmark = instrument.trade.floating_terms.benchmark
    forecast_benchmark = snapshot.curves[assignment.forecast_curve_id].market_data.benchmark
    if BENCHMARK_CURVES.get(benchmark) != forecast_benchmark:
        raise ValueError(f"floating benchmark {benchmark!r} needs a "
                         f"{BENCHMARK_CURVES.get(benchmark)!r} forecast curve, but the {currency} "
                         f"forecast curve {assignment.forecast_curve_id!r} is "
                         f"{forecast_benchmark!r}")
    env = resolve_market_environment(snapshot).environment

    previous = ql.Settings.instance().evaluationDate
    try:
        # Past overnight fixings (market data) are in QuantLib's index history only while
        # this trade is priced and read; the previous history is restored afterwards.
        with overnight_fixings_applied(env.fixings or {}):
            result = PricingService().price(instrument=instrument, market_env=env,
                                            model_type="analytical", engine_type="discounting")
            legs = instrument.leg_npvs()
            # Read while the pricing evaluation date is still set (same date and curve).
            rows = irs_cashflow_rows(instrument.last_built, env.discount_curves[currency])
            settled = settled_cashflows(instrument.last_built,
                                        ql.Settings.instance().evaluationDate)
    finally:
        ql.Settings.instance().evaluationDate = previous
    return instrument, currency, result, legs, rows, settled


def report(instrument, currency, result, legs, rows, settled) -> None:
    print(f"Trade {instrument.trade_id()} ({currency})  "
          f"valuation {instrument.trade.valuation_date}")
    print(f"NPV {result.npv:,.4f} | fixed {legs['fixed']:,.4f} | floating {legs['floating']:,.4f}"
          f" | engine {result.engine_used}, model {result.model_used}\n")

    print("Cashflow statement (paid leg negative; rate includes any floating spread)")
    print(f"{'Leg':8} {'Side':7} {'Per':>3} {'Acc start':10} {'Acc end':10} {'Pay date':10} "
          f"{'Notional':>14} {'DCF':>9} {'Rate %':>10} {'Amount':>15} {'DF':>10} {'PV':>15}")
    for r in sorted(rows, key=lambda r: (r.payment_date, r.leg)):
        print(f"{r.leg:8} {r.side:7} {r.period:>3} {r.accrual_start} {r.accrual_end} "
              f"{r.payment_date} {r.notional:>14,.2f} {r.day_count_fraction:>9.6f} "
              f"{r.rate * 100:>10.6f} {r.amount:>15,.2f} {r.discount_factor:>10.7f} "
              f"{r.present_value:>15,.2f}")

    if settled:
        print("\nSettled (pay on or before the valuation date; excluded from the NPV)")
        for s in settled:
            print(f"  {s.leg:8} {s.side:7} period {s.period}  {s.accrual_start} -> "
                  f"{s.accrual_end}, paid {s.payment_date}")

    net = defaultdict(lambda: [0.0, 0.0])
    for r in rows:
        net[r.payment_date][0] += r.amount
        net[r.payment_date][1] += r.present_value
    print(f"\nNet cashflow per payment date\n{'Pay date':10} {'Net amount':>15} {'Net PV':>15}")
    for d in sorted(net):
        print(f"{d} {net[d][0]:>15,.2f} {net[d][1]:>15,.2f}")
    total = sum(v[1] for v in net.values())
    print(f"{'Total':10} {'':>15} {total:>15,.4f}   (engine NPV {result.npv:,.4f}, "
          f"difference {total - result.npv:+.2e})")


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Price an IRS trade on the production engine.")
    parser.add_argument("--trade", required=True, help="trade JSON file")
    parser.add_argument("--market", nargs="+", default=None,
                        help="market-data JSON files to use instead of resolving them from the "
                        "trade")
    parser.add_argument("--market-dir", default=DEFAULT_MARKET_DIR,
                        help=f"folder of market snapshots for resolution (default "
                        f"{DEFAULT_MARKET_DIR})")
    args = parser.parse_args(argv)
    try:
        trade_doc = load(args.trade)
        if args.market is None:
            selection = resolve_market_files(trade_doc, args.market_dir)
            files = list(selection.files)
            print(f"Market data resolved from the trade ({selection.currency}, "
                  f"{selection.floating_benchmark} -> {selection.curve_benchmark} curve, "
                  f"{selection.valuation_date}):")
            for f in files:
                print(f"  {f}")
            if selection.fixing_reasons:
                print("  fixings needed for: " + "; ".join(selection.fixing_reasons))
            print()
        else:
            files = args.market
            print("Market data as supplied: " + ", ".join(files) + "\n")
        valuation = price(trade_doc, merge_market(files))
    except (OSError, json.JSONDecodeError, KeyError, ValueError, InvalidIRSParameters,
            InvalidMarketData) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except PricingError as exc:
        print(f"pricing failed: {exc}", file=sys.stderr)
        return 1
    report(*valuation)
    return 0


if __name__ == "__main__":
    sys.exit(main())
