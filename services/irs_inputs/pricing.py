"""Price a normalized IRS trade on the existing engine (``price_irs_engine``).

No pricing logic of its own. The steps are the existing engine's:

1. ``price_irs_engine.resolve_market_files``: the prepared curve snapshot (and the dated
   fixings file only when the trade needs a fixing) from the canonical layout
   ``market_data/<valuation date>/<CCY>/``;
2. the input's market-data reference is checked against that selection and against the
   prepared snapshot (curve file, fixings file, reference date, interpolation). A
   mismatch is an error; the reference never selects, overrides or rebuilds a curve;
3. ``price_irs_engine.merge_market`` and ``price_irs_engine.price`` (which restores
   QuantLib's evaluation date).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import price_irs_engine as engine
from market.market_data_layout import MARKET_DATA_ROOT
from services.irs_inputs.contract import InputValidationError, NormalizedIRSTrade


@dataclass(frozen=True)
class PricedTrade:
    trade_id: str
    currency: str
    valuation_date: date
    npv: float
    fixed_leg_npv: float
    floating_leg_npv: float
    cashflows: Tuple[Any, ...]            # instruments.rates.irs.cashflows.IRSCashflowRow
    settled: Tuple[Any, ...]              # SettledCashflow, excluded from the NPV
    market_files: Tuple[Path, ...]
    fixing_reasons: Tuple[str, ...]
    notes: Tuple[str, ...]
    engine_outputs: Tuple[Any, ...]       # (instrument, currency, result, legs, rows, settled)


def _check_reference(trade: NormalizedIRSTrade, selection, market_doc: Dict[str, Any]) -> None:
    request = trade.market
    problems: List[str] = []
    curve_file = selection.files[0]
    if request.curve_benchmark != selection.curve_benchmark:
        problems.append(f"market_data.curve: {request.curve_benchmark} curve stated, the trade's "
                        f"benchmark resolves to the {selection.curve_benchmark} curve")
    if request.curve_file != curve_file.name:
        problems.append(f"market_data.curve_source_file: {request.curve_file!r} stated, the "
                        f"resolver selected {curve_file.name!r}")
    fixings = [p.name for p in selection.files[1:]]
    if fixings and request.fixings_file != fixings[0]:
        problems.append(f"market_data.fixings_source_file: the trade needs fixings "
                        f"({'; '.join(selection.fixing_reasons)}) from {fixings[0]!r}, stated "
                        f"{request.fixings_file!r}")
    if not fixings and request.fixings_file is not None:
        problems.append(f"market_data.fixings_source_file: {request.fixings_file!r} stated, but "
                        "the trade needs no fixing on or before the valuation date")
    currency = request.currency
    assignment = market_doc["assignments"][currency]
    curve_ids = {assignment["discount"], assignment["forecast"]}
    for curve_id in sorted(curve_ids):
        curve = market_doc["curves"][curve_id]
        if request.reference_date is not None and \
                curve["reference_date"] != request.reference_date.isoformat():
            problems.append(f"market_data.reference_date: {request.reference_date} stated, the "
                            f"prepared snapshot {curve_id} has {curve['reference_date']}")
        actual = curve["conventions"]["interpolation"]
        if request.interpolation is not None and request.interpolation != actual:
            problems.append(f"market_data.interpolation: {request.interpolation!r} stated, the "
                            f"prepared snapshot {curve_id} uses {actual!r}; the snapshot is "
                            "never changed to match the input")
    if problems:
        raise InputValidationError(problems, "market-data reference")


def price_normalized(trade: NormalizedIRSTrade,
                     market_root: Path = MARKET_DATA_ROOT) -> PricedTrade:
    document = trade.trade_document
    selection = engine.resolve_market_files(document, market_root)
    market_doc = engine.merge_market(list(selection.files))
    _check_reference(trade, selection, market_doc)
    outputs = engine.price(document, market_doc)
    instrument, currency, result, legs, rows, settled = outputs
    return PricedTrade(
        trade_id=str(instrument.trade_id()), currency=currency,
        valuation_date=instrument.trade.valuation_date, npv=result.npv,
        fixed_leg_npv=legs["fixed"], floating_leg_npv=legs["floating"],
        cashflows=tuple(rows), settled=tuple(settled), market_files=tuple(selection.files),
        fixing_reasons=tuple(selection.fixing_reasons), notes=trade.notes,
        engine_outputs=outputs)


def price_workbook(path, sheet: Optional[str] = None,
                   market_root: Path = MARKET_DATA_ROOT) -> PricedTrade:
    """Excel worksheet -> trade inputs -> normalized trade -> existing engine."""
    from services.irs_inputs.excel_reader import read_trade_sheet
    from services.irs_inputs.normalizer import normalize

    inputs = read_trade_sheet(path, sheet)
    normalized = normalize(inputs, source=f"{Path(path).name}[{sheet or 'only sheet'}]")
    return price_normalized(normalized, market_root)
