"""Price any fresh IRS trade on the production engine (PricingService) and print its
cashflow statement, settled cashflows and net cashflow per payment date.

Run from the quantlib-pricing project root (env optima-ql143):

    python price_irs_engine.py --trade examples/irs/tc1_trade.json
    python price_irs_engine.py --trade examples/irs/tc4_trade.json --market <file> [<file> ...]

--market defaults to every market file in examples/irs (USD, CHF, INR, JPY curves and the
fixings file). Several files are merged into one market document; they must share one
valuation date and may not define the same curve, currency or fixing series twice.
Nothing in this script is specific to a trade.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import QuantLib as ql

from instruments.rates.irs.cashflows import irs_cashflow_rows, settled_cashflows
from instruments.rates.irs.pricing_instrument import FreshOISInstrument
from market.curves.irs_fixings import overnight_fixings_applied
from market.curves.irs_market_snapshot import parse_market_snapshot, resolve_market_environment
from services.pricers.pricing_service import PricingService

DEFAULT_MARKET = [
    "examples/irs/usd_sofr_2026-03-31.json",
    "examples/irs/chf_saron_2026-03-31.json",
    "examples/irs/inr_mibor_2026-03-31.json",
    "examples/irs/jpy_tona_2026-03-31.json",
    "examples/irs/fixings_2026-03-31.json",
]


def load(path: str) -> dict:
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


def price(trade_doc: dict, market_doc: dict):
    instrument = FreshOISInstrument.from_dict(trade_doc["params"])
    snapshot = parse_market_snapshot(market_doc)
    if instrument.trade.valuation_date != snapshot.valuation_date:
        raise ValueError(f"trade valuation date {instrument.trade.valuation_date} != market "
                         f"valuation date {snapshot.valuation_date}")
    env = resolve_market_environment(snapshot).environment
    currency = instrument.currency()

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
    print(f"Trade {instrument.trade_id()} ({currency})  valuation {instrument.trade.valuation_date}")
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Price an IRS trade on the production engine.")
    parser.add_argument("--trade", required=True, help="trade JSON file")
    parser.add_argument("--market", nargs="+", default=DEFAULT_MARKET,
                        help="one or more market-data JSON files (default: all in examples/irs)")
    args = parser.parse_args(argv)
    report(*price(load(args.trade), merge_market(args.market)))
    return 0


if __name__ == "__main__":
    sys.exit(main())