"""Compare the two SARON observation-date methods of an SF0006M fallback trade (TC2).

Method A (``contractual_accrual``, TC2's PROVISIONAL default since 14-Oct-2026): SARON
observed over each contractual accrual sub-period, no observation shift. The no-shift
choice is an operational assumption made because the trade data contains no
observation-shift term; it is not SME-confirmed or contractually validated (OI-17).

Method B (``reset_date_fallback``, the previous behaviour, still selectable): 6M IBOR
period from reset + 1 EN business day, observed with the benchmark's 2 Swiss business
day shift (OI-11, OI-12).

Everything is computed with production functions: the trade parser
(``pricing_instrument._term_rate_floating``), the per-reset rate
(``term_rate_leg._reset_rate``), ``flat_compounded_amount``, the production curves and
the market-data fixings. The NPV of a method is the full production price
(``price_irs``) when it prices; otherwise it is reported as not computable with the
reason. Bloomberg values are references only. Nothing here is tuned to Bloomberg.

Run from the project root: ``python -m scripts.irs_observation_methods [--case TC2]``.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import QuantLib as ql

from instruments.rates.irs.pricing_instrument import _term_rate_floating
from instruments.rates.irs.term_rate_leg import (
    CONTRACTUAL_ACCRUAL,
    OBSERVATION_METHODS,
    RESET_DATE_FALLBACK,
    TermRateFixingRequired,
    _reset_rate,
    flat_compounded_amount,
    observation_rule,
)
from market.curves.irs_fixings import overnight_fixings_applied
from market.curves.irs_market_snapshot import parse_market_snapshot, resolve_market_environment
from services.pricers.irs_valuation import price_irs

ROOT = Path(__file__).resolve().parents[1]
CASE_TRADES = {"TC2": ROOT / "examples" / "irs" / "tc2_trade.json"}
METHOD_LABELS = {
    CONTRACTUAL_ACCRUAL: "Method A (contractual_accrual, provisional default)",
    RESET_DATE_FALLBACK: "Method B (reset_date_fallback, previous behaviour)",
}
NO_SHIFT_STATUS = (
    "Method A uses no observation shift: an operational assumption because the trade data "
    "has no observation-shift term. Not SME-confirmed or contractually validated (OI-17)."
)


def _json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _ql(value: date) -> ql.Date:
    return ql.Date(value.day, value.month, value.year)


def _py(value: ql.Date) -> date:
    return date(value.year(), value.month(), value.dayOfMonth())


def with_method(trade: Dict[str, Any], method: str) -> Dict[str, Any]:
    """A copy of the trade document with the observation-date method set."""
    if method not in OBSERVATION_METHODS:
        raise ValueError(f"unknown observation method {method!r}")
    doc = copy.deepcopy(trade)
    doc["params"]["floating_leg"]["term_rate"]["observation_dates"] = method
    return doc


def _bloomberg(case_id: str) -> Dict[str, Any]:
    ref = _json(ROOT / "tests" / "fixtures" / "bloomberg_irs" / "references"
                / f"{case_id}.json")["source_oracle_sections"]
    floating = next(ref[k] for k in ("cashflow_leg_1", "cashflow_leg_2")
                    if "Float" in ref[k]["leg"])
    fixed = next(ref[k] for k in ("cashflow_leg_1", "cashflow_leg_2")
                 if "Fixed" in ref[k]["leg"])
    return {"npv": ref["cashflow"]["npv"], "floating_npv": floating["npv"],
            "fixed_npv": fixed["npv"], "floating_rows": floating["cashflows"]}


def _historical_range(message: str, valuation: ql.Date, calendar: ql.Calendar):
    """(first, last) historical RFR fixing dates named by a TermRateFixingRequired."""
    marker = " onwards"
    head = message.split(marker)[0]
    first = date.fromisoformat(head[-10:])
    last = calendar.advance(valuation, -1, ql.Days)
    return first, _py(last)


def _method_periods(trade: Dict[str, Any], method: str, environment, valuation: ql.Date):
    params = with_method(trade, method)["params"]
    _, periods, spec = _term_rate_floating(params["floating_leg"], params["currency"])
    forecast = environment.forecast_curves[params["currency"]]
    discount = environment.discount_curves[params["currency"]]
    margin = float(params["floating_leg"]["spread"])
    day_counter = ql.Actual360()
    if params["floating_leg"]["day_count"] != "ACT/360":
        raise ValueError("comparison implemented for ACT/360 floating legs (TC2)")
    calendar = spec.benchmark.period_calendar()
    rows = []
    with overnight_fixings_applied(environment.fixings or {}):
        for number, (period, resets) in enumerate(zip(periods, spec.resets), start=1):
            if len(resets) != 1:
                raise ValueError("comparison implemented for single-reset periods (TC2)")
            reset = resets[0]
            row = {"period": number, "method": method,
                   "accrual_start": reset.start.isoformat(),
                   "accrual_end": reset.end.isoformat(),
                   "payment_date": period.payment_date.isoformat(),
                   "reset_date": reset.reset_date.isoformat(),
                   "notional": float(period.notional.amount)}
            try:
                rfr, adj, rate_start, ibor_end, obs_start, obs_end, source = _reset_rate(
                    spec, forecast, reset, {})
            except TermRateFixingRequired as exc:
                first, last = _historical_range(str(exc), valuation, calendar)
                row.update({"computable": False,
                            "missing_fixings": f"{spec.benchmark.rfr} {first.isoformat()} -> "
                            f"{last.isoformat()}",
                            "reason": str(exc)})
                rows.append(row)
                continue
            fraction = day_counter.yearFraction(_ql(reset.start), _ql(reset.end))
            amount, _ = flat_compounded_amount(row["notional"], (rfr + adj,), (fraction,),
                                               margin)
            df = discount.discount(_ql(period.payment_date))
            row.update({
                "computable": True,
                "ibor_period": (f"{rate_start.isoformat()} -> {ibor_end.isoformat()}"
                                if ibor_end else "-"),
                "observation_start": obs_start.isoformat(),
                "observation_end": obs_end.isoformat(),
                "compounded_saron_pct": rfr * 100,
                "spread_adjustment_pct": adj * 100,
                "coupon_pct": (rfr + adj + margin) * 100,
                "amount": amount, "discount_factor": df, "pv": amount * df,
            })
            rows.append(row)
    return rows, observation_rule(spec)


def compare(case_id: str = "TC2", market_doc: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Both methods for one case: per-period dates, rates, cashflows; NPVs where priced."""
    if market_doc is None:
        from scripts.irs_case_audit import load_market_document
        market_doc = load_market_document()
    trade = _json(CASE_TRADES[case_id])
    valuation_iso = trade["params"]["valuation_date"]
    valuation = _ql(date.fromisoformat(valuation_iso))
    configured = trade["params"]["floating_leg"]["term_rate"].get(
        "observation_dates", RESET_DATE_FALLBACK)
    bbg = _bloomberg(case_id)
    previous = ql.Settings.instance().evaluationDate
    ql.Settings.instance().evaluationDate = valuation
    try:
        environment = resolve_market_environment(parse_market_snapshot(market_doc)).environment
        methods = {}
        for method in (CONTRACTUAL_ACCRUAL, RESET_DATE_FALLBACK):
            rows, rule = _method_periods(trade, method, environment, valuation)
            try:
                result = price_irs(with_method(trade, method), market_doc)
                priced = {"npv": result.npv, "fixed_leg_npv": result.fixed_leg_npv,
                          "floating_leg_npv": result.floating_leg_npv, "reason": None}
                production = {c.period: c for c in result.cashflows if c.leg == "floating"}
                for row in rows:  # per-period amounts equal the production cashflows
                    if row["computable"]:
                        row["production_amount"] = production[row["period"]].amount
            except Exception as exc:  # noqa: BLE001 - reported, not hidden
                priced = {"npv": None, "fixed_leg_npv": None, "floating_leg_npv": None,
                          "reason": f"{type(exc).__name__}: {exc}"}
            methods[method] = {"label": METHOD_LABELS[method], "rule": rule, "periods": rows,
                               **priced}
    finally:
        ql.Settings.instance().evaluationDate = previous

    a, b = methods[CONTRACTUAL_ACCRUAL], methods[RESET_DATE_FALLBACK]
    comparison = []
    for ra, rb, rbbg in zip(a["periods"], b["periods"], bbg["floating_rows"]):
        both = ra["computable"] and rb["computable"]
        comparison.append({
            "period": ra["period"], "payment_date": ra["payment_date"],
            "accrual": f"{ra['accrual_start']} -> {ra['accrual_end']}",
            "reset_date": ra["reset_date"],
            "a_observation": (f"{ra['observation_start']} -> {ra['observation_end']}"
                              if ra["computable"] else "not computable"),
            "b_observation": (f"{rb['observation_start']} -> {rb['observation_end']}"
                              if rb["computable"] else "needs " + rb["missing_fixings"]),
            "bloomberg_effective_reset_date": rbbg["effective_reset_date"],
            "a_end_matches_bloomberg": (ra.get("observation_end")
                                        == rbbg["effective_reset_date"]),
            "b_end_matches_bloomberg": (rb.get("observation_end")
                                        == rbbg["effective_reset_date"]),
            "a_coupon_pct": ra.get("coupon_pct"), "b_coupon_pct": rb.get("coupon_pct"),
            "bloomberg_coupon_pct": rbbg["equivalent_coupon"],
            "a_minus_b_coupon_bp": ((ra["coupon_pct"] - rb["coupon_pct"]) * 100
                                    if both else None),
            "a_amount": ra.get("amount"), "b_amount": rb.get("amount"),
            "bloomberg_payment": rbbg["payment"],
            "a_pv": ra.get("pv"), "b_pv": rb.get("pv"), "bloomberg_pv": rbbg["pv"],
            "a_minus_b_pv": (ra["pv"] - rb["pv"]) if both else None,
        })
    common = [c for c in comparison if c["a_pv"] is not None and c["b_pv"] is not None]
    common_periods = [c["period"] for c in common]
    totals = {
        "common_periods": common_periods,
        "a_floating_pv_common": sum(c["a_pv"] for c in common),
        "b_floating_pv_common": sum(c["b_pv"] for c in common),
        "bloomberg_floating_pv_common": sum(c["bloomberg_pv"] for c in common),
    }
    totals["a_minus_b_floating_pv_common"] = (totals["a_floating_pv_common"]
                                              - totals["b_floating_pv_common"])

    def _vs_bbg(npv):
        return None if npv is None else npv - bbg["npv"]

    return {
        "case_id": case_id,
        "valuation_date": valuation_iso,
        "configured_method": configured,
        "configured_label": METHOD_LABELS[configured],
        "no_shift_status": NO_SHIFT_STATUS,
        "bloomberg": {k: v for k, v in bbg.items() if k != "floating_rows"},
        "methods": {m: {k: v for k, v in d.items()} for m, d in methods.items()},
        "npv_vs_bloomberg": {m: _vs_bbg(d["npv"]) for m, d in methods.items()},
        "periods": comparison,
        "common_period_totals": totals,
    }


COMPARISON_COLUMNS = [
    "period", "payment_date", "accrual", "reset_date", "a_observation", "b_observation",
    "bloomberg_effective_reset_date", "a_end_matches_bloomberg", "b_end_matches_bloomberg",
    "a_coupon_pct", "b_coupon_pct", "bloomberg_coupon_pct", "a_minus_b_coupon_bp",
    "a_amount", "b_amount", "bloomberg_payment", "a_pv", "b_pv", "bloomberg_pv",
    "a_minus_b_pv",
]


def _f(value, spec):
    return "-" if value is None else format(value, spec)


def to_markdown(result: Dict[str, Any]) -> List[str]:
    a = result["methods"][CONTRACTUAL_ACCRUAL]
    b = result["methods"][RESET_DATE_FALLBACK]
    bbg = result["bloomberg"]
    t = result["common_period_totals"]
    lines = [f"## SARON observation-date methods ({result['case_id']})", "",
             f"Configured for production: **{result['configured_label']}**. "
             f"{result['no_shift_status']} Method B is preserved unchanged and selectable "
             "(`floating_leg.term_rate.observation_dates`). Neither method is tuned to "
             "Bloomberg.", "",
             f"- Method A rule: {a['rule']}",
             f"- Method B rule: {b['rule']}", "",
             "| Measure | Method A | Method B | Bloomberg |", "|---|---:|---:|---:|"]
    for label, key, bkey in (("NPV", "npv", "npv"), ("Fixed leg PV", "fixed_leg_npv",
                                                      "fixed_npv"),
                             ("Floating leg PV", "floating_leg_npv", "floating_npv")):
        lines.append(f"| {label} | {_f(a[key], ',.4f')} | "
                     f"{_f(b[key], ',.4f') if b[key] is not None else 'not computable'} | "
                     f"{bbg[bkey]:,.2f} |")
    diff_a = result["npv_vs_bloomberg"][CONTRACTUAL_ACCRUAL]
    diff_b = result["npv_vs_bloomberg"][RESET_DATE_FALLBACK]
    lines.append(f"| NPV - Bloomberg | {_f(diff_a, '+,.4f')} | "
                 f"{'not computable' if b['npv'] is None else _f(diff_b, '+,.4f')} | - |")
    if b["npv"] is None:
        missing = next((p["missing_fixings"] for p in b["periods"] if not p["computable"]),
                       "-")
        lines += ["", f"Method B is not priced: it needs historical fixings {missing} "
                  "(evidence request R3). No fixings are fabricated."]
    lines += ["", f"Floating PV over the periods both methods can compute "
              f"(P{', P'.join(str(p) for p in t['common_periods'])}): Method A "
              f"{t['a_floating_pv_common']:,.4f}, Method B {t['b_floating_pv_common']:,.4f}, "
              f"Bloomberg {t['bloomberg_floating_pv_common']:,.2f}; A - B "
              f"{t['a_minus_b_floating_pv_common']:+,.4f}.", "",
              "| Period | Accrual | Reset | A observation | B observation | BBG effective reset "
              "| A coupon % | B coupon % | BBG coupon % | A - B (bp) | A amount | B amount "
              "| BBG payment | A PV | B PV | BBG PV |",
              "|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for c in result["periods"]:
        mark_a = " ✓" if c["a_end_matches_bloomberg"] else ""
        mark_b = " ✓" if c["b_end_matches_bloomberg"] else ""
        lines.append(
            f"| P{c['period']} | {c['accrual']} | {c['reset_date']} | {c['a_observation']}"
            f"{mark_a} | {c['b_observation']}{mark_b} | {c['bloomberg_effective_reset_date']} "
            f"| {_f(c['a_coupon_pct'], '.4f')} | {_f(c['b_coupon_pct'], '.4f')} | "
            f"{c['bloomberg_coupon_pct']:.4f} | {_f(c['a_minus_b_coupon_bp'], '+.2f')} | "
            f"{_f(c['a_amount'], ',.4f')} | {_f(c['b_amount'], ',.4f')} | "
            f"{c['bloomberg_payment']:,.2f} | {_f(c['a_pv'], ',.4f')} | "
            f"{_f(c['b_pv'], ',.4f')} | {c['bloomberg_pv']:,.2f} |")
    lines += ["", "✓ = observation end equals Bloomberg's effective reset date. Method B's P1 "
              "end (30-Jul-2026 vs Bloomberg 29-Jul-2026) is the open discrepancy TC2-F2 / R8; "
              "the convention question for management/SME is R9 (OI-17)."]
    return lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--case", default="TC2", choices=sorted(CASE_TRADES))
    args = parser.parse_args(argv)
    print("\n".join(to_markdown(compare(args.case))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
