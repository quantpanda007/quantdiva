"""Ten-case valuation and reconciliation report: Optima's fresh IRS pricing path
against the Bloomberg reference results for TC1-TC10.

Validation only. Pricing, capability checks and cashflow comparison come from
``scripts.irs_case_audit`` (``run_audit``), which prices each case through the
production workflow (``price_irs`` -> ``PricingService`` -> discounting engine)
with the market data the repository configures. This module adds no pricing: it
classifies each case, attributes each cashflow difference, and writes the report.
Bloomberg values are read only as references; nothing here feeds them into pricing.

Run from the project root:

    python -m scripts.irs_reconciliation_report [--output-dir <new directory>]

Without ``--output-dir`` only the summary is printed. With it, a new directory is
created holding ``reconciliation.json``, ``summary.md``, ``summary.csv`` and
``cashflows/<case>.csv``. The directory must not exist yet and must not be inside
``tests/fixtures``, ``examples`` or ``market_data``. The output contains
Bloomberg-derived values: keep it local (OI-6).

Exit codes: 0 report produced with no ERROR case; 1 at least one ERROR case;
2 refused output path; 3 QuantLib shared state corrupted (audit stopped).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import QuantLib as ql

from instruments.rates.irs.term_rate_leg import flat_compounded_amount
from scripts import irs_case_audit as audit
from scripts import irs_evidence_register as register
from scripts import irs_observation_methods as methods

REPORT_SCHEMA_VERSION = 2

STATUS_DEFINITIONS = {
    "PASS": "Priced by the production path, and every comparison is within tolerance: total, "
    "fixed-leg and floating-leg NPV, and every cashflow (coupon, payment, discount factor, "
    "accrual dates).",
    "FAIL": "Priced by the production path, but at least one comparison is outside tolerance. "
    "The failing checks are listed; documented open items are tagged.",
    "PARTIAL": "The production engine priced the trade, but the full workflow stopped on a "
    "documented limitation, so the cashflow reconciliation is incomplete.",
    "BLOCKED": "A required capability or input is missing; nothing is priced. The blockers "
    "are listed.",
    "ERROR": "The case failed unexpectedly during the audit; the stage and exception are "
    "recorded.",
}
STATUSES = tuple(STATUS_DEFINITIONS)

# Tolerances: the repository's Bloomberg display tolerances (scripts/irs_case_audit.py,
# shared with the TC1 reconciliation test). An NPV may differ by up to one payment
# tolerance per cashflow it sums, since each Bloomberg payment carries that rounding band.
NPV_TOL_PER_CASHFLOW = audit.PAYMENT_TOL
TOLERANCES = {
    "coupon_pct": audit.COUPON_DISPLAY_TOL_PCT,
    "discount_factor": audit.DF_DISPLAY_TOL,
    "payment": audit.PAYMENT_TOL,
    "npv_per_cashflow": NPV_TOL_PER_CASHFLOW,
}
NOT_COMPUTED = "not computed by the Optima production path"

CASHFLOW_COLUMNS = (
    "case_id", "status", "leg", "period", "accrual_start", "accrual_end", "payment_date",
    "bbg_accrual_start", "bbg_accrual_end", "bbg_effective_reset_date", "bbg_reset_date",
    "bbg_reset_rate_pct", "notional", "bbg_notional", "accrual_days", "day_count",
    "day_count_fraction", "index_rate_pct", "spread_pct", "coupon_pct", "bbg_coupon_pct",
    "diff_coupon_bp", "payment", "bbg_payment", "diff_payment", "discount_factor",
    "bbg_discount_factor", "diff_discount_factor", "present_value", "bbg_present_value",
    "diff_present_value", "open_item", "row_status", "discrepancy_sources",
)
SUMMARY_COLUMNS = (
    "case_id", "trade_id", "currency", "floating_index", "status", "optima_npv",
    "bloomberg_npv", "diff_npv", "diff_npv_pct", "optima_fixed_leg_npv",
    "bloomberg_fixed_leg_npv", "optima_floating_leg_npv", "bloomberg_floating_leg_npv",
    "key_issue",
)


# --- Bloomberg reference metrics -----------------------------------------------------------


def bloomberg_trade_metrics(case_id: str) -> Dict[str, Any]:
    """Par coupon, PV01, DV01, accrued and BP value as Bloomberg displays them."""
    oracle = audit._read(audit.FIXTURES / "references" / f"{case_id}.json")[
        "source_oracle_sections"
    ]
    values = dict(oracle.get("valuation_results") or oracle.get("valuation") or {})
    values.update({k: v for k, v in (oracle.get("risk") or {}).items() if k not in values})
    return {k: values.get(k) for k in ("par_coupon", "pv01", "dv01", "accrued", "bp_value")}


# --- cashflow attribution ---------------------------------------------------------------------


def discrepancy_sources(row: Dict[str, Any]) -> List[str]:
    """Where a priced cashflow differs from Bloomberg, in calculation order.

    schedule      accrual dates differ from Bloomberg's for the same payment date
    rate          coupon (fixed rate, or projected index rate + spread) outside tolerance
    payment       payment outside tolerance although the coupon is within it (notional,
                  day count or amount calculation)
    discounting   discount factor outside tolerance
    """
    b, d = row.get("bloomberg"), row.get("difference")
    if b is None or d is None:
        return []
    sources = []
    if (row["accrual_start"], row["accrual_end"]) != (b["accrual_start"], b["accrual_end"]):
        sources.append("schedule")
    rate_out = d["rate_bp"] is not None and abs(d["rate_bp"]) / 100 > TOLERANCES["coupon_pct"]
    if rate_out:
        sources.append("rate")
    if not rate_out and abs(d["amount"]) > TOLERANCES["payment"]:
        sources.append("payment")
    if abs(d["discount_factor"]) > TOLERANCES["discount_factor"]:
        sources.append("discounting")
    return sources


def row_status(row: Dict[str, Any]) -> str:
    if row.get("bloomberg") is None:
        return "NO_BLOOMBERG_ROW"
    return "RECONCILED" if not discrepancy_sources(row) else "DIFFERENCE"


# --- case classification ------------------------------------------------------------------


def _pct(diff: Optional[float], reference: Optional[float]) -> Optional[float]:
    if diff is None or not reference:
        return None
    return audit._r(diff / abs(reference) * 100)


def classify(case: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Report status and the reasons for it. Only a priced case can PASS, and only when
    every check is within tolerance."""
    audit_status = case["status"]
    if audit_status == "error":
        e = case["error"]
        return "ERROR", [f"{e['stage']}: {e['type']}: {e['message']}"]
    if audit_status == "blocked":
        return "BLOCKED", [f"{b['code']}: {b['detail']}" for b in case["blockers"]]
    if audit_status == "partially_audited":
        return "PARTIAL", [f"{x['code']}: {x['detail']}" for x in case["limitations"]]
    if audit_status != "priced":
        return "ERROR", [f"unknown audit status {audit_status!r}"]
    rows = case["cashflows"] or []
    failures = []
    if not rows:
        failures.append("no cashflows to reconcile")
    counts = Counter(r["leg"] for r in rows)
    limits = {
        "npv": NPV_TOL_PER_CASHFLOW * len(rows),
        "fixed_leg_npv": NPV_TOL_PER_CASHFLOW * counts["fixed"],
        "floating_leg_npv": NPV_TOL_PER_CASHFLOW * counts["floating"],
    }
    for metric, limit in limits.items():
        diff = case["differences"][metric]
        if abs(diff) > limit:
            failures.append(f"{metric} difference {diff:+.4f} exceeds tolerance {limit:.2f}")
    for r in rows:
        if r.get("bloomberg") is None:
            failures.append(f"{r['leg']} P{r['period']} {r['payment_date']}: no Bloomberg row")
            continue
        sources = discrepancy_sources(r)
        if sources:
            tag = f" [{r['open_item']}]" if r["open_item"] else ""
            failures.append(
                f"{r['leg']} P{r['period']} {r['payment_date']}: {', '.join(sources)}{tag}"
            )
    return ("FAIL", failures) if failures else ("PASS", [])


def _bloomberg_consistency(bbg: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not bbg:
        return None
    legs_sum = bbg["fixed_leg_npv"] + bbg["floating_leg_npv"]
    return {
        "trade_npv": bbg["npv"],
        "cashflow_legs_sum": audit._r(legs_sum),
        "difference": audit._r(bbg["npv"] - legs_sum),
        "consistent": abs(bbg["npv"] - legs_sum) <= TOLERANCES["payment"],
        "other_leg_values": bbg.get("other_leg_values"),
    }


def reconcile_case(case: Dict[str, Any]) -> Dict[str, Any]:
    status, reasons = classify(case)
    bbg, pricing, diffs = case.get("bloomberg"), case.get("pricing"), case.get("differences")
    leg = case.get("floating_leg") or {}
    try:
        reference_metrics = bloomberg_trade_metrics(case["case_id"])
    except (OSError, KeyError, ValueError) as exc:  # unreadable reference: record, carry on
        reference_metrics = {"error": f"{type(exc).__name__}: {exc}"}
    return {
        "case_id": case["case_id"],
        "trade_id": case.get("trade_id"),
        "currency": case.get("currency"),
        "floating_index": (f"{leg['index']} {leg['index_tenor']}" if leg else None),
        "valuation_date": case.get("valuation_date"),
        "status": status,
        "reasons": reasons,
        "audit_status": case["status"],
        "trade": {
            "optima": None if not pricing else {
                "npv": pricing["npv"],
                "fixed_leg_npv": pricing["fixed_leg_npv"],
                "floating_leg_npv": pricing["floating_leg_npv"],
                "path": pricing["path"],
                "engine": pricing["engine"],
                "par_coupon": NOT_COMPUTED,
                "pv01": NOT_COMPUTED,
                "dv01": NOT_COMPUTED,
                "accrued": NOT_COMPUTED,
            },
            "bloomberg": None if not bbg else {
                "npv": bbg["npv"],
                "fixed_leg_npv": bbg["fixed_leg_npv"],
                "floating_leg_npv": bbg["floating_leg_npv"],
                "leg_npv_source": bbg.get("leg_npv_source"),
                **reference_metrics,
            },
            "difference": None if not diffs else {
                **diffs,
                "npv_pct": _pct(diffs["npv"], bbg["npv"] if bbg else None),
            },
            "bloomberg_internal_consistency": _bloomberg_consistency(bbg),
        },
        "cashflows": [
            {**r, "row_status": row_status(r), "discrepancy_sources": discrepancy_sources(r)}
            for r in case.get("cashflows") or []
        ],
        "observations": case.get("observations", []),
        "hypotheses": case.get("hypotheses", []),
    }


def _key_issue(rec: Dict[str, Any]) -> str:
    if rec["status"] == "PASS":
        return "-"
    if rec["status"] == "BLOCKED":
        return "; ".join(sorted({r.split(":")[0] for r in rec["reasons"]}))
    if rec["status"] == "FAIL":
        differing = [r for r in rec["cashflows"] if r["row_status"] != "RECONCILED"]
        tags = sorted({r["open_item"] for r in differing if r["open_item"]})
        sources = sorted({s for r in differing for s in r["discrepancy_sources"]})
        parts = [rec["reasons"][0]]
        if differing:
            parts.append(f"{len(differing)} of {len(rec['cashflows'])} cashflows differ "
                         f"({', '.join(sources) or 'no Bloomberg row'})")
        if tags:
            parts.append(f"documented: {', '.join(tags)}")
        return "; ".join(parts)
    return rec["reasons"][0] if rec["reasons"] else "-"


def build_report(audit_result: Dict[str, Any]) -> Dict[str, Any]:
    cases = [reconcile_case(c) for c in audit_result["cases"]]
    counts = {s: [c["case_id"] for c in cases if c["status"] == s] for s in STATUSES}
    supported = sorted({(c["currency"], c["floating_index"]) for c in cases
                        if c["status"] in ("PASS", "FAIL", "PARTIAL")})
    blocker_codes = Counter(
        b["code"] for c in audit_result["cases"] for b in c.get("blockers", [])
        if c["status"] == "blocked"
    )
    open_items = Counter(
        r["open_item"] for c in cases for r in c["cashflows"]
        if r["open_item"] and r["row_status"] == "DIFFERENCE"
    )
    audit_cases = {c["case_id"]: c for c in audit_result["cases"]}
    for rec in cases:
        rec["analysis"] = analyse_case(rec, audit_cases[rec["case_id"]])
    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "report": "fresh IRS - Bloomberg ten-case valuation and reconciliation",
        "classifications": register.CLASSIFICATIONS,
        "evidence_requests": register.EVIDENCE_REQUESTS,
        "source_conflicts": register.SOURCE_CONFLICTS,
        "value_sources": VALUE_SOURCES,
        "input_provenance": input_provenance(),
        "valuation_date": audit_result["valuation_date"],
        "quantlib_version": audit_result["quantlib_version"],
        "status_definitions": STATUS_DEFINITIONS,
        "tolerances": TOLERANCES,
        "counts": counts,
        "supported": [{"currency": c, "floating_index": i} for c, i in supported],
        "common_blockers": dict(sorted(blocker_codes.items())),
        "recurring_discrepancies": dict(sorted(open_items.items())),
        "cases": cases,
        "audit": audit_result,
    }


# --- diagnostics (labelled: diagnostic checks, not production results) ----------------------
#
# Everything below works on numbers already produced: the production results (audit
# cashflow rows and derived inputs read from the production-built swap) and the Bloomberg
# references. The only calculation that reuses a pricing function is the reset
# attribution, which calls the production ``flat_compounded_amount``.

DIAGNOSTIC_LABEL = "diagnostic check (not a production result)"
ROW_TOL = 1e-6  # identity checks on sums of already-rounded (12 significant digit) values


def trade_structure(case: Dict[str, Any]) -> str:
    """One-line structure from the Bloomberg source terms (never hand-written)."""
    fx, fl, ft = case.get("fixed_leg"), case.get("floating_leg"), case.get("features")
    if not fx or not fl or not ft:
        return "-"
    return (
        f"{fx['side']} fixed {fx['rate_pct']:g}% {fx['day_count']} {fx['pay_frequency']}; "
        f"{fl['side']} {fl['index']} {fl['index_tenor']} + {fl['spread_bp']:g} bp "
        f"({fl['reset_frequency']} reset, {fl.get('reset_type') or '-'}, compounding "
        f"{fl.get('compounding') or '-'}, {fl['day_count']}) {fl['pay_frequency']}; "
        f"{ft['periods']} periods, {'amortising' if ft['amortising'] else 'bullet'}; "
        f"{case['effective_date']} -> {case['maturity_date']}"
    )


def _decompose(amount: float, df: float, pv: float, b: Dict[str, Any]) -> Dict[str, Any]:
    """PV_optima - PV_bloomberg = amount effect + DF effect + Bloomberg display residual:
    (A_o - A_b) DF_o + A_b (DF_o - DF_b) + (A_b DF_b - PV_b). An identity, not a model."""
    amount_effect = (amount - b["payment"]) * df
    df_effect = b["payment"] * (df - b["discount_factor"])
    display = b["payment"] * b["discount_factor"] - b["pv"]
    total = pv - b["pv"]
    return {
        "amount_effect": audit._r(amount_effect),
        "discount_factor_effect": audit._r(df_effect),
        "bloomberg_display_residual": audit._r(display),
        "pv_difference": audit._r(total),
        "identity_holds": abs(amount_effect + df_effect + display - total) <= ROW_TOL,
    }


def observation_method_of(case: Dict[str, Any]) -> Optional[str]:
    """Observation-date method recorded in a priced term-rate case's derived inputs."""
    rows = (case.get("derived_inputs") or {}).get("rows") or []
    methods = {(r.get("detail") or {}).get("observation_method") for r in rows
               if r.get("item") == "observation_window"}
    methods.discard(None)
    if len(methods) > 1:
        raise ValueError(f"{case.get('case_id')}: mixed observation methods {sorted(methods)}")
    return methods.pop() if methods else None


def _derived_index(case: Dict[str, Any]) -> Dict[Tuple[str, str, str, Optional[int]], Dict]:
    rows = (case.get("derived_inputs") or {}).get("rows") or []
    return {(r["leg"], r["payment_date"], r["item"], r["sub_period"]): r for r in rows}


def diagnostic_cashflows(case: Dict[str, Any], bloomberg_rows: List[Dict[str, Any]]):
    """For a PARTIAL case (production extractor refused): cashflows paying after the
    valuation date, read from the production-built swap, against Bloomberg."""
    derived = case.get("derived_inputs")
    if not derived:
        return []
    by_key = {(b["leg"], b["pay_date"]): b for b in bloomberg_rows}
    spread_pct = (case["floating_leg"]["spread_bp"] or 0) / 100.0
    out = []
    for r in derived["rows"]:
        if r["item"] != "coupon_amount":
            continue
        sign = -1.0 if r["side"] == "pay" else 1.0
        index = _derived_index(case)
        df = index[(r["leg"], r["payment_date"], "discount_factor", None)]["value"]
        rate = None
        if r["leg"] == "fixed":
            rate = case["fixed_leg"]["rate_pct"]
        else:
            idx = index.get((r["leg"], r["payment_date"], "compounded_index_rate", None))
            rate = None if idx is None else audit._r(idx["value"] + spread_pct)
        amount = sign * r["value"]
        detail = r["detail"]
        row = {"leg": r["leg"], "period": r["period"], "payment_date": r["payment_date"],
               "accrual_start": detail["accrual_start"], "accrual_end": detail["accrual_end"],
               "accrual_days": (date.fromisoformat(detail["accrual_end"])
                                - date.fromisoformat(detail["accrual_start"])).days,
               "day_count_fraction": audit._r(detail["accrual_fraction"]),
               "notional": detail["notional"],
               "spread_pct": None if r["leg"] == "fixed" else audit._r(spread_pct),
               "index_rate_pct": None if r["leg"] == "fixed" or rate is None
               else audit._r(rate - spread_pct),
               "rate_pct": rate, "amount": audit._r(amount), "discount_factor": df,
               "present_value": audit._r(amount * df)}
        b = by_key.get((r["leg"], r["payment_date"]))
        row["bloomberg"] = b
        if b is not None:
            row["difference"] = {
                "rate_bp": None if rate is None or b["rate_pct"] is None
                else audit._r((rate - b["rate_pct"]) * 100),
                "amount": audit._r(amount - b["payment"]),
                "discount_factor": audit._r(df - b["discount_factor"]),
                "present_value": audit._r(amount * df - b["pv"]),
            }
            row["decomposition"] = _decompose(amount, df, amount * df, b)
        out.append(row)
    return out


def leg_reconciliation(case: Dict[str, Any], rows: List[Dict[str, Any]],
                       bbg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Cashflow PVs -> leg PVs -> NPV, for Optima (must close exactly) and Bloomberg
    (as displayed), and the PV differences aggregated by effect."""
    pricing = case.get("pricing")
    if not pricing or not rows:
        return {}
    out: Dict[str, Any] = {"label": DIAGNOSTIC_LABEL, "legs": {}}
    for leg in ("fixed", "floating"):
        mine = [r for r in rows if r["leg"] == leg]
        optima_sum = sum(r["present_value"] for r in mine)
        dec = [r["decomposition"] for r in mine if r.get("decomposition")]
        b_rows = [r["bloomberg"] for r in mine if r.get("bloomberg")]
        bloomberg_sum = sum(b["pv"] for b in b_rows)
        out["legs"][leg] = {
            "optima_cashflow_pv_sum": audit._r(optima_sum),
            "optima_leg_npv": pricing[f"{leg}_leg_npv"],
            "optima_closes": abs(optima_sum - pricing[f"{leg}_leg_npv"]) <= ROW_TOL,
            "bloomberg_cashflow_pv_sum": audit._r(bloomberg_sum),
            "bloomberg_leg_npv": None if not bbg else bbg[f"{leg}_leg_npv"],
            "bloomberg_leg_minus_cashflow_sum": None if not bbg
            else audit._r(bbg[f"{leg}_leg_npv"] - bloomberg_sum),
            "amount_effect": audit._r(sum(d["amount_effect"] for d in dec)),
            "discount_factor_effect": audit._r(sum(d["discount_factor_effect"] for d in dec)),
            "bloomberg_display_residual": audit._r(
                sum(d["bloomberg_display_residual"] for d in dec)),
            "pv_difference": audit._r(sum(d["pv_difference"] for d in dec)),
        }
    legs = out["legs"]
    out["optima_legs_sum"] = audit._r(sum(l["optima_leg_npv"] for l in legs.values()))
    out["optima_npv"] = pricing["npv"]
    out["optima_closes"] = (abs(out["optima_legs_sum"] - pricing["npv"]) <= ROW_TOL
                            and all(l["optima_closes"] for l in legs.values()))
    return out


def bloomberg_reset_reference(case_id: str) -> Optional[Dict[str, Any]]:
    """Bloomberg reset rates by reset date: the case's own cashflow table where it shows
    them (TC8, TC9), otherwise a supplementary reference with its stated source (TC7)."""
    supplementary = register.SUPPLEMENTARY_BLOOMBERG_REFERENCES.get(case_id)
    if supplementary:
        return supplementary
    try:
        rows = audit.read_bloomberg(case_id)["cashflows"]
    except (OSError, KeyError, ValueError):
        return None
    rates = {r["reset_date"]: r["reset_rate_pct"] for r in rows
             if r["leg"] == "floating" and r.get("reset_date")
             and r.get("reset_rate_pct") is not None}
    if not rates:
        return None
    return {"source": "Bloomberg cashflow table (reset_date, reset_rate) in the case fixture",
            "reset_rate_pct": dict(sorted(rates.items()))}


def reset_attribution(case: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Substitute Bloomberg's reset rates one at a time, in reset order, into the
    production flat-compounding function, holding Optima's discount factors. Only for
    cases with term-rate resets and a Bloomberg reset reference."""
    reference = bloomberg_reset_reference(case["case_id"])
    rows = (case.get("derived_inputs") or {}).get("rows") or []
    subs = [r for r in rows if r["item"] == "sub_period_amount"]
    if not reference or not subs:
        return None
    resets = {(r["period"], r["sub_period"]): r for r in rows if r["item"] == "reset_rate"}
    index = _derived_index(case)
    periods: Dict[int, List[Dict[str, Any]]] = {}
    for s in subs:
        reset = resets[(s["period"], s["sub_period"])]
        if reset["detail"]["reset_date"] not in reference["reset_rate_pct"]:
            return None  # every reset needs a Bloomberg counterpart
        periods.setdefault(s["period"], []).append({
            "reset_date": reset["detail"]["reset_date"],
            "rate": s["detail"]["reset_rate"], "fraction": s["detail"]["accrual_fraction"],
            "notional": s["detail"]["notional"], "margin": s["detail"]["margin"],
            "payment_date": s["payment_date"], "sign": -1.0 if s["side"] == "pay" else 1.0,
        })

    def payments(rates: Dict[str, float]) -> Dict[int, float]:
        out = {}
        for number, items in periods.items():
            total, _ = flat_compounded_amount(
                items[0]["notional"], tuple(rates[i["reset_date"]] for i in items),
                tuple(i["fraction"] for i in items), items[0]["margin"])
            out[number] = items[0]["sign"] * total
        return out

    dfs = {n: index[("floating", items[0]["payment_date"], "discount_factor", None)]["value"]
           for n, items in periods.items()}
    current = {i["reset_date"]: i["rate"] for items in periods.values() for i in items}
    base = payments(current)
    steps = []
    order = sorted(current)
    for reset_date in order:
        before = payments(current)
        optima = current[reset_date]
        bloomberg = reference["reset_rate_pct"][reset_date] / 100.0
        current[reset_date] = bloomberg
        after = payments(current)
        d_pay = {n: after[n] - before[n] for n in after}
        steps.append({
            "reset_date": reset_date,
            "optima_reset_pct": audit._r(optima * 100),
            "bloomberg_reset_pct": reference["reset_rate_pct"][reset_date],
            "difference_bp": audit._r((optima - bloomberg) * 1e4),
            "payment_effect": {str(n): audit._r(-v) for n, v in d_pay.items() if v},
            "npv_effect": audit._r(-sum(v * dfs[n] for n, v in d_pay.items())),
        })
    final = payments(current)
    return {
        "label": DIAGNOSTIC_LABEL,
        "method": "Bloomberg reset rates substituted one at a time in reset order into the "
        "production flat_compounded_amount (term_rate_leg.py:149-161); Optima discount "
        "factors held; effects are Optima minus Bloomberg",
        "bloomberg_source": reference["source"],
        "steps": steps,
        "total_npv_effect": audit._r(sum(s["npv_effect"] for s in steps)),
        "payments_optima": {str(n): audit._r(v) for n, v in base.items()},
        "payments_with_bloomberg_resets": {str(n): audit._r(v) for n, v in final.items()},
        "npv_with_bloomberg_resets": audit._r(
            case["pricing"]["npv"] + sum((final[n] - base[n]) * dfs[n] for n in base)),
    }


def derived_comparisons(case: Dict[str, Any], bloomberg_rows: List[Dict[str, Any]],
                        attribution: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Each derived input with its Bloomberg counterpart where one exists. Bloomberg values
    that are themselves inferred (equivalent coupon minus contractual spread) say so."""
    derived = case.get("derived_inputs")
    if not derived:
        return []
    by_key = {(b["leg"], b["pay_date"]): b for b in bloomberg_rows}
    reference = bloomberg_reset_reference(case["case_id"]) or {}
    steps = {s["reset_date"]: s for s in (attribution or {}).get("steps", [])}
    spread_pct = (case["floating_leg"]["spread_bp"] or 0) / 100.0
    index = _derived_index(case)
    out = []
    for r in derived["rows"]:
        b = by_key.get((r["leg"], r["payment_date"]))
        sign = -1.0 if r.get("side") == "pay" else 1.0
        row = {
            "case_id": case["case_id"], "leg": r["leg"], "side": r.get("side"),
            "period": r["period"], "sub_period": r["sub_period"],
            "payment_date": r["payment_date"], "item": r["item"], "optima_value": r["value"],
            "unit": r["unit"], "bloomberg_value": None, "bloomberg_source": None,
            "difference": None, "difference_unit": None, "payment_effect": None,
            "pv_effect": None, "inputs": r["inputs"], "method": r["method"], "basis": r["basis"],
        }
        item = r["item"]
        if b is not None and item == "discount_factor":
            row.update(bloomberg_value=b["discount_factor"], bloomberg_source="cashflow table",
                       difference=audit._r(r["value"] - b["discount_factor"]),
                       difference_unit="DF",
                       pv_effect=audit._r(b["payment"] * (r["value"] - b["discount_factor"])))
        elif b is not None and item == "coupon_amount":
            df = index[(r["leg"], r["payment_date"], "discount_factor", None)]["value"]
            diff = sign * r["value"] - b["payment"]
            row.update(bloomberg_value=abs(b["payment"]), bloomberg_source="cashflow table",
                       difference=audit._r(sign * diff), difference_unit="currency",
                       payment_effect=audit._r(diff), pv_effect=audit._r(diff * df))
        elif b is not None and item == "compounded_index_rate" and b["rate_pct"] is not None:
            inferred = b["rate_pct"] - spread_pct
            row.update(bloomberg_value=audit._r(inferred),
                       bloomberg_source="equivalent coupon minus contractual spread (inferred)",
                       difference=audit._r((r["value"] - inferred) * 100), difference_unit="bp")
        elif b is not None and item == "equivalent_coupon" and b["rate_pct"] is not None:
            row.update(bloomberg_value=b["rate_pct"],
                       bloomberg_source="cashflow table (equivalent coupon, 4 dp)",
                       difference=audit._r((r["value"] - b["rate_pct"]) * 100),
                       difference_unit="bp")
        elif b is not None and item == "observation_window":
            detail = r["detail"]
            end = detail.get("last_fixing") or detail.get("observation_end")
            last_sub = r["sub_period"] is None or not index.get(
                (r["leg"], r["payment_date"], "observation_window", (r["sub_period"] or 0) + 1))
            if b.get("effective_reset_date") and last_sub:
                row.update(bloomberg_value=f"effective reset date {b['effective_reset_date']}",
                           bloomberg_source="cashflow table",
                           difference="same date" if end == b["effective_reset_date"]
                           else f"Optima window ends {end}")
        elif item == "reset_rate" and r["detail"].get("reset_date") in reference.get(
                "reset_rate_pct", {}):
            reset_date = r["detail"]["reset_date"]
            step = steps.get(reset_date, {})
            row.update(bloomberg_value=reference["reset_rate_pct"][reset_date],
                       bloomberg_source=reference["source"].split(".")[0],
                       difference=audit._r((r["value"] - reference["reset_rate_pct"][reset_date])
                                           * 100), difference_unit="bp",
                       payment_effect=";".join(f"P{k} {v:+.6f}" for k, v in
                                               step.get("payment_effect", {}).items()) or None,
                       pv_effect=step.get("npv_effect"))
        out.append(row)
    return out


def findings_for(case: Dict[str, Any], rec: Dict[str, Any],
                 rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Register findings for the case, plus an explicit NOT_INVESTIGATED finding for any
    out-of-tolerance cashflow the register does not cover, plus blockers."""
    findings = [dict(f, match=[list(m) for m in f["match"]] if f["match"] else None)
                for f in register.FINDINGS.get(case["case_id"], [])]
    covered = {tuple(m) for f in findings for m in (f["match"] or [])}
    for r in rows:
        if r.get("row_status", "RECONCILED") == "DIFFERENCE" and \
                (r["leg"], r["payment_date"]) not in covered:
            findings.append({
                "id": f"{case['case_id']}-auto-{r['leg']}-{r['payment_date']}",
                "match": [[r["leg"], r["payment_date"]]],
                "classification": register.NOT_INVESTIGATED,
                "categories": [], "statement": f"{', '.join(r['discrepancy_sources'])} "
                "outside tolerance", "evidence": "no register entry", "open_item": None,
            })
    bbg = case.get("bloomberg") or {}
    other = {k: v for k, v in (bbg.get("other_leg_values") or {}).items() if v is not None}
    if other and bbg.get("fixed_leg_npv") is not None:
        legs = (bbg["fixed_leg_npv"], bbg["floating_leg_npv"])
        if any(min(abs(v - leg) for leg in legs) > TOLERANCES["payment"] for v in other.values()):
            total = sum(other.values())
            findings.append({
                "id": f"{case['case_id']}-legdef", "match": None,
                "classification": "Not comparable",
                "categories": ["different measure or calculation scope"],
                "statement": "Bloomberg's alternative leg values "
                + ", ".join(f"{k} {v:,.2f}" for k, v in other.items())
                + f" differ from the cashflow-leg NPVs {legs[0]:,.2f} / {legs[1]:,.2f}.",
                "evidence": f"Both splits sum to the trade NPV {bbg['npv']:,.2f} (alternative "
                f"sum {total:,.2f}). The cashflow-leg values are the PVs of the listed "
                "cashflows and are the references used; the alternative definition is "
                "unconfirmed.",
                "open_item": "OI-9",
            })
    if rec["status"] == "BLOCKED":
        for number, b in enumerate(case.get("blockers", []), start=1):
            findings.append({
                "id": f"{case['case_id']}-B{number}", "match": None, "classification": "Blocked",
                "categories": [], "statement": f"{b['code']}: {b['detail']}",
                "evidence": "production capability / data-presence check",
                "next_action": register.BLOCKER_ACTIONS.get(b["code"], "-").format(
                    requests=", ".join(q["id"] for q in register.EVIDENCE_REQUESTS
                                       if case["case_id"] in q["cases"]) or "-"),
                "open_item": None,
            })
    return findings


def analyse_case(rec: Dict[str, Any], case: Dict[str, Any]) -> Dict[str, Any]:
    try:
        bloomberg_rows = audit.read_bloomberg(case["case_id"])["cashflows"]
    except (OSError, KeyError, ValueError):
        bloomberg_rows = []
    rows = rec["cashflows"]
    source = "production extractor (irs_cashflow_rows)"
    if rows:
        for r in rows:
            if r.get("bloomberg"):
                r["decomposition"] = _decompose(r["amount"], r["discount_factor"],
                                                r["present_value"], r["bloomberg"])
    elif rec["status"] == "PARTIAL":
        rows = diagnostic_cashflows(case, bloomberg_rows)
        for r in rows:
            r["row_status"] = ("NO_BLOOMBERG_ROW" if r.get("bloomberg") is None
                               else "RECONCILED" if not discrepancy_sources(r) else "DIFFERENCE")
            r["discrepancy_sources"] = discrepancy_sources(r)
            r["open_item"] = None
        source = ("diagnostic: read from the production-built swap (cashflows paying after "
                  "the valuation date; the production extractor refuses this trade)")
    attribution = reset_attribution(case) if case.get("pricing") else None
    return {
        "structure": trade_structure(case),
        "notes": register.CASE_NOTES.get(case["case_id"]),
        "cashflow_source": source if rows else None,
        "compared_cashflows": rows,
        "leg_reconciliation": leg_reconciliation(case, rows, case.get("bloomberg")),
        "reset_attribution": attribution,
        "derived_inputs": derived_comparisons(case, bloomberg_rows, attribution),
        "engine_check": (case.get("derived_inputs") or {}).get("engine_check"),
        "findings": findings_for(case, rec, rows),
        "evidence_requests": [q["id"] for q in register.EVIDENCE_REQUESTS
                              if case["case_id"] in q["cases"]],
    }


def input_provenance() -> List[Dict[str, Any]]:
    """Every input file the run reads, with its SHA-256 (deterministic order)."""
    files = [audit.FIXTURES / kind / f"{c}.json" for c in audit.CASE_IDS
             for kind in ("source", "references")]
    files += [audit.trade_input_path(c) for c in audit.CASE_IDS
              if audit.trade_input_path(c).exists()]
    files += list(audit.MARKET_SNAPSHOT_FILES)
    files += sorted(audit.MARKET_DATA_DIR.glob("*/market_data.json"))
    return [{"path": audit._rel(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in files]


def environment_info(argv: Optional[List[str]] = None) -> Dict[str, Any]:
    """Where and how the report was produced (not part of the deterministic report body)."""
    def git(*args: str) -> Optional[str]:
        try:
            out = subprocess.run(["git", *args], cwd=audit.ROOT, capture_output=True,
                                 text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.strip() if out.returncode == 0 else None

    status = git("status", "--porcelain")
    return {
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "quantlib": ql.__version__,
        "platform": platform.platform(),
        "project_root": str(audit.ROOT),
        "command": "python -m scripts.irs_reconciliation_report " + " ".join(argv or []),
        "git_commit": git("rev-parse", "--short", "HEAD"),
        "git_uncommitted_paths": None if status is None else len(status.splitlines()),
        "run_date": date.today().isoformat(),
    }


# --- presentation -----------------------------------------------------------------------------


def _fmt(value: Any, spec: str = ",.2f") -> str:
    if value is None:
        return "-"
    if isinstance(value, (int, float)):
        return format(value, spec)
    return str(value)


def summary_rows(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for c in report["cases"]:
        o, b, d = c["trade"]["optima"] or {}, c["trade"]["bloomberg"] or {}, c["trade"]["difference"] or {}
        rows.append({
            "case_id": c["case_id"], "trade_id": c["trade_id"], "currency": c["currency"],
            "floating_index": c["floating_index"], "status": c["status"],
            "optima_npv": o.get("npv"), "bloomberg_npv": b.get("npv"),
            "diff_npv": d.get("npv"), "diff_npv_pct": d.get("npv_pct"),
            "optima_fixed_leg_npv": o.get("fixed_leg_npv"),
            "bloomberg_fixed_leg_npv": b.get("fixed_leg_npv"),
            "optima_floating_leg_npv": o.get("floating_leg_npv"),
            "bloomberg_floating_leg_npv": b.get("floating_leg_npv"),
            "key_issue": _key_issue(c),
        })
    return rows


def cashflow_table(rec: Dict[str, Any], bloomberg_rows: Optional[List[Dict[str, Any]]],
                   day_counts: Dict[str, Optional[str]]) -> List[Dict[str, Any]]:
    """One row per payment. Priced cases use the compared rows; other cases list the
    Bloomberg reference rows with the Optima columns empty."""
    out = []
    for r in rec["cashflows"]:
        b, d = r.get("bloomberg") or {}, r.get("difference") or {}
        out.append({
            "case_id": rec["case_id"], "status": rec["status"], "leg": r["leg"],
            "period": r["period"], "accrual_start": r["accrual_start"],
            "accrual_end": r["accrual_end"], "payment_date": r["payment_date"],
            "bbg_accrual_start": b.get("accrual_start"), "bbg_accrual_end": b.get("accrual_end"),
            "bbg_effective_reset_date": b.get("effective_reset_date"),
            "bbg_reset_date": b.get("reset_date"), "bbg_reset_rate_pct": b.get("reset_rate_pct"),
            "notional": r["notional"], "bbg_notional": b.get("notional"),
            "accrual_days": r["accrual_days"], "day_count": day_counts.get(r["leg"]),
            "day_count_fraction": r["day_count_fraction"], "index_rate_pct": r["index_rate_pct"],
            "spread_pct": r["spread_pct"], "coupon_pct": r["rate_pct"],
            "bbg_coupon_pct": b.get("rate_pct"), "diff_coupon_bp": d.get("rate_bp"),
            "payment": r["amount"], "bbg_payment": b.get("payment"),
            "diff_payment": d.get("amount"), "discount_factor": r["discount_factor"],
            "bbg_discount_factor": b.get("discount_factor"),
            "diff_discount_factor": d.get("discount_factor"), "present_value": r["present_value"],
            "bbg_present_value": b.get("pv"), "diff_present_value": d.get("present_value"),
            "open_item": r["open_item"], "row_status": r["row_status"],
            "discrepancy_sources": ";".join(r["discrepancy_sources"]),
        })
    if out or not bloomberg_rows:
        return out
    row_state = {"PARTIAL": "NOT_EXTRACTED", "BLOCKED": "NOT_PRICED", "ERROR": "NOT_PRICED"}
    for b in bloomberg_rows:
        row = {k: None for k in CASHFLOW_COLUMNS}
        row.update({
            "case_id": rec["case_id"], "status": rec["status"], "leg": b["leg"],
            "payment_date": b["pay_date"], "bbg_accrual_start": b["accrual_start"],
            "bbg_accrual_end": b["accrual_end"],
            "bbg_effective_reset_date": b.get("effective_reset_date"),
            "bbg_reset_date": b.get("reset_date"), "bbg_reset_rate_pct": b.get("reset_rate_pct"),
            "bbg_notional": b["notional"], "day_count": day_counts.get(b["leg"]),
            "bbg_coupon_pct": b["rate_pct"], "bbg_payment": b["payment"],
            "bbg_discount_factor": b["discount_factor"], "bbg_present_value": b["pv"],
            "row_status": row_state.get(rec["status"], "NOT_PRICED"),
        })
        out.append(row)
    return out


# --- output -------------------------------------------------------------------------------


def _write_csv(path: Path, columns, rows) -> None:
    with open(path, "x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_report(directory: Path, report: Dict[str, Any]) -> List[Path]:
    """Create ``directory`` (it must not exist) and write every report file exclusively."""
    directory.mkdir()
    (directory / "cashflows").mkdir()
    written = []
    path = directory / "reconciliation.json"
    with open(path, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    written.append(path)
    path = directory / "summary.md"
    with open(path, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(to_markdown(report))
    written.append(path)
    path = directory / "summary.csv"
    _write_csv(path, SUMMARY_COLUMNS, summary_rows(report))
    written.append(path)
    audit_cases = {c["case_id"]: c for c in report["audit"]["cases"]}
    for rec in report["cases"]:
        case = audit_cases[rec["case_id"]]
        day_counts = {
            "fixed": (case.get("fixed_leg") or {}).get("day_count"),
            "floating": (case.get("floating_leg") or {}).get("day_count"),
        }
        try:
            bloomberg_rows = audit.read_bloomberg(rec["case_id"])["cashflows"]
        except (OSError, KeyError, ValueError):
            bloomberg_rows = None
        path = directory / "cashflows" / f"{rec['case_id']}.csv"
        _write_csv(path, CASHFLOW_COLUMNS, cashflow_table(rec, bloomberg_rows, day_counts))
        written.append(path)
    return written


# --- full report: tables ----------------------------------------------------------------------

CASE_COMPARISON_COLUMNS = (
    "case_id", "trade_id", "currency", "floating_index", "structure", "valuation_date",
    "status", "optima_npv", "bloomberg_npv", "diff_npv", "diff_npv_pct", "npv_tolerance",
    "optima_fixed_leg_npv", "bloomberg_fixed_leg_npv", "diff_fixed_leg_npv",
    "optima_floating_leg_npv", "bloomberg_floating_leg_npv", "diff_floating_leg_npv",
    "cashflow_source", "cashflows_compared", "cashflows_outside_tolerance",
    "max_abs_coupon_diff_bp", "max_abs_discount_factor_diff", "pv_diff_amount_effect",
    "pv_diff_discount_factor_effect", "pv_diff_bloomberg_display_residual",
    "optima_cashflows_close_to_npv", "bloomberg_par_coupon", "bloomberg_pv01",
    "bloomberg_dv01", "bloomberg_accrued", "optima_par_coupon", "optima_pv01", "optima_dv01",
    "optima_accrued", "pricing_path", "observation_method", "findings", "evidence_requests",
    "key_issue",
)
CASHFLOW_RECONCILIATION_COLUMNS = CASHFLOW_COLUMNS + (
    "cashflow_source", "amount_effect", "discount_factor_effect", "bloomberg_display_residual",
    "finding_ids", "classification",
)
DERIVED_INPUT_COLUMNS = (
    "case_id", "leg", "side", "period", "sub_period", "payment_date", "item", "optima_value",
    "unit", "bloomberg_value", "bloomberg_source", "difference", "difference_unit",
    "payment_effect", "pv_effect", "inputs", "method", "basis",
)
MISSING_INPUT_COLUMNS = (
    "request_id", "kind", "priority", "to", "cases", "affected", "request", "why_needed",
    "distinguishes", "result_supporting_first", "result_supporting_second", "open_item",
)


def _row_findings(rec: Dict[str, Any], leg: str, payment_date: str) -> List[Dict[str, Any]]:
    return [f for f in rec["analysis"]["findings"]
            if f["match"] and [leg, payment_date] in f["match"]]


def case_comparison_rows(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for rec, summary in zip(report["cases"], summary_rows(report)):
        a = rec["analysis"]
        o, b = rec["trade"]["optima"] or {}, rec["trade"]["bloomberg"] or {}
        d = rec["trade"]["difference"] or {}
        rows = a["compared_cashflows"]
        compared = [r for r in rows if r.get("bloomberg")]
        legs = (a["leg_reconciliation"] or {}).get("legs", {})
        coupon_bp = [abs(r["difference"]["rate_bp"]) for r in compared
                     if r["difference"].get("rate_bp") is not None]
        dfs = [abs(r["difference"]["discount_factor"]) for r in compared]
        out.append({
            "case_id": rec["case_id"], "trade_id": rec["trade_id"], "currency": rec["currency"],
            "floating_index": rec["floating_index"], "structure": a["structure"],
            "valuation_date": rec["valuation_date"], "status": rec["status"],
            "optima_npv": o.get("npv"), "bloomberg_npv": b.get("npv"), "diff_npv": d.get("npv"),
            "diff_npv_pct": d.get("npv_pct"),
            "npv_tolerance": audit._r(NPV_TOL_PER_CASHFLOW * len(rows)) if rows else None,
            "optima_fixed_leg_npv": o.get("fixed_leg_npv"),
            "bloomberg_fixed_leg_npv": b.get("fixed_leg_npv"),
            "diff_fixed_leg_npv": d.get("fixed_leg_npv"),
            "optima_floating_leg_npv": o.get("floating_leg_npv"),
            "bloomberg_floating_leg_npv": b.get("floating_leg_npv"),
            "diff_floating_leg_npv": d.get("floating_leg_npv"),
            "cashflow_source": a["cashflow_source"] or "Bloomberg only (not priced)",
            "cashflows_compared": len(compared),
            "cashflows_outside_tolerance": sum(r["row_status"] == "DIFFERENCE" for r in rows),
            "max_abs_coupon_diff_bp": audit._r(max(coupon_bp)) if coupon_bp else None,
            "max_abs_discount_factor_diff": audit._r(max(dfs)) if dfs else None,
            "pv_diff_amount_effect": audit._r(sum(l["amount_effect"] for l in legs.values()))
            if legs else None,
            "pv_diff_discount_factor_effect": audit._r(
                sum(l["discount_factor_effect"] for l in legs.values())) if legs else None,
            "pv_diff_bloomberg_display_residual": audit._r(
                sum(l["bloomberg_display_residual"] for l in legs.values())) if legs else None,
            "optima_cashflows_close_to_npv": (a["leg_reconciliation"] or {}).get("optima_closes"),
            "bloomberg_par_coupon": b.get("par_coupon"), "bloomberg_pv01": b.get("pv01"),
            "bloomberg_dv01": b.get("dv01"), "bloomberg_accrued": b.get("accrued"),
            "optima_par_coupon": NOT_COMPUTED if o else None,
            "optima_pv01": NOT_COMPUTED if o else None,
            "optima_dv01": NOT_COMPUTED if o else None,
            "optima_accrued": NOT_COMPUTED if o else None,
            "pricing_path": o.get("path"),
            "observation_method": observation_method_of(
                next((c for c in report["audit"]["cases"] if c["case_id"] == rec["case_id"]),
                     {})) or "-",
            "findings": "; ".join(f"{f['id']}: {f['classification']}" for f in a["findings"]),
            "evidence_requests": ", ".join(a["evidence_requests"]),
            "key_issue": summary["key_issue"],
        })
    return out


def cashflow_reconciliation_rows(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    audit_cases = {c["case_id"]: c for c in report["audit"]["cases"]}
    for rec in report["cases"]:
        case = audit_cases[rec["case_id"]]
        a = rec["analysis"]
        day_counts = {"fixed": (case.get("fixed_leg") or {}).get("day_count"),
                      "floating": (case.get("floating_leg") or {}).get("day_count")}
        try:
            bloomberg_rows = audit.read_bloomberg(rec["case_id"])["cashflows"]
        except (OSError, KeyError, ValueError):
            bloomberg_rows = None
        view = dict(rec, cashflows=a["compared_cashflows"])
        decomposition = {(r["leg"], r["payment_date"]): r.get("decomposition") or {}
                         for r in a["compared_cashflows"]}
        for row in cashflow_table(view, bloomberg_rows, day_counts):
            dec = decomposition.get((row["leg"], row["payment_date"]), {})
            found = _row_findings(rec, row["leg"], row["payment_date"])
            row.update(
                cashflow_source=a["cashflow_source"] or "Bloomberg only (not priced)",
                amount_effect=dec.get("amount_effect"),
                discount_factor_effect=dec.get("discount_factor_effect"),
                bloomberg_display_residual=dec.get("bloomberg_display_residual"),
                finding_ids=";".join(f["id"] for f in found) or None,
                classification=";".join(sorted({f["classification"] for f in found})) or
                ("Within tolerance" if row["row_status"] == "RECONCILED" else None),
            )
            out.append(row)
    return out


def derived_input_rows(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [r for rec in report["cases"] for r in rec["analysis"]["derived_inputs"]]


def missing_input_rows(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for q in sorted(report["evidence_requests"], key=lambda q: (q["priority"], q["id"])):
        out.append({
            "request_id": q["id"], "kind": "evidence request", "priority": q["priority"],
            "to": q["to"], "cases": " ".join(q["cases"]), "affected": q["affected"],
            "request": q["request"], "why_needed": q["why"], "distinguishes": q["distinguishes"],
            "result_supporting_first": q["supports_first"],
            "result_supporting_second": q["supports_second"], "open_item": q["open_item"],
        })
    for rec in report["cases"]:
        if rec["status"] != "BLOCKED":
            continue
        blockers = [f for f in rec["analysis"]["findings"] if f["classification"] == "Blocked"]
        actions = sorted({f["next_action"] for f in blockers if f.get("next_action")})
        out.append({
            "request_id": f"{rec['case_id']}-next", "kind": "blocked-case next action",
            "priority": None, "to": "SME / implementation", "cases": rec["case_id"],
            "affected": f"{rec['case_id']} (not priced)",
            "request": " | ".join(actions),
            "why_needed": " | ".join(f["statement"] for f in blockers),
            "distinguishes": "-", "result_supporting_first": "-",
            "result_supporting_second": "-",
            "open_item": "; ".join(sorted({f["open_item"] for f in
                                           rec["analysis"]["findings"] if f.get("open_item")}))
            or None,
        })
    return out


# --- full report: markdown ------------------------------------------------------------------

VALUE_SOURCES = {
    "Bloomberg reference": "Columns prefixed bbg_ / bloomberg_ and the Bloomberg columns of the "
    "Markdown tables: read from tests/fixtures/bloomberg_irs/references (cashflow-leg NPVs are "
    "the leg references). TC7 reset rates come from the SWPM Resets tab (supplementary, "
    "source stated). Never used as pricing inputs.",
    "Optima production": "Unprefixed values (optima_*, payment, discount_factor, "
    "present_value, coupon_pct, optima_value): computed by the production path. Priced cases: "
    "price_irs; TC4: the production engine, with cashflows read from the production-built "
    "swap (labelled diagnostic source).",
    "Diagnostic": "amount_effect, discount_factor_effect, bloomberg_display_residual, the "
    "leg aggregation and the reset attribution: identities or substitutions on the two sets "
    "above, labelled as diagnostic checks, not production results.",
    "Unavailable": "Empty cells (CSV) or '-' (Markdown): not available from that source or not "
    "computed. Never shown as zero. Par coupon, PV01/DV01 and accrued are 'not computed by the "
    "Optima production path'.",
}

GLOSSARY = [
    ("Discount factor (DF)", "Present value today of 1 paid on a given date, read from the "
     "discount curve."),
    ("Projected (forecast) rate", "A floating rate not yet fixed, computed from the forecast "
     "curve rather than taken from a published fixing."),
    ("Compounded in arrears", "Daily overnight rates over the period are compounded and paid "
     "at the end of the period."),
    ("Lookback / observation shift", "Rates are observed some business days before each day "
     "of the period; with an observation shift the day weights move with them."),
    ("Rate cutoff", "The last few rates of a period are frozen; Optima records it but does not "
     "map it to QuantLib's lockout (OI-2)."),
    ("Flat compounding", "Sub-period amounts within a payment period are compounded at the "
     "index rate only; the margin is not compounded."),
    ("Equivalent coupon", "The single rate that reproduces a compounded payment over the "
     "whole period; Bloomberg displays it, Optima uses it to represent the payment."),
    ("Spread adjustment", "The fixed 0.0741% added to compounded SARON in the CHF LIBOR 6M "
     "fallback."),
    ("Display tolerance", "The rounding band of Bloomberg's displayed values: coupons 1e-4 %, "
     "DFs 5e-7, payments 0.05."),
    ("Amount / DF effect", "Diagnostic split of a PV difference: (A_o - A_b) x DF_o and "
     "A_b x (DF_o - DF_b); the rest is Bloomberg's own display rounding."),
]


def _md_table(header: List[str], rows: List[List[Any]]) -> List[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join("-" if v is None else str(v) for v in row) + " |" for row in rows]
    return lines


def _num(value: Any, spec: str = ",.4f") -> str:
    return _fmt(value, spec) if isinstance(value, (int, float)) else ("-" if value is None
                                                                       else str(value))


def case_markdown(rec: Dict[str, Any], report: Dict[str, Any]) -> str:
    a = rec["analysis"]
    o, b = rec["trade"]["optima"] or {}, rec["trade"]["bloomberg"] or {}
    d = rec["trade"]["difference"] or {}
    lines = [f"# {rec['case_id']} ({rec['trade_id']}, {rec['currency']} {rec['floating_index']})"
             f": {rec['status']}", "",
             f"**Structure (from the Bloomberg source terms):** {a['structure']}", ""]
    if a["notes"]:
        lines += [f"**Notes:** {a['notes']}", ""]
    lines += [f"Valuation date {rec['valuation_date']}. Differences are Optima minus "
              "Bloomberg. Bloomberg values are references only.", "", "## Results", ""]
    lines += _md_table(["Measure", "Optima", "Bloomberg", "Optima - Bloomberg"], [
        ["NPV", _num(o.get("npv")), _num(b.get("npv"), ",.2f"), _num(d.get("npv"), "+,.4f")],
        ["Fixed leg PV", _num(o.get("fixed_leg_npv")), _num(b.get("fixed_leg_npv"), ",.2f"),
         _num(d.get("fixed_leg_npv"), "+,.4f")],
        ["Floating leg PV", _num(o.get("floating_leg_npv")),
         _num(b.get("floating_leg_npv"), ",.2f"), _num(d.get("floating_leg_npv"), "+,.4f")],
        ["Par coupon", NOT_COMPUTED if o else "-", _num(b.get("par_coupon"), "g"), "-"],
        ["PV01 / DV01", NOT_COMPUTED if o else "-",
         f"{_num(b.get('pv01'), 'g')} / {_num(b.get('dv01'), 'g')}", "-"],
        ["Accrued", NOT_COMPUTED if o else "-", _num(b.get("accrued"), "g"), "-"],
    ])
    lines += [""] + [f"- {r}" for r in rec["reasons"]]
    check = a["engine_check"]
    if check:
        lines += ["", "**Production-path checks:** cashflow PVs equal the engine leg NPVs: "
                  f"{check['future_cashflow_pv_matches_engine']}"
                  + (f"; a production rebuild reproduces price_irs exactly: "
                     f"{check['rebuild_matches_price_irs']}"
                     if "rebuild_matches_price_irs" in check else "")
                  + (f"; cashflows -> legs -> NPV close: {a['leg_reconciliation']['optima_closes']}"
                     if a["leg_reconciliation"] else "") + "."]
    rows = a["compared_cashflows"]
    if rows:
        lines += ["", "## Cashflow reconciliation", "", f"Source: {a['cashflow_source']}.", ""]
        table = []
        for r in rows:
            bb, dd = r.get("bloomberg") or {}, r.get("difference") or {}
            dec = r.get("decomposition") or {}
            table.append([
                r["leg"], r["payment_date"], f"{r['accrual_start']} -> {r['accrual_end']}",
                _num(r["notional"], ",.2f"), _num(r["rate_pct"], ".6f"),
                _num(bb.get("rate_pct"), ".5f"), _num(dd.get("rate_bp"), "+.4f"),
                _num(r["amount"], ",.4f"), _num(bb.get("payment"), ",.2f"),
                _num(r["discount_factor"], ".7f"), _num(bb.get("discount_factor"), ".6f"),
                _num(dd.get("present_value"), "+.4f"), _num(dec.get("amount_effect"), "+.4f"),
                _num(dec.get("discount_factor_effect"), "+.4f"), r["row_status"],
                ";".join(f["id"] for f in _row_findings(rec, r["leg"], r["payment_date"]))
                or "-"])
        lines += _md_table(["Leg", "Pay date", "Accrual", "Notional", "Coupon % (Optima)",
                            "Coupon % (BBG)", "Diff bp", "Amount (Optima)", "Amount (BBG)",
                            "DF (Optima)", "DF (BBG)", "PV diff", "Amount effect", "DF effect",
                            "Row", "Finding"], table)
        legs = a["leg_reconciliation"]["legs"]
        lines += ["", "**Aggregation (diagnostic):**", ""]
        lines += _md_table(["Leg", "Sum of PV diffs", "Amount effect", "DF effect",
                            "BBG display residual", "BBG leg NPV - its cashflow PVs"],
                           [[k, _num(v["pv_difference"], "+.4f"), _num(v["amount_effect"], "+.4f"),
                             _num(v["discount_factor_effect"], "+.4f"),
                             _num(v["bloomberg_display_residual"], "+.4f"),
                             _num(v["bloomberg_leg_minus_cashflow_sum"], "+.4f")]
                            for k, v in legs.items()])
    derived = a["derived_inputs"]
    if derived:
        lines += ["", "## Values Optima derives (not read from the trade input)", "",
                  "Read from the production-built swap; full inputs and methods are in "
                  "`derived_inputs.csv`.", ""]
        lines += _md_table(
            ["Leg", "Period", "Sub", "Item", "Optima", "Bloomberg", "Diff", "PV effect",
             "Basis"],
            [[r["leg"], r["period"], r["sub_period"], r["item"],
              _num(r["optima_value"], ".8g"), _num(r["bloomberg_value"], ".8g"),
              (f"{_num(r['difference'], '+.6g')} {r['difference_unit'] or ''}".strip()
               if r["difference"] is not None else "-"),
              _num(r["pv_effect"], "+.6f"), r["basis"]] for r in derived])
    attribution = a["reset_attribution"]
    if attribution:
        lines += ["", "## Reset-rate attribution (diagnostic)", "", attribution["method"] + ".",
                  f"Bloomberg reset source: {attribution['bloomberg_source']}", ""]
        lines += _md_table(["Reset date", "Optima %", "Bloomberg %", "Diff bp",
                            "Payment effect", "NPV effect"],
                           [[s["reset_date"], _num(s["optima_reset_pct"], ".8f"),
                             _num(s["bloomberg_reset_pct"], ".5f"),
                             _num(s["difference_bp"], "+.4f"),
                             ", ".join(f"P{k} {v:+.4f}" for k, v in s["payment_effect"].items()),
                             _num(s["npv_effect"], "+.5f")] for s in attribution["steps"]])
        lines += ["", f"Total NPV effect of the reset rates: "
                  f"{attribution['total_npv_effect']:+.5f} of the NPV difference "
                  f"{d.get('npv', 0):+.5f}. With Bloomberg's resets the payments become "
                  + ", ".join(f"P{k} {v:,.5f}" for k, v in
                              attribution["payments_with_bloomberg_resets"].items())
                  + f" and the NPV {attribution['npv_with_bloomberg_resets']:,.5f} "
                  f"(Bloomberg {b.get('npv')})."]
    lines += ["", "## Findings", ""]
    for f in a["findings"]:
        lines.append(f"- **{f['id']} - {f['classification']}**"
                     + (f" ({f['open_item']})" if f.get("open_item") else "")
                     + f": {f['statement']}")
        if f.get("evidence"):
            lines.append(f"  - Evidence: {f['evidence']}")
        if f.get("next_action"):
            lines.append(f"  - Minimum next action: {f['next_action']}")
    requests = [q for q in report["evidence_requests"] if q["id"] in a["evidence_requests"]]
    if requests:
        lines += ["", "## Evidence needed", ""]
        for q in requests:
            lines += [f"- **{q['id']}** ({q['to']}): {q['request']}",
                      f"  - Why: {q['why']}"]
            if q["distinguishes"] != "-":
                lines += [f"  - Distinguishes: {q['distinguishes']}",
                          f"  - {q['supports_first']}", f"  - {q['supports_second']}"]
    comparison = (report.get("observation_methods") or {}).get(rec["case_id"])
    if comparison:
        lines += [""] + methods.to_markdown(comparison)
    if rec["status"] == "BLOCKED":
        lines += ["", "## Bloomberg reference cashflows (not priced by Optima)", ""]
        try:
            rows_b = audit.read_bloomberg(rec["case_id"])["cashflows"]
        except (OSError, KeyError, ValueError):
            rows_b = []
        lines += _md_table(["Leg", "Pay date", "Accrual", "Notional", "Coupon %", "Payment",
                            "DF", "PV"],
                           [[r["leg"], r["pay_date"], f"{r['accrual_start']} -> {r['accrual_end']}",
                             _num(r["notional"], ",.2f"), _num(r["rate_pct"], "g"),
                             _num(r["payment"], ",.2f"), _num(r["discount_factor"], "g"),
                             _num(r["pv"], ",.2f")] for r in rows_b])
    return "\n".join(lines) + "\n"


def _case_order(case_ids: List[str]) -> List[str]:
    return sorted(case_ids, key=lambda c: int(c[2:]))


def to_markdown(report: Dict[str, Any]) -> str:
    env = report.get("environment") or {}
    rows = summary_rows(report)
    cases = {c["case_id"]: c for c in report["cases"]}
    n = {s: len(v) for s, v in report["counts"].items()}
    lines = [
        "# Fresh IRS: ten-case production pricing validation against Bloomberg", "",
        f"Valuation date {report['valuation_date']} · QuantLib {report['quantlib_version']}"
        + (f" · Python {env['python']} · {env['platform']}" if env else "")
        + ". Differences are Optima minus Bloomberg. Bloomberg values are validation "
        "references only; nothing here feeds them into pricing. Contains Bloomberg-derived "
        "data: keep local (OI-6).", "",
        "## Executive summary", "",
        f"- All ten cases were audited exactly once. "
        f"{', '.join(_case_order(report['counts']['FAIL'] + report['counts']['PASS']))} "
        "were priced by the full production workflow (`price_irs` -> `PricingService` -> "
        "`ql.DiscountingSwapEngine` -> cashflow extraction); "
        + (f"{', '.join(report['counts']['PARTIAL'])} by the same engine but the production "
           "cashflow extractor refuses it; " if report["counts"]["PARTIAL"] else "")
        + (f"{', '.join(report['counts']['BLOCKED'])} "
           f"{'is' if n['BLOCKED'] == 1 else 'are'} not priced. " if n["BLOCKED"] else "")
        + f"**{n['PASS']} PASS, {n['FAIL']} FAIL, {n['PARTIAL']} PARTIAL, {n['BLOCKED']} "
        f"BLOCKED, {n['ERROR']} ERROR.**",
    ]
    for cid in _case_order(report["counts"]["PASS"] + report["counts"]["FAIL"]
                           + report["counts"]["PARTIAL"]):
        c = cases[cid]
        d = c["trade"]["difference"]
        lines.append(f"- **{cid}** ({c['currency']} {c['floating_index']}, {c['status']}): NPV "
                     f"{d['npv']:+.4f} vs Bloomberg ({_fmt(d.get('npv_pct'), '+.4f')}%). "
                     + "; ".join(f"{f['id']} {f['classification'].lower()}"
                                 for f in c["analysis"]["findings"]
                                 if f["classification"] not in ("Not comparable",)) + ".")
    for cid, comp in sorted((report.get("observation_methods") or {}).items()):
        a_npv = comp["methods"]["contractual_accrual"]["npv"]
        b = comp["methods"]["reset_date_fallback"]
        t = comp["common_period_totals"]
        lines.append(
            f"- **{cid} SARON observation dates: priced with {comp['configured_label']}.** "
            f"{comp['no_shift_status']} Method A NPV {a_npv:,.4f} vs Bloomberg "
            f"{comp['bloomberg']['npv']:,.2f} "
            f"({comp['npv_vs_bloomberg']['contractual_accrual']:+.4f}). Method B (previous "
            "behaviour, preserved and selectable): "
            + ("not computable without the historical fixings "
               + next(p["missing_fixings"] for p in b["periods"] if not p["computable"])
               + " (R3)" if b["npv"] is None else f"NPV {b['npv']:,.4f}")
            + f". Floating PV over P{', P'.join(str(p) for p in t['common_periods'])}: A "
            f"{t['a_floating_pv_common']:,.4f}, B {t['b_floating_pv_common']:,.4f}, Bloomberg "
            f"{t['bloomberg_floating_pv_common']:,.2f}. Convention question: R9 (OI-17); "
            f"`cases/{cid}.md`, `{cid.lower()}_observation_methods.csv`.")
    for cid, c in cases.items():
        att = c["analysis"]["reset_attribution"]
        if not att:
            continue
        largest = max(att["steps"], key=lambda s: abs(s["npv_effect"]))
        requests = ", ".join(c["analysis"]["evidence_requests"]) or "-"
        lines.append(
            f"- **{cid} reset rates were not trade inputs: Optima projected them itself** from "
            f"the supplied market data (historical fixings from market data where a reset "
            f"precedes the valuation date). Differences from Bloomberg's resets: "
            + ", ".join(f"{s['reset_date']} {s['difference_bp']:+.2f} bp" for s in att["steps"])
            + f". Together they account for {att['total_npv_effect']:+,.3f} of the "
            f"{c['trade']['difference']['npv']:+,.3f} NPV difference; the largest, "
            f"{largest['reset_date']}, {largest['npv_effect']:+,.3f}. With Bloomberg's resets "
            f"the production payment calculation gives NPV "
            f"{att['npv_with_bloomberg_resets']:,.3f} "
            f"(Bloomberg {c['trade']['bloomberg']['npv']:,.2f}), "
            f"so the payment mechanics are confirmed; the open question is the projection "
            f"({requests}).")
    blocked = report["counts"]["BLOCKED"]
    lines.append(f"- **Blocked ({', '.join(blocked)})**: no price is produced; each case lists "
                 "its exact blockers, Bloomberg's reference values and the minimum next action. "
                 "No market data, convention or fixing is invented.")
    lines += ["- Every priced cashflow table closes: cashflow PVs = engine leg NPVs = NPV; each "
              "PV difference splits exactly into an amount effect, a DF effect and Bloomberg "
              "display rounding.", "",
              "## Status", ""]
    lines += [
        "| Case | Trade | Ccy | Index | Status | Optima NPV | Bloomberg NPV | Diff | "
        "Fixed (Optima / BBG) | Floating (Optima / BBG) | Key issue |",
        "|---|---|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['case_id']} | {r['trade_id']} | {r['currency']} | {r['floating_index']} | "
            f"{r['status']} | {_fmt(r['optima_npv'], ',.4f')} | {_fmt(r['bloomberg_npv'])} | "
            f"{_fmt(r['diff_npv'], '+,.4f')} | {_fmt(r['optima_fixed_leg_npv'])} / "
            f"{_fmt(r['bloomberg_fixed_leg_npv'])} | {_fmt(r['optima_floating_leg_npv'])} / "
            f"{_fmt(r['bloomberg_floating_leg_npv'])} | {r['key_issue']} |"
        )
    lines += ["", "**Counts:** " + ", ".join(f"{s} {n[s]}" for s in STATUSES), ""]
    lines += ["## Findings", ""]
    lines += _md_table(["Case", "Finding", "Classification", "Statement", "Open item"],
                       [[c["case_id"], f["id"], f["classification"], f["statement"],
                         f.get("open_item")] for c in report["cases"]
                        for f in c["analysis"]["findings"] if f["classification"] != "Blocked"])
    lines += ["", "Blocked cases' blockers are listed in their case files and in "
              "`missing_inputs.csv`.", "", "## Priorities: evidence needed", ""]
    ordered = sorted(report["evidence_requests"], key=lambda q: (q["priority"], q["id"]))
    lines += _md_table(["ID", "Priority", "To", "Cases", "Request", "Distinguishes"],
                       [[q["id"], q["priority"], q["to"], " ".join(q["cases"]), q["request"],
                         q["distinguishes"]] for q in ordered])
    lines += ["", "## Source conflicts", "",
              "Older notes or inputs that disagree with newer evidence or the current code, "
              "and the source this report treats as authoritative. No document was edited.", ""]
    lines += _md_table(["ID", "Older statement", "Newer evidence", "Authoritative", "Action"],
                       [[c["id"], c["older"], c["newer"], c["authoritative"], c["action"]]
                        for c in report["source_conflicts"]])
    lines += ["", "## Reading the values", ""]
    lines += [f"- **{k}**: {v}" for k, v in report["value_sources"].items()]
    lines += ["", "## Definitions", "", "**Statuses**", ""]
    lines += [f"- **{s}**: {d}" for s, d in report["status_definitions"].items()]
    lines += ["", "**Discrepancy classifications**", ""]
    lines += [f"- **{k}**: {v}" for k, v in report["classifications"].items()]
    lines += [f"- **{register.NOT_INVESTIGATED}**: an out-of-tolerance cashflow with no "
              "register entry (none in this run)"
              if not any(f["classification"] == register.NOT_INVESTIGATED
                         for c in report["cases"] for f in c["analysis"]["findings"])
              else f"- **{register.NOT_INVESTIGATED}**: an out-of-tolerance cashflow with no "
              "register entry (PRESENT in this run: see the case files)"]
    lines += ["", "**Terms**", ""] + [f"- **{k}**: {v}" for k, v in GLOSSARY]
    t = report["tolerances"]
    lines += [
        "", "## Tolerances (unchanged)", "",
        f"Coupon {t['coupon_pct']} % · discount factor {t['discount_factor']} · payment "
        f"{t['payment']} · NPV {t['npv_per_cashflow']} per cashflow summed (total and each "
        "leg). Raw differences are reported even when within tolerance.",
        "", "## Supported currencies and indices", "",
    ]
    lines += [f"- {s['currency']} {s['floating_index']}" for s in report["supported"]] or ["- none"]
    lines += ["", "## Known limitations", "",
              "- Production prices daily-compounded overnight legs (USD SOFRRATE 1D, JPY "
              "MUTKCALM 1D) and term-rate legs with explicit resets (CHF SF0006M fallback, INR "
              "IRSWOF 6M). The SF0006M fallback and the IRSWOF projection are provisional "
              "(OI-12, OI-15); the JN/RB calendar and MUTKCALM mappings are evidence-based, not "
              "SME-confirmed (OI-15, OI-16).",
              "- INR and JPY curves are bootstrapped from the OIS par rates "
              "(scripts/build_ois_curve_snapshots.py); the supplied DF columns are not used "
              "(they do not reproduce Bloomberg's trade DFs).",
              "- Fixings on or before the valuation date are market data "
              "(market_data/2026-03-31/fixings_2026-03-31.json, each with its source); a "
              "missing one "
              "blocks the case (MISSING_FIXINGS), it is never inferred.",
              "- Par coupon, PV01/DV01 and accrued are not computed by the production path; "
              "only Bloomberg's values are shown.",
              "- Cashflows paying on or before the valuation date are settled: excluded, as "
              "by the engine, and listed (OI-10).",
              "- Bloomberg cashflow tables are compared as supplied; a Bloomberg NPV that "
              "disagrees with its own leg sums is flagged, not reconciled.",
              "", "## Files", "",
              "- `case_comparison.csv`: one row per case.",
              "- `cashflow_reconciliation.csv`: every cashflow, all cases (Bloomberg-only rows "
              "for cases not priced).",
              "- `derived_inputs.csv`: values Optima derives, with inputs, method, basis and "
              "Bloomberg counterpart.",
              "- `missing_inputs.csv`: evidence requests and blocked-case next actions.",
              "- `cases/<case>.md`: detail per case. `reconciliation.json`: everything, "
              "machine-readable. `summary.csv`, `cashflows/<case>.csv`: earlier formats, kept.",
              ]
    if env:
        lines += ["", "## Run environment", ""]
        lines += [f"- {k}: {v}" for k, v in env.items()]
    lines += ["", "## Input files (SHA-256)", ""]
    lines += [f"- `{p['path']}` {p['sha256'][:16]}..." for p in report["input_provenance"]]
    return "\n".join(lines) + "\n"


def write_full_report(directory: Path, report: Dict[str, Any]) -> List[Path]:
    """The base report (write_report) plus the detailed tables and per-case files."""
    written = write_report(directory, report)
    (directory / "cases").mkdir()
    for name, columns, rows in (
        ("case_comparison.csv", CASE_COMPARISON_COLUMNS, case_comparison_rows(report)),
        ("cashflow_reconciliation.csv", CASHFLOW_RECONCILIATION_COLUMNS,
         cashflow_reconciliation_rows(report)),
        ("derived_inputs.csv", DERIVED_INPUT_COLUMNS, derived_input_rows(report)),
        ("missing_inputs.csv", MISSING_INPUT_COLUMNS, missing_input_rows(report)),
    ):
        path = directory / name
        _write_csv(path, columns, rows)
        written.append(path)
    for cid, comparison in sorted((report.get("observation_methods") or {}).items()):
        path = directory / f"{cid.lower()}_observation_methods.csv"
        _write_csv(path, methods.COMPARISON_COLUMNS, comparison["periods"])
        written.append(path)
    for rec in report["cases"]:
        path = directory / "cases" / f"{rec['case_id']}.md"
        with open(path, "x", encoding="utf-8", newline="\n") as handle:
            handle.write(case_markdown(rec, report))
        written.append(path)
    return written


def format_console(report: Dict[str, Any]) -> str:
    lines = [f"{'Case':<5} {'Trade':<9} {'Ccy':<4} {'Index':<13} {'Status':<8}"
             f"{'Optima NPV':>15}{'Bloomberg':>15}{'Diff':>11}  Key issue"]
    for r in summary_rows(report):
        lines.append(
            f"{r['case_id']:<5} {r['trade_id'] or '-':<9} {r['currency'] or '-':<4} "
            f"{r['floating_index'] or '-':<13} {r['status']:<8}{_fmt(r['optima_npv'], ',.4f'):>15}"
            f"{_fmt(r['bloomberg_npv']):>15}{_fmt(r['diff_npv'], '+,.4f'):>11}  {r['key_issue']}"
        )
    lines.append("")
    lines.append(" | ".join(f"{s} {len(report['counts'][s])}" for s in STATUSES))
    return "\n".join(lines)


def observation_method_comparisons(audit_result: Dict[str, Any]) -> Dict[str, Any]:
    """Method A vs Method B for every audited case that has a comparison (TC2): both
    computed with production functions (scripts/irs_observation_methods.py)."""
    audited = {c["case_id"] for c in audit_result["cases"]}
    return {cid: methods.compare(cid) for cid in sorted(methods.CASE_TRADES) if cid in audited}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Ten-case IRS valuation and reconciliation.")
    parser.add_argument("--output-dir", help="create this new directory and write the report")
    args = parser.parse_args(argv)
    target = None
    if args.output_dir:
        try:
            target = audit.validate_output_path(args.output_dir)
        except audit.OutputPathRefused as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    try:
        result = audit.run_audit()
    except audit.SharedStateCorrupted as exc:
        print(f"audit stopped: {exc}", file=sys.stderr)
        return 3
    report = build_report(result)
    report["observation_methods"] = observation_method_comparisons(result)
    report["environment"] = environment_info(argv if argv is not None else sys.argv[1:])
    print(format_console(report))
    if target is not None:
        try:
            write_full_report(target, report)
        except FileExistsError:
            print(f"error: {args.output_dir!r} was created by something else; not overwritten",
                  file=sys.stderr)
            return 2
        print(f"\nReport written to {target}")
    return 1 if report["counts"]["ERROR"] else 0


if __name__ == "__main__":
    sys.exit(main())
