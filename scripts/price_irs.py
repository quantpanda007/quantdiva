"""Price a fresh IRS from a trade file and a market-data file.

Run from the project root:

    python scripts/price_irs.py --trade examples/irs/tc1_trade.json ^
        --market examples/irs/usd_sofr_2026-03-31.json [--output result.json]

Prints total and leg NPVs and the period-by-period cashflows. With --output, also
writes the result as JSON. No Bloomberg data, test fixtures or FastAPI are used.

Exit codes: 0 priced; 2 invalid or unreadable input; 1 pricing failed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.exceptions.errors import PricingError  # noqa: E402
from instruments.rates.irs.cashflows import CashflowExtractionError  # noqa: E402
from instruments.rates.irs.pricing_instrument import InvalidIRSParameters  # noqa: E402
from market.curves.irs_market_snapshot import InvalidMarketData  # noqa: E402
from services.pricers.irs_valuation import (  # noqa: E402
    InvalidTradeDocument,
    IRSValuation,
    IRSValuationError,
    price_irs,
)

INPUT_ERRORS = (InvalidTradeDocument, InvalidIRSParameters, InvalidMarketData, IRSValuationError)


class InputFileError(Exception):
    """A file could not be read or is not valid JSON."""


def load_json(path: str, label: str):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise InputFileError(f"cannot read {label} file {path!r}: {exc.strerror}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputFileError(f"{label} file {path!r} is not valid JSON: {exc}") from exc


def format_valuation(valuation: IRSValuation) -> str:
    lines = [
        f"Trade {valuation.trade_id} ({valuation.instrument_type}, {valuation.currency})  "
        f"valuation {valuation.valuation_date.isoformat()}",
        f"Curves: discount {valuation.discount_curve_id}, forecast {valuation.forecast_curve_id}"
        f"  | model {valuation.model}, engine {valuation.engine}",
        "",
        f"  {'Fixed-leg NPV':<18}{valuation.fixed_leg_npv:>18,.6f}",
        f"  {'Floating-leg NPV':<18}{valuation.floating_leg_npv:>18,.6f}",
        f"  {'Total NPV':<18}{valuation.npv:>18,.6f}",
        "",
        f"  {'Leg':<9}{'Side':<8}{'Per':>3} {'Acc start':>10} {'Acc end':>10} {'Payment':>10}"
        f"{'Notional':>13}{'DCF':>10}{'Rate %':>11}{'Sprd bp':>8}"
        f"{'Amount':>14}{'DF':>11}{'PV':>14}",
    ]
    for row in valuation.cashflows:
        spread = "" if row.spread is None else f"{row.spread * 1e4:.1f}"
        lines.append(
            f"  {row.leg:<9}{row.side:<8}{row.period:>3} {row.accrual_start.isoformat():>10} "
            f"{row.accrual_end.isoformat():>10} {row.payment_date.isoformat():>10}"
            f"{row.notional:>13,.0f}{row.day_count_fraction:>10.6f}{row.rate * 100:>11.6f}"
            f"{spread:>8}{row.amount:>14,.2f}{row.discount_factor:>11.7f}"
            f"{row.present_value:>14,.2f}"
        )
    lines.append("")
    lines.append("Amounts and PVs on the paid leg are negative; PVs sum to the leg NPVs.")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Price a fresh IRS from input files.")
    parser.add_argument("--trade", required=True, help="trade JSON file")
    parser.add_argument("--market", required=True, help="market-data JSON file")
    parser.add_argument("--output", help="optional path for the result as JSON")
    args = parser.parse_args(argv)

    try:
        trade = load_json(args.trade, "trade")
        market = load_json(args.market, "market data")
        valuation = price_irs(trade, market)
    except (InputFileError, *INPUT_ERRORS) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (PricingError, CashflowExtractionError) as exc:
        print(f"pricing failed: {exc}", file=sys.stderr)
        return 1

    print(format_valuation(valuation))
    if args.output:
        try:
            Path(args.output).write_text(
                json.dumps(valuation.to_dict(), indent=2) + "\n", encoding="utf-8"
            )
        except OSError as exc:
            print(f"error: cannot write output file {args.output!r}: {exc.strerror}",
                  file=sys.stderr)
            return 2
        print(f"Result written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
