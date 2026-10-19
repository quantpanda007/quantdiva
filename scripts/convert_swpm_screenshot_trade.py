"""Convert a Bloomberg SWPM screenshot-extracted trade (top-level ``trade`` key, legs under
``trade.legs.fixed`` / ``trade.legs.floating``) into Optima's production trade input
(``{"schema_version", "instrument_type": "ois", "params": {...}}``).

The source file is only read, never modified. Only contractual terms are mapped; Bloomberg
outputs embedded in the source (leg NPVs, accrued, premium, DV01, valuation results,
cashflow amounts, discount factors, the curve table) are ignored: they are not inputs and
not independent expected values.

Supported: fixed vs overnight floating leg (daily reset, compounded in arrears), explicit
per-period schedules and amortising notionals, no principal exchange, payments on the
listed pay dates. Anything else is rejected with ``UnsupportedConversion`` rather than
guessed.

Field mapping (source -> production ``params``):

========================================  ====================================================
trade.swap_id                             trade_id
trade.currency                            currency
trade.valuation_date / effective_date /   valuation_date / effective_date / maturity_date
maturity_date
legs.fixed.pay_receive                    fixed_leg_side ("Pay" -> "pay", "Receive" -> "receive")
<leg>.day_count                           <leg>.day_count (ACT/360, ACT/365, 30/360)
<leg>.pay_frequency                       <leg>.payment_frequency ("SemiAnnual" -> semiannual)
<leg>.calculation_calendar +              <leg>.accrual_date_adjustment {calendar,
business_day_adjustment                   business_day_convention} (Mod Foll -> mod. following)
legs.fixed.coupon (%)                     fixed_leg.fixed_rate (decimal)
legs.floating.index / index_tenor         floating_leg.benchmark / benchmark_tenor
legs.floating.spread_bp                   floating_leg.spread (decimal = bp / 10,000)
legs.floating.leverage                    floating_leg.leverage
legs.floating.reset_frequency             floating_leg.reset_frequency ("Daily" -> daily)
legs.floating.days_before_accrual         floating_leg.observation.lookback_days
legs.floating.days_before_type            floating_leg.observation.lookback_type
legs.floating.rate_cutoff_days            floating_leg.observation.cutoff_days
legs.floating.reset_type                  floating_leg.observation.reset_timing
legs.floating.compounding                 floating_leg.observation.compounding
<leg>.amortization_schedule[]             <leg>.periods[] {accrual_start, accrual_end,
  accrual_start, accrual_end, pay_date,     payment_date, notional = balance x notional-scale}
  balance
========================================  ====================================================

Checked, not mapped (must hold, else rejected): leg currency and dates equal the trade's;
``adjustment`` = "Acc & Pay Dates"; ``payment_delay`` = 0; ``principal_exchange`` =
"Never"; schedule rows contiguous, first start = effective date, last end = maturity date;
balances consistent with ``amort_amount``; per-row spread and leverage equal the leg's.

Not mapped (no production field; the production calculation does not use them):
ids, counterparty, ticker, curve_date, calc_basis, first_payment, next_last_payment,
roll_convention and payment_type (the periods are explicit); floating ``fixing_calendar``
and per-row ``reset_date`` (an overnight leg's observation dates come from the index's own
fixing calendar and the cutoff, as for TC1/TC3/TC4); ``latest_index`` (a fixing, i.e. market
data); ``amort_rate_percent`` / ``amort_amount`` (checked only); every Bloomberg output.

Notional scale: periods use the source balances unchanged (``--notional-scale 1``). A
different basis is a decision, never inferred: pass ``--notional-scale`` explicitly.

Run from the project root:

    python -m scripts.convert_swpm_screenshot_trade examples/irs/tc11_trade.json \\
        examples/irs/tc11_trade_production.json [--notional-scale 1] [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]


class UnsupportedConversion(ValueError):
    """The source trade has a field or convention the production format cannot express."""


_DAY_COUNTS = {"ACT/360": "ACT/360", "ACT/365": "ACT/365", "30/360": "30/360"}
_FREQUENCIES = {"Annual": "annual", "SemiAnnual": "semiannual", "Quarterly": "quarterly",
                "Monthly": "monthly"}
_BUSINESS_DAY = {"Mod Foll": "modified_following", "Following": "following",
                 "Preceding": "preceding", "Mod Prec": "modified_preceding",
                 "No Adjustment": "unadjusted"}
_SIDES = {"Pay": "pay", "Receive": "receive"}
_RESET_FREQUENCIES = {"Daily": "daily"}


def _lookup(table: Dict[str, str], value: Any, path: str) -> str:
    if value not in table:
        raise UnsupportedConversion(f"{path} = {value!r} is not supported; supported: "
                                    f"{sorted(table)}")
    return table[value]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise UnsupportedConversion(message)


def _number(value: float, scale: float):
    scaled = value * scale
    return int(scaled) if float(scaled).is_integer() else scaled


def _periods(leg: Dict[str, Any], trade: Dict[str, Any], name: str, scale: float,
             spread_bp=None, leverage=None) -> List[Dict[str, Any]]:
    rows = leg.get("amortization_schedule") or []
    _require(bool(rows), f"legs.{name}.amortization_schedule is empty")
    _require(rows[0]["accrual_start"] == trade["effective_date"],
             f"legs.{name}: first accrual start {rows[0]['accrual_start']} != effective date "
             f"{trade['effective_date']}")
    _require(rows[-1]["accrual_end"] == trade["maturity_date"],
             f"legs.{name}: last accrual end {rows[-1]['accrual_end']} != maturity date "
             f"{trade['maturity_date']}")
    for i, row in enumerate(rows):
        path = f"legs.{name}.amortization_schedule[{i}]"
        _require(date.fromisoformat(row["accrual_start"]) < date.fromisoformat(row["accrual_end"]),
                 f"{path}: accrual start not before accrual end")
        if i:
            _require(row["accrual_start"] == rows[i - 1]["accrual_end"],
                     f"{path}: not contiguous with the previous period")
            _require(abs(rows[i - 1]["balance"] - row["amort_amount"] - row["balance"]) < 1e-6,
                     f"{path}: balance {row['balance']} != previous balance "
                     f"{rows[i - 1]['balance']} - amort_amount {row['amort_amount']}")
        if spread_bp is not None and "spread_bp" in row:
            _require(row["spread_bp"] == spread_bp, f"{path}: spread differs from the leg's")
        if leverage is not None and "leverage" in row:
            _require(row["leverage"] == leverage, f"{path}: leverage differs from the leg's")
    return [{"accrual_start": r["accrual_start"], "accrual_end": r["accrual_end"],
             "payment_date": r["pay_date"], "notional": _number(r["balance"], scale)}
            for r in rows]


def _common_leg_checks(leg: Dict[str, Any], trade: Dict[str, Any], name: str) -> None:
    for key in ("currency", "effective_date", "maturity_date"):
        _require(leg.get(key) == trade[key],
                 f"legs.{name}.{key} = {leg.get(key)!r} differs from trade {trade[key]!r}")
    _require(leg.get("adjustment") == "Acc & Pay Dates",
             f"legs.{name}.adjustment = {leg.get('adjustment')!r}: only 'Acc & Pay Dates' "
             "is supported")
    _require(leg.get("payment_delay", 0) == 0,
             f"legs.{name}.payment_delay = {leg.get('payment_delay')!r}: only 0 is supported")
    _require(leg.get("principal_exchange", "Never") == "Never",
             f"legs.{name}.principal_exchange = {leg.get('principal_exchange')!r}: only "
             "'Never' is supported")


def _adjustment(leg: Dict[str, Any], name: str) -> Dict[str, str]:
    return {"calendar": leg["calculation_calendar"],
            "business_day_convention": _lookup(_BUSINESS_DAY, leg["business_day_adjustment"],
                                               f"legs.{name}.business_day_adjustment")}


def convert(source: Dict[str, Any], notional_scale: float = 1.0) -> Dict[str, Any]:
    """Production trade document from a screenshot-extracted SWPM trade."""
    if not isinstance(source, dict) or not isinstance(source.get("trade"), dict):
        raise UnsupportedConversion("source has no top-level 'trade' object")
    trade = source["trade"]
    legs = trade.get("legs") or {}
    _require(set(legs) == {"fixed", "floating"},
             f"trade.legs must hold exactly 'fixed' and 'floating', got {sorted(legs)}")
    fx, fl = legs["fixed"], legs["floating"]
    _common_leg_checks(fx, trade, "fixed")
    _common_leg_checks(fl, trade, "floating")
    _require(_SIDES.get(fx["pay_receive"]) != _SIDES.get(fl["pay_receive"]),
             "fixed and floating legs are on the same side")
    reset = _lookup(_RESET_FREQUENCIES, fl["reset_frequency"], "legs.floating.reset_frequency")
    _require(fl.get("index_tenor") == "1D",
             f"legs.floating.index_tenor = {fl.get('index_tenor')!r}: only overnight (1D) "
             "floating legs are supported by this converter")
    fixed_periods = _periods(fx, trade, "fixed", notional_scale)
    floating_periods = _periods(fl, trade, "floating", notional_scale,
                                spread_bp=fl["spread_bp"], leverage=fl["leverage"])
    params = {
        "trade_id": trade["swap_id"],
        "currency": trade["currency"],
        "valuation_date": trade["valuation_date"],
        "effective_date": trade["effective_date"],
        "maturity_date": trade["maturity_date"],
        "fixed_leg_side": _lookup(_SIDES, fx["pay_receive"], "legs.fixed.pay_receive"),
        "fixed_leg": {
            "day_count": _lookup(_DAY_COUNTS, fx["day_count"], "legs.fixed.day_count"),
            "payment_frequency": _lookup(_FREQUENCIES, fx["pay_frequency"],
                                         "legs.fixed.pay_frequency"),
            "fixed_rate": fx["coupon"] / 100,
            "accrual_date_adjustment": _adjustment(fx, "fixed"),
            "periods": fixed_periods,
        },
        "floating_leg": {
            "day_count": _lookup(_DAY_COUNTS, fl["day_count"], "legs.floating.day_count"),
            "payment_frequency": _lookup(_FREQUENCIES, fl["pay_frequency"],
                                         "legs.floating.pay_frequency"),
            "benchmark": fl["index"],
            "benchmark_tenor": fl["index_tenor"],
            "spread": fl["spread_bp"] / 10000,
            "leverage": fl["leverage"],
            "reset_frequency": reset,
            "accrual_date_adjustment": _adjustment(fl, "floating"),
            "observation": {
                "lookback_days": fl["days_before_accrual"],
                "cutoff_days": fl["rate_cutoff_days"],
                "reset_timing": fl["reset_type"],
                "compounding": fl["compounding"],
                "lookback_type": fl["days_before_type"],
            },
            "periods": floating_periods,
        },
    }
    return {"schema_version": 1, "instrument_type": "ois", "params": params}


def to_text(document: Dict[str, Any]) -> str:
    return json.dumps(document, indent=2) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Convert an SWPM screenshot trade.")
    parser.add_argument("source")
    parser.add_argument("output")
    parser.add_argument("--notional-scale", type=float, default=1.0,
                        help="multiply source balances by this (default 1: unchanged)")
    parser.add_argument("--check", action="store_true",
                        help="compare the output file with a fresh conversion")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    source, output = Path(args.source), Path(args.output)
    if source.resolve() == output.resolve():
        print("error: output must differ from the source (the source is never modified)",
              file=sys.stderr)
        return 2
    try:
        text = to_text(convert(json.loads(source.read_text(encoding="utf-8")),
                               args.notional_scale))
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.check:
        same = output.exists() and output.read_text(encoding="utf-8").replace("\r\n", "\n") == text
        print(f"{output}: {'up to date' if same else 'DIFFERS'}")
        return 0 if same else 1
    if output.exists() and not args.overwrite:
        print(f"error: {output} exists; pass --overwrite to replace it", file=sys.stderr)
        return 2
    output.write_text(text, encoding="utf-8")
    print(f"wrote {output} (notional scale {args.notional_scale:g})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
