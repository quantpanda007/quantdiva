"""IRS pricing endpoints: HTTP wiring for the existing IRS input adapter and engine.

No pricing logic here. Every endpoint calls existing functions only:

* ``POST /pricing/irs``: trade inputs (``services.irs_inputs.contract.TradeInputs``, the
  same dictionary the Excel reader produces) -> ``normalizer.normalize`` ->
  ``pricing.price_normalized`` (``price_irs_engine``: canonical market data, QuantLib).
  The response carries the engine's own numbers; the per-leg and net rows are built by
  the same functions as the Excel results workbook (``services.irs_outputs.excel_report``).
* ``POST /pricing/irs/report``: the same pricing, returned as the Excel results workbook
  written by ``excel_report.write_pricing_report`` (as ``price_irs_workbook --output``).
* ``GET /pricing/irs/market-files``: the prepared curve snapshots and the dated fixings
  file present in the canonical layout (``market.market_data_layout``) for a valuation
  date, so the form can state them. Read-only; nothing is selected for the trade here.
* ``POST /pricing/irs/workbook``: an uploaded input workbook -> its trade sheets, and the
  trade inputs of one sheet (``excel_reader.read_trade_sheet``), to fill the form.

The generic ``/pricing/single`` endpoint still rejects IRS (flat test curves, OI-5).
"""

from __future__ import annotations

import io
import shutil
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, File, Form, HTTPException, Query, Response, UploadFile

import price_irs_engine as engine
from core.exceptions.errors import PricingError
from market.market_data_layout import (
    MARKET_DATA_ROOT,
    curve_snapshot_path,
    fixings_path,
)
from services.irs_inputs.contract import InputValidationError
from services.irs_inputs.excel_reader import WorkbookReadError, read_trade_sheet
from services.irs_inputs.normalizer import CURVES, normalize
from services.irs_inputs.pricing import PricedTrade, price_normalized
from services.irs_outputs.excel_report import _leg_rows, _net_rows

router = APIRouter()

# Tests point this at a temporary copy; the service always uses the canonical root.
market_root: Path = MARKET_DATA_ROOT


def _json(value: Any) -> Any:
    """Dates as ISO strings, Decimals as floats; everything else unchanged."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    return value


def _error(status: int, kind: str, message: str, issues: Optional[List[str]] = None):
    detail: Dict[str, Any] = {"error": kind, "message": message}
    if issues is not None:
        detail["issues"] = issues
    return HTTPException(status_code=status, detail=detail)


def priced_trade_response(priced: PricedTrade) -> Dict[str, Any]:
    """The engine's result as JSON: totals, both legs per period, net per payment date."""
    fixed = _leg_rows(priced, "fixed")
    floating = _leg_rows(priced, "floating")
    net = _net_rows(fixed, floating)
    result = priced.engine_outputs[2]
    terms = priced.engine_outputs[0].trade.floating_terms
    return _json({
        "trade_id": priced.trade_id,
        "currency": priced.currency,
        "valuation_date": priced.valuation_date,
        "npv": priced.npv,
        "fixed_leg_npv": priced.fixed_leg_npv,
        "floating_leg_npv": priced.floating_leg_npv,
        "fixed_leg_side": priced.engine_outputs[0].trade.fixed_leg_side,
        "floating_benchmark": f"{terms.benchmark} {terms.benchmark_tenor}",
        "engine": result.engine_used,
        "model": result.model_used,
        "fixed_leg": fixed,
        "floating_leg": floating,
        "net": net,
        "settled_periods": len(priced.settled),
        "market_files": [p.name for p in priced.market_files],
        "fixing_reasons": list(priced.fixing_reasons),
        "notes": list(priced.notes),
        "sign_convention": "Amounts and present values are signed from the trade's point "
                           "of view: the paid leg is negative.",
    })


def _price(trade_inputs: Dict[str, Any]) -> PricedTrade:
    """normalize -> price_normalized, with the adapter's errors as HTTP errors."""
    try:
        normalized = normalize(trade_inputs, source="UI trade inputs")
        return price_normalized(normalized, market_root)
    except InputValidationError as exc:
        raise _error(422, "input_validation", f"{exc.source}: {len(exc.issues)} problem(s)",
                     exc.issues)
    except engine.MarketDataResolutionError as exc:
        raise _error(422, "market_data", str(exc))
    except PricingError as exc:
        raise _error(400, "pricing", str(exc))


@router.post("/irs")
def price_irs(trade_inputs: Dict[str, Any] = Body(...)):
    """Price one IRS from trade inputs (analyst units and labels)."""
    priced = _price(trade_inputs)
    try:
        return priced_trade_response(priced)
    except ValueError as exc:  # e.g. an engine row/period consistency check
        raise _error(400, "pricing", str(exc))


@router.post("/irs/report")
def irs_report(trade_inputs: Dict[str, Any] = Body(...)):
    """Price one IRS and return the results workbook (.xlsx).

    The workbook is written by ``services.irs_outputs.excel_report.write_pricing_report``,
    the same writer as ``scripts/price_irs_workbook.py --output``: Summary, Fixed Leg,
    Floating Leg and Net Cashflow sheets, values only.
    """
    from services.irs_outputs.excel_report import write_pricing_report

    priced = _price(trade_inputs)
    name = f"{priced.trade_id}_{priced.valuation_date.isoformat()}.xlsx"
    name = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
    tmp = tempfile.mkdtemp(prefix="optima_irs_report_")
    try:
        try:
            path = write_pricing_report(priced, Path(tmp) / name, source="Optima IRS screen")
        except ValueError as exc:  # writer consistency checks
            raise _error(400, "pricing", str(exc))
        content = path.read_bytes()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)   # see irs_workbook: never fail on cleanup
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/irs/market-files")
def irs_market_files(valuation_date: str = Query(...), currency: str = Query(...)):
    """Prepared curve snapshots and the fixings file present for a valuation date."""
    try:
        day = date.fromisoformat(valuation_date)
    except ValueError:
        raise _error(422, "input_validation", f"valuation_date {valuation_date!r} is not "
                                              "a YYYY-MM-DD date")
    currency = currency.upper()
    curves = []
    for label, (ccy, benchmark) in CURVES.items():
        if ccy != currency:
            continue
        path = curve_snapshot_path(day, ccy, benchmark, market_root)
        if path.exists():
            curves.append({"curve": label, "curve_source_file": path.name})
    fixings = fixings_path(day, market_root)
    return {
        "valuation_date": day.isoformat(),
        "currency": currency,
        "curves": curves,
        "fixings_files": [fixings.name] if fixings.exists() else [],
    }


@router.get("/irs/curve")
def irs_curve(valuation_date: str = Query(...), currency: str = Query(...)):
    """The prepared curve snapshot the engine uses for a currency, for display.

    Pillar dates and discount factors come from the production curve builder
    (``irs_market_snapshot.parse_market_snapshot`` -> ``resolve_market_environment`` ->
    ``irs_zero_curve.build_zero_curve``), the same one the pricing engine uses. Nothing
    here is an input to pricing.
    """
    from market.curves.irs_market_snapshot import (
        parse_market_snapshot,
        resolve_market_environment,
    )
    import QuantLib as ql

    try:
        day = date.fromisoformat(valuation_date)
    except ValueError:
        raise _error(422, "input_validation", f"valuation_date {valuation_date!r} is not "
                                              "a YYYY-MM-DD date")
    currency = currency.upper()
    paths = [curve_snapshot_path(day, ccy, benchmark, market_root)
             for ccy, benchmark in CURVES.values() if ccy == currency]
    paths = [p for p in paths if p.exists()]
    if not paths:
        raise _error(404, "market_data", f"no prepared {currency} curve snapshot in "
                                         f"market_data/{day.isoformat()}/{currency}/")
    document = engine.load(paths[0])
    resolved = resolve_market_environment(parse_market_snapshot(document))
    assignment = document["assignments"][currency]
    curves = []
    for role in ("discount", "forecast"):
        curve_id = assignment[role]
        if any(c["curve_id"] == curve_id for c in curves):
            next(c for c in curves if c["curve_id"] == curve_id)["roles"].append(role)
            continue
        raw = document["curves"][curve_id]
        built = resolved.curves[curve_id]
        pillars = []
        for obs, pillar in zip(raw["observations"], built.pillar_dates):
            ql_date = ql.Date(pillar.day, pillar.month, pillar.year)
            pillars.append({
                "tenor": obs["tenor"], "date": pillar.isoformat(),
                "zero_rate": obs["zero_rate"],
                "snapshot_discount_factor": obs.get("discount_factor"),
                "discount_factor": built.term_structure.discount(ql_date),
            })
        curves.append({"curve_id": curve_id, "roles": [role],
                       "benchmark": raw["benchmark"], "reference_date": raw["reference_date"],
                       "conventions": raw["conventions"], "spot_date": built.spot_date,
                       "pillars": pillars})
    return _json({"valuation_date": day, "currency": currency, "file": paths[0].name,
                  "provenance": document.get("provenance"), "curves": curves})


@router.post("/irs/workbook")
async def irs_workbook(file: UploadFile = File(...), sheet: Optional[str] = Form(None)):
    """List an input workbook's sheets; with ``sheet``, return that sheet's trade inputs."""
    content = await file.read()
    try:
        from openpyxl import load_workbook
        workbook = load_workbook(io.BytesIO(content), read_only=True)   # in memory: no file
        try:
            sheets = list(workbook.sheetnames)
        finally:
            workbook.close()
    except Exception as exc:  # noqa: BLE001 - any unreadable upload is reported the same
        raise _error(422, "workbook", f"{file.filename}: cannot open as an Excel "
                                      f"workbook ({exc})")
    if sheet is None:
        return {"file": file.filename, "sheets": sheets, "sheet": None, "trade_inputs": None}

    # The existing reader takes a file path. The temporary folder is removed with errors
    # ignored: on Windows a file still held by another process (e.g. a virus scanner)
    # cannot be deleted at once, and that must not fail the request.
    tmp = tempfile.mkdtemp(prefix="optima_irs_")
    try:
        path = Path(tmp) / (Path(file.filename or "inputs.xlsx").name or "inputs.xlsx")
        path.write_bytes(content)
        try:
            inputs = read_trade_sheet(path, sheet)
        except WorkbookReadError as exc:
            raise _error(422, "workbook", str(exc))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {"file": file.filename, "sheets": sheets, "sheet": sheet,
            "trade_inputs": _json(inputs)}
