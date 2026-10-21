"""Price one trade worksheet of the IRS input workbook on the existing engine.

    python -m scripts.price_irs_workbook --workbook examples/irs/Optima_IRS_Test_Case_Inputs_v4.xlsx
    python -m scripts.price_irs_workbook --workbook <file.xlsx> --sheet TC001 [--market-root <dir>]
                                         [--show-trade]

Excel worksheet -> services.irs_inputs.excel_reader (trade inputs) -> normalizer (engine
trade document) -> pricing (price_irs_engine: canonical market data, PricingService).
Prints the same cashflow statement as price_irs_engine.py. --show-trade also prints the
normalized trade document (JSON).

Exit codes: 0 priced; 2 input or market-data problem (all problems listed); 1 pricing error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import price_irs_engine as engine  # noqa: E402
from core.exceptions.errors import PricingError  # noqa: E402
from market.market_data_layout import MARKET_DATA_ROOT  # noqa: E402
from services.irs_inputs.contract import InputValidationError  # noqa: E402
from services.irs_inputs.excel_reader import WorkbookReadError, read_trade_sheet  # noqa: E402
from services.irs_inputs.normalizer import normalize  # noqa: E402
from services.irs_inputs.pricing import price_normalized  # noqa: E402


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Price an IRS trade worksheet.")
    parser.add_argument("--workbook", required=True, help="input workbook (.xlsx)")
    parser.add_argument("--sheet", default=None, help="worksheet (default: the only one)")
    parser.add_argument("--market-root", default=MARKET_DATA_ROOT,
                        help="root of the market_data/<date>/<CCY>/ layout")
    parser.add_argument("--show-trade", action="store_true",
                        help="print the normalized trade document")
    args = parser.parse_args(argv)
    try:
        inputs = read_trade_sheet(args.workbook, args.sheet)
        normalized = normalize(inputs, source=f"{Path(args.workbook).name}"
                                              f"[{args.sheet or 'only sheet'}]")
        if args.show_trade:
            print(json.dumps(normalized.trade_document, indent=2) + "\n")
        priced = price_normalized(normalized, Path(args.market_root))
    except (WorkbookReadError, InputValidationError, engine.MarketDataResolutionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except PricingError as exc:
        print(f"PRICING ERROR: {exc}", file=sys.stderr)
        return 1
    print("Market data:")
    for path in priced.market_files:
        print(f"  {path}")
    for note in priced.notes:
        print(f"  note: {note}")
    print()
    engine.report(*priced.engine_outputs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
