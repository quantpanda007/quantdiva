"""Reproducible audit of the ten Bloomberg IRS cases (TC1-TC10) against the fresh
IRS pricing path.

Diagnostic only: it reads fixtures and market data and changes nothing. Run from
the project root:

    python -m scripts.irs_case_audit [--json <path>]

(With the project installed in editable mode, ``python scripts/irs_case_audit.py``
also works.) The console gets a human-readable summary; ``--json`` also writes the
full, deterministic machine-readable result to a new file. The JSON path must not
exist yet and must not be inside ``tests/fixtures``, ``examples`` or
``market_data``. The output contains Bloomberg-derived values: keep it local (OI-6).

Each case is classified as
* ``priced``            - ``price_irs`` (the full production workflow) succeeded;
* ``partially_audited`` - the production engine priced the trade but the full
                          workflow stopped on a documented limitation;
* ``blocked``           - an input or feature is missing; nothing is priced;
* ``error``             - the audit of that case failed unexpectedly (recorded with
                          the stage and exception; other cases still run).

If a case leaves QuantLib's evaluation date or index fixings changed, the audit
stops with ``SharedStateCorrupted`` rather than continuing on corrupted state.

Exit codes: 0 audit completed with no case errors; 1 at least one case error;
2 refused output path; 3 shared state corrupted.

Blockers come from production capability checks (curve assignments in the market
snapshots, ``BENCHMARK_CURVES``, ``AccrualDateAdjustment`` calendars, the
instrument's floating-leg support: daily overnight compounding, or a term-rate
fallback leg in ``TERM_BENCHMARKS``), from unresolved contract terms
(``UNRESOLVED_CONTRACT_TERMS``) and from data-presence checks. No market data,
convention or fixing is invented. Pricing reuses ``price_irs``; for a
partially-audited case it makes the same production calls (``build_trade``,
``resolve_market_environment``, ``PricingService.price``, ``leg_npvs``).

Findings are labelled: ``observations`` are verified by computation;
``hypotheses`` are tested but unconfirmed; ``open_questions`` need external input.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import QuantLib as ql

from core.enums.definitions import BusinessDayConvention
from instruments.rates.irs.cashflows import CashflowExtractionError
from instruments.rates.irs.floating_leg import QuantLibFloatingLeg
from instruments.rates.irs.term_rate_leg import (
    TERM_BENCHMARKS,
    QuantLibTermRateFloatingLeg,
    TermRateFixingRequired,
)
from market.curves.irs_fixings import overnight_fixings_applied
from instruments.rates.irs.pricing_instrument import (
    AccrualDateAdjustment,
    InvalidIRSParameters,
)
from market.curves.irs_market_snapshot import (
    parse_market_snapshot,
    resolve_market_environment,
)
from services.pricers.irs_valuation import (
    BENCHMARK_CURVES,
    build_trade,
    price_irs,
)
from services.pricers.pricing_service import PricingService

ROOT = Path(__file__).resolve().parents[1]
AUDIT_SCHEMA_VERSION = 1
CASE_IDS = tuple(f"TC{i}" for i in range(1, 11))
FIXTURES = ROOT / "tests" / "fixtures" / "bloomberg_irs"
EXAMPLES = ROOT / "examples" / "irs"
# One snapshot file per currency; the audit merges them into one market document.
MARKET_SNAPSHOT_FILES = (
    EXAMPLES / "usd_sofr_2026-03-31.json",
    EXAMPLES / "chf_saron_2026-03-31.json",
    EXAMPLES / "inr_mibor_2026-03-31.json",
    EXAMPLES / "jpy_tona_2026-03-31.json",
    EXAMPLES / "fixings_2026-03-31.json",
)
# Cases whose contractual terms are unresolved: not priced whatever the capability.
# (TC2's fixing-date rule, OI-11, is resolved by evidence on 14-Oct-2026: the source reset
# dates with the rate period starting 1 EN business day later reproduce all seven of
# Bloomberg's observable effective reset dates.)
UNRESOLVED_CONTRACT_TERMS: Dict[str, str] = {}
MARKET_DATA_DIR = ROOT / "market_data" / "2026-03-31"
VALUATION_DATE = date(2026, 3, 31)

# The JSON output may never be written inside these source directories.
PROTECTED_OUTPUT_DIRS = (ROOT / "tests" / "fixtures", ROOT / "examples", ROOT / "market_data")

# Bloomberg display precision. Same values as the TC1 reconciliation test
# (tests/unit/test_irs/test_tc1_bloomberg_reconciliation.py); a test checks they agree.
COUPON_DISPLAY_TOL_PCT = 1e-4  # coupons shown to 5 dp of a percent
DF_DISPLAY_TOL = 5e-7  # DFs shown to 6 dp
PAYMENT_TOL = 0.05  # 5-dp coupon band plus zero-rate input rounding

# Payment dates with a documented curve difference (docs/IRS_OPEN_ITEMS.md).
OPEN_ITEM_DATES = {"2027-11-30": "OI-1", "2028-04-28": "OI-7"}


def _r(value: Optional[float]) -> Optional[float]:
    """Round to 12 significant digits for stable, comparable JSON."""
    if value is None:
        return None
    return float(f"{value:.12g}")


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


# --- normalised inventory (three Bloomberg source layouts) ------------------------------


@dataclass
class Terms:
    case_id: str
    layout: str
    trade_id: str
    currency: str
    valuation_date: str
    effective_date: str
    maturity_date: str
    fixed: Dict[str, Any]
    floating: Dict[str, Any]
    periods: List[Dict[str, Any]]  # accrual_start, accrual_end, pay_date, notional
    principal_exchange: Optional[str]


def _period(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "accrual_start": row["accrual_start"],
        "accrual_end": row["accrual_end"],
        "pay_date": row["pay_date"],
        "notional": row["balance"],
    }


def read_terms(case_id: str) -> Terms:
    source = _read(FIXTURES / "source" / f"{case_id}.json")
    if "leg_1" in source:  # layout A: TC1-TC5
        trade, legs = source["trade"], (source["leg_1"], source["leg_2"])
        fx = next(leg for leg in legs if leg["type"] == "Fixed")
        fl = next(leg for leg in legs if leg["type"] == "Floating")
        fcd, lcd = fx["contract_detail"], fl["contract_detail"]
        return Terms(
            case_id,
            "A",
            trade["swap_id"],
            trade["currency"],
            trade["valuation_date"],
            trade["effective_date"],
            trade["maturity_date"],
            {
                "side": fx["pay_receive"],
                "rate_pct": fx["coupon"],
                "pay_frequency": fx["pay_frequency"],
                "day_count": fx["day_count"],
                "calendar": fcd["calculation_calendar"],
                "business_day_adjustment": fcd["bus_day_adjustment"],
                "pay_delay": fcd.get("pay_delay"),
            },
            {
                "side": fl["pay_receive"],
                "index": fl["index"],
                "index_tenor": fl["index_tenor"],
                "spread_bp": fl["spread"],
                "reset_frequency": fl["reset_frequency"],
                "pay_frequency": fl["pay_frequency"],
                "day_count": fl["day_count"],
                "reset_type": fl.get("reset_type"),
                "compounding": fl.get("compounding"),
                "lookback_days": fl.get("days_before_accrual"),
                "cutoff_days": fl.get("rate_cut_off_days"),
                "calendar": lcd["calculation_calendar"],
                "fixing_calendar": lcd.get("fixing_calendar"),
                "latest_index": fl.get("latest_index"),
                "pay_delay": lcd.get("pay_delay"),
            },
            [_period(r) for r in fx["amortization"]],
            source.get("additional_detail", {}).get("principal_exchange"),
        )
    if "legs" in source.get("trade", {}):  # layout B: TC6-TC9
        trade = source["trade"]
        fx, fl = trade["legs"]["fixed"], trade["legs"]["floating"]
        return Terms(
            case_id,
            "B",
            trade["swap_id"],
            trade["currency"],
            trade["valuation_date"],
            trade["effective_date"],
            trade["maturity_date"],
            {
                "side": fx["pay_receive"],
                "rate_pct": fx["coupon"],
                "pay_frequency": fx["pay_frequency"],
                "day_count": fx["day_count"],
                "calendar": fx["calculation_calendar"],
                "business_day_adjustment": fx["business_day_adjustment"],
                "pay_delay": None,
            },
            {
                "side": fl["pay_receive"],
                "index": fl["index"],
                "index_tenor": fl["index_tenor"],
                "spread_bp": fl["spread_bp"],
                "reset_frequency": fl["reset_frequency"],
                "pay_frequency": fl["pay_frequency"],
                "day_count": fl["day_count"],
                "reset_type": fl.get("reset_type"),
                "compounding": fl.get("compounding"),
                "lookback_days": fl.get("days_before_accrual"),
                "cutoff_days": fl.get("rate_cutoff_days"),
                "calendar": fl["calculation_calendar"],
                "fixing_calendar": fl.get("fixing_calendar"),
                "latest_index": fl.get("latest_index"),
                "pay_delay": fl.get("payment_delay"),
            },
            [_period(r) for r in fx["amortization_schedule"]],
            fx.get("principal_exchange"),
        )
    if "fixed_leg" in source:  # layout C: TC10
        trade, fx, fl = source["trade"], source["fixed_leg"], source["floating_leg"]
        fadj, ladj = fx["date_adjustment"], fl["date_adjustments"]
        return Terms(
            case_id,
            "C",
            trade["trade_id"],
            trade["currency"],
            trade["valuation_date"],
            trade["effective_date"],
            trade["maturity_date"],
            {
                "side": fx["role"],
                "rate_pct": fx["coupon_rate_pct"],
                "pay_frequency": fx["pay_frequency"],
                "day_count": fx["day_count"],
                "calendar": fadj["calendar"],
                "business_day_adjustment": fadj["business_day_adjustment"],
                "pay_delay": None,
            },
            {
                "side": fl["role"],
                "index": fl["index"],
                "index_tenor": fl["index_tenor"],
                "spread_bp": fl["spread_bps"],
                "reset_frequency": fl["reset_frequency"],
                "pay_frequency": fl["pay_frequency"],
                "day_count": fl["day_count"],
                "reset_type": fl.get("reset_type"),
                "compounding": fl.get("compounding"),
                "lookback_days": fl.get("lookback_days"),
                "cutoff_days": fl.get("rate_cutoff_days"),
                "calendar": ladj["calendar"],
                "fixing_calendar": None,
                "latest_index": fl.get("latest_index"),
                "pay_delay": None,
            },
            [_period(r) for r in source["amortization_schedule"]],
            source["additional_details"].get("principal_exchange"),
        )
    raise ValueError(f"{case_id}: unrecognised Bloomberg source layout")


# --- Bloomberg reference values -----------------------------------------------------


def _rows(rows: List[Dict[str, Any]], leg: str) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        coupon = r.get(
            "equivalent_coupon",
            r.get("equivalent_coupon_pct", r.get("coupon_rate_pct", r.get("equiv_coupon"))),
        )
        out.append(
            {
                "leg": leg,
                "pay_date": r["pay_date"],
                "accrual_start": r["accrual_start"],
                "accrual_end": r["accrual_end"],
                "notional": r["notional"],
                "rate_pct": coupon,
                "payment": r["payment"],
                "discount_factor": r.get("discount_factor", r.get("discount")),
                "pv": r["pv"],
                # Floating reset information as displayed; None where the layout has none.
                "effective_reset_date": r.get("effective_reset_date"),
                "reset_date": r.get("reset_date"),
                "reset_rate_pct": r.get("reset_rate"),
            }
        )
    return out


def read_bloomberg(case_id: str) -> Dict[str, Any]:
    """Cashflow-leg NPVs are used as leg references; the 'market' / 'leg_valuation'
    leg values are recorded separately (OI-9)."""
    oracle = _read(FIXTURES / "references" / f"{case_id}.json")["source_oracle_sections"]
    if "cashflow_leg_1" in oracle:
        legs = {}
        for key in ("cashflow_leg_1", "cashflow_leg_2"):
            leg = "fixed" if "Fixed" in oracle[key]["leg"] else "floating"
            legs[leg] = oracle[key]
        return {
            "npv": oracle["valuation_results"]["npv"],
            "accrued": oracle["valuation_results"].get("accrued"),
            "fixed_leg_npv": legs["fixed"]["npv"],
            "floating_leg_npv": legs["floating"]["npv"],
            "leg_npv_source": "cashflow_leg_* npv",
            "other_leg_values": {
                k: oracle[k]["npv"] for k in ("leg_1_market", "leg_2_market") if k in oracle
            },
            "cashflows": _rows(legs["fixed"]["cashflows"], "fixed")
            + _rows(legs["floating"]["cashflows"], "floating"),
        }
    if "cashflows" in oracle:
        cf = oracle["cashflows"]
        return {
            "npv": oracle["valuation_results"]["npv"],
            "accrued": oracle["valuation_results"].get("accrued"),
            "fixed_leg_npv": cf["fixed_leg"]["npv"],
            "floating_leg_npv": cf["floating_leg"]["npv"],
            "leg_npv_source": "cashflows.*_leg npv",
            "other_leg_values": {
                f"leg_valuation_metrics.{k}": v["npv"]
                for k, v in oracle.get("leg_valuation_metrics", {}).items()
            },
            "net_npv": cf.get("net_npv"),
            "cashflows": _rows(cf["fixed_leg"]["cashflows"], "fixed")
            + _rows(cf["floating_leg"]["cashflows"], "floating"),
        }
    fixed = _rows(oracle["fixed_leg_cashflows"], "fixed")
    floating = _rows(oracle["floating_leg_cashflows"], "floating")
    return {
        "npv": oracle["valuation"]["trade_npv"],
        "accrued": oracle["valuation"].get("accrued"),
        "fixed_leg_npv": _r(sum(r["pv"] for r in fixed)),
        "floating_leg_npv": _r(sum(r["pv"] for r in floating)),
        "leg_npv_source": "sum of cashflow PVs (no cashflow-leg NPV field)",
        "other_leg_values": {
            f"leg_valuation.{k}": v["npv"] for k, v in oracle["leg_valuation"].items()
        },
        "cashflows": fixed + floating,
    }


# --- capability and data checks ---------------------------------------------------------


def market_data_coverage(currency: str, maturity: str, snapshot) -> Dict[str, Any]:
    path = MARKET_DATA_DIR / currency / "market_data.json"
    info: Dict[str, Any] = {
        "snapshot_assignment": None,
        "market_data_file": _rel(path) if path.exists() else None,
    }
    if currency in snapshot.assignments:
        a = snapshot.assignments[currency]
        info["snapshot_assignment"] = {
            "discount": a.discount_curve_id,
            "forecast": a.forecast_curve_id,
        }
    if path.exists():
        doc = _read(path)
        obs = doc["observations"]
        info.update(
            benchmark=doc.get("benchmark"),
            observation_fields=sorted(obs[0]),
            observations=len(obs),
            last_observation=obs[-1]["date"],
            covers_maturity=obs[-1]["date"] >= maturity,
            has_zero_rates=any("zero" in key for key in obs[0]),
        )
    return info


def blockers_for(terms: Terms, coverage: Dict[str, Any]) -> List[Dict[str, str]]:
    blockers: List[Dict[str, str]] = []
    fl = terms.floating

    def add(code: str, detail: str) -> None:
        blockers.append({"code": code, "detail": detail})

    if coverage["snapshot_assignment"] is None:
        add(
            "NO_CURVE_ASSIGNMENT",
            f"market snapshots {[_rel(p) for p in MARKET_SNAPSHOT_FILES]} assign no curve "
            f"for {terms.currency}",
        )
        if coverage["market_data_file"] is None:
            add("NO_MARKET_DATA", f"no market_data file for {terms.currency}")
        elif not coverage["has_zero_rates"] or coverage.get("benchmark") is None:
            add(
                "MARKET_DATA_NOT_CURVE_READY",
                f"{coverage['market_data_file']} has fields {coverage['observation_fields']} "
                f"(no zero rates, tenors or conventions; benchmark {coverage.get('benchmark')!r})",
            )
    if fl["index"] not in BENCHMARK_CURVES:
        add(
            "UNSUPPORTED_BENCHMARK",
            f"floating index {fl['index']} {fl['index_tenor']} is not in BENCHMARK_CURVES "
            f"{sorted(BENCHMARK_CURVES)}",
        )
    term_rate_supported = (
        fl["index"] in TERM_BENCHMARKS
        and str(fl.get("compounding") or "none").lower() in ("flat", "none")
    )
    if str(fl["reset_frequency"]).lower() != "daily" and not term_rate_supported:
        add(
            "UNSUPPORTED_FLOATING_LEG",
            f"reset {fl['reset_frequency']} ({fl.get('reset_type') or 'reset type not given'}, "
            f"compounding {fl.get('compounding') or 'not given'}); the fresh instrument "
            "supports daily overnight compounding, and term-rate fallback legs for "
            f"{sorted(TERM_BENCHMARKS)} only",
        )
    for leg_name, calendar in (("fixed", terms.fixed["calendar"]), ("floating", fl["calendar"])):
        try:
            AccrualDateAdjustment(
                calendar=calendar, business_day_convention=BusinessDayConvention.MODIFIED_FOLLOWING
            )
        except InvalidIRSParameters:
            add("UNSUPPORTED_CALENDAR", f"{leg_name} calculation calendar {calendar!r}")
    if terms.case_id in UNRESOLVED_CONTRACT_TERMS:
        add("CONTRACT_TERMS_UNRESOLVED", UNRESOLVED_CONTRACT_TERMS[terms.case_id])
    # Fixings are not checked here: historical and valuation-date fixings are market data,
    # and pricing itself reports any that are missing (MISSING_FIXINGS).
    return blockers


def _missing_fixings(exc: BaseException) -> bool:
    """True when pricing failed only because a required fixing was not supplied."""
    seen = exc
    while seen is not None:
        if isinstance(seen, TermRateFixingRequired):
            return True
        if (isinstance(seen, CashflowExtractionError)
                and "fixings before the valuation" in str(seen)):
            return True
        seen = seen.__cause__ or seen.__context__
    return False


def data_quality(terms: Terms, bloomberg: Dict[str, Any]) -> List[str]:
    notes = []
    denominators = {"ACT/360": 360.0, "ACT/365": 365.0}
    rate = terms.fixed["rate_pct"] / 100.0
    if terms.fixed["day_count"] in denominators:
        ratios = set()
        for r in (r for r in bloomberg["cashflows"] if r["leg"] == "fixed"):
            days = (
                date.fromisoformat(r["accrual_end"]) - date.fromisoformat(r["accrual_start"])
            ).days
            expected = abs(r["notional"]) * rate * days / denominators[terms.fixed["day_count"]]
            ratios.add(round(abs(r["payment"]) / expected, 4) if expected else None)
        if ratios != {1.0}:
            notes.append(
                f"Bloomberg fixed payments / (notional x rate x days) = {sorted(ratios)}; "
                "the source notional column is not on the payment scale"
            )
    legs_sum = bloomberg["fixed_leg_npv"] + bloomberg["floating_leg_npv"]
    if abs(legs_sum - bloomberg["npv"]) > 0.05:
        notes.append(
            f"Bloomberg total NPV {bloomberg['npv']} differs from fixed + floating "
            f"cashflow-leg NPVs {_r(legs_sum)} by {_r(bloomberg['npv'] - legs_sum)}"
        )
    if bloomberg.get("net_npv") is not None and abs(bloomberg["net_npv"] - bloomberg["npv"]) > 0.05:
        notes.append(
            f"Bloomberg cashflows.net_npv {bloomberg['net_npv']} differs from "
            f"valuation npv {bloomberg['npv']}"
        )
    latest = terms.floating.get("latest_index")
    starts_today = [p for p in terms.periods if p["accrual_start"] == terms.valuation_date]
    if latest is not None and starts_today:
        notes.append(
            f"a floating period starts on the valuation date ({terms.valuation_date}) and "
            f"the source supplies latest_index {latest}; its meaning is unconfirmed"
        )
    return notes


# --- pricing ------------------------------------------------------------------------


def trade_input_path(case_id: str) -> Path:
    """Canonical trade input for a case: examples/irs/<case>_trade.json."""
    return EXAMPLES / f"{case_id.lower()}_trade.json"


def _compare_rows(rows: List[Dict[str, Any]], bloomberg_rows: List[Dict[str, Any]]):
    by_key = {(r["leg"], r["pay_date"]): r for r in bloomberg_rows}
    out = []
    for row in rows:
        b = by_key.get((row["leg"], row["payment_date"]))
        spread = row.get("spread")
        entry = {
            "leg": row["leg"],
            "period": row["period"],
            "payment_date": row["payment_date"],
            "accrual_start": row["accrual_start"],
            "accrual_end": row["accrual_end"],
            "accrual_days": (
                date.fromisoformat(row["accrual_end"]) - date.fromisoformat(row["accrual_start"])
            ).days,
            "day_count_fraction": _r(row.get("day_count_fraction")),
            "notional": _r(row["notional"]),
            # Floating rows: the coupon is the projected index rate plus the spread.
            "spread_pct": None if spread is None else _r(spread * 100),
            "index_rate_pct": None if spread is None else _r((row["rate"] - spread) * 100),
            "rate_pct": _r(row["rate"] * 100),
            "amount": _r(row["amount"]),
            "discount_factor": _r(row["discount_factor"]),
            "present_value": _r(row["present_value"]),
            "open_item": OPEN_ITEM_DATES.get(row["payment_date"]),
        }
        if b is None:
            entry["bloomberg"] = None
        else:
            d_rate = None if b["rate_pct"] is None else row["rate"] * 100 - b["rate_pct"]
            d_df = row["discount_factor"] - b["discount_factor"]
            d_amt = row["amount"] - b["payment"]
            entry["bloomberg"] = {
                "rate_pct": b["rate_pct"],
                "payment": b["payment"],
                "discount_factor": b["discount_factor"],
                "pv": b["pv"],
                "accrual_start": b["accrual_start"],
                "accrual_end": b["accrual_end"],
                "notional": b["notional"],
                "effective_reset_date": b.get("effective_reset_date"),
                "reset_date": b.get("reset_date"),
                "reset_rate_pct": b.get("reset_rate_pct"),
            }
            entry["difference"] = {
                "rate_bp": _r(None if d_rate is None else d_rate * 100),
                "amount": _r(d_amt),
                "discount_factor": _r(d_df),
                "present_value": _r(row["present_value"] - b["pv"]),
            }
            entry["within_display_tolerance"] = (
                (d_rate is None or abs(d_rate) <= COUPON_DISPLAY_TOL_PCT)
                and abs(d_df) <= DF_DISPLAY_TOL
                and abs(d_amt) <= PAYMENT_TOL
            )
        out.append(entry)
    return out


def _differences(pricing: Dict[str, float], bloomberg: Dict[str, Any]) -> Dict[str, float]:
    return {
        "npv": _r(pricing["npv"] - bloomberg["npv"]),
        "fixed_leg_npv": _r(pricing["fixed_leg_npv"] - bloomberg["fixed_leg_npv"]),
        "floating_leg_npv": _r(pricing["floating_leg_npv"] - bloomberg["floating_leg_npv"]),
    }


def _engine_only(trade_doc, market_doc):
    """Same production calls as price_irs, stopping before cashflow extraction."""
    instrument = build_trade(trade_doc)
    environment = resolve_market_environment(parse_market_snapshot(market_doc)).environment
    previous = ql.Settings.instance().evaluationDate
    try:
        result = PricingService().price(
            instrument=instrument,
            market_env=environment,
            model_type="analytical",
            engine_type="discounting",
        )
        legs = instrument.leg_npvs()
    finally:
        ql.Settings.instance().evaluationDate = previous
    return instrument, environment, result, legs


def latest_index_evidence(terms: Terms, instrument, environment, bloomberg) -> Optional[Dict]:
    """Hypothesis test: Bloomberg applies the supplied latest_index to the fixing on
    the valuation date. The value is set on the priced swap's index only for this
    calculation and removed afterwards; production pricing never uses it."""
    latest = terms.floating.get("latest_index")
    if latest is None:
        return None
    built = instrument.last_built
    floating = next(
        leg for leg in (built.pay_leg, built.receive_leg) if isinstance(leg, QuantLibFloatingLeg)
    )
    valuation = ql.Date(VALUATION_DATE.day, VALUATION_DATE.month, VALUATION_DATE.year)
    target = None
    for number, coupon in enumerate(floating.coupons, start=1):
        if coupon.date() > valuation and coupon.fixingDates()[0] == valuation:
            target = (number, coupon)
            break
    if target is None:
        return {"latest_index_pct": latest, "status": "no coupon fixes on the valuation date"}
    number, coupon = target
    index = floating.index
    if len(index.timeSeries()) != 0:
        return {"latest_index_pct": latest, "status": "index already has fixings; not tested"}
    previous = ql.Settings.instance().evaluationDate
    ql.Settings.instance().evaluationDate = valuation
    try:
        forecast_fixing = index.fixing(valuation)
        forecast_rate, forecast_amount = coupon.rate(), coupon.amount()
        try:
            index.addFixing(valuation, latest / 100.0)
            with_rate, with_amount = coupon.rate(), coupon.amount()
        finally:
            index.clearFixings()
    finally:
        ql.Settings.instance().evaluationDate = previous
    pay = date(coupon.date().year(), coupon.date().month(), coupon.date().dayOfMonth()).isoformat()
    b = next(r for r in bloomberg["cashflows"] if r["leg"] == "floating" and r["pay_date"] == pay)
    return {
        "status": "tested",
        "label": "hypothesis (unconfirmed convention)",
        "statement": "Bloomberg applies latest_index to the overnight fixing on the valuation date",
        "latest_index_pct": latest,
        "period": number,
        "payment_date": pay,
        "forecast_fixing_pct": _r(forecast_fixing * 100),
        "bloomberg_rate_pct": b["rate_pct"],
        "bloomberg_payment": b["payment"],
        "rate_pct_forecast": _r(forecast_rate * 100),
        "rate_pct_with_latest_index": _r(with_rate * 100),
        "residual_bp_forecast": _r((forecast_rate * 100 - b["rate_pct"]) * 100),
        "residual_bp_with_latest_index": _r((with_rate * 100 - b["rate_pct"]) * 100),
        "residual_payment_forecast": _r(forecast_amount - b["payment"]),
        "residual_payment_with_latest_index": _r(with_amount - b["payment"]),
        "fixings_removed": len(index.timeSeries()) == 0,
    }


# --- derived inputs (values Optima calculates, read from the production objects) ------------


DERIVED_INPUTS_SCHEMA_VERSION = 1


def _iso(value: ql.Date) -> str:
    return date(value.year(), value.month(), value.dayOfMonth()).isoformat()


def curve_position(zero_curve, when: date) -> Dict[str, Any]:
    """Where a date sits on a built zero curve: the bracketing pillars, the linear-zero
    weight and the interpolated zero rate (ACT/365F, continuous), with the discount factor
    rebuilt from them. A description of the production curve, not a second curve: the
    production discount factor is read from the curve itself and must agree."""
    reference = zero_curve.market_data.reference_date
    t = (when - reference).days / 365.0
    pillars = [(o.tenor, p, float(o.zero_rate), (p - reference).days / 365.0)
               for o, p in zip(zero_curve.market_data.observations, zero_curve.pillar_dates)]
    production = zero_curve.term_structure.discount(ql.Date(when.day, when.month, when.year))
    if t <= pillars[0][3]:
        lo = hi = pillars[0]
        weight, zero = 0.0, pillars[0][2]
    elif t >= pillars[-1][3]:
        lo = hi = pillars[-1]
        weight, zero = 1.0, pillars[-1][2]
    else:
        index = next(i for i in range(len(pillars) - 1) if pillars[i][3] <= t <= pillars[i + 1][3])
        lo, hi = pillars[index], pillars[index + 1]
        weight = (t - lo[3]) / (hi[3] - lo[3])
        zero = lo[2] + weight * (hi[2] - lo[2])
    rebuilt = math.exp(-zero * t)
    return {
        "date": when.isoformat(),
        "lower_pillar": f"{lo[0]} {lo[1].isoformat()}",
        "upper_pillar": f"{hi[0]} {hi[1].isoformat()}",
        "weight": _r(weight),
        "zero_rate_pct": _r(zero * 100),
        "discount_factor": _r(production),
        "rebuilt_matches_curve": abs(rebuilt - production) <= 1e-12,
    }


def _derived(leg: str, period: int, payment_date: str, item: str, value: Any, unit: str,
             inputs: str, method: str, basis: str, sub_period: Optional[int] = None,
             detail: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "leg": leg, "period": period, "sub_period": sub_period, "payment_date": payment_date,
        "item": item, "value": value, "unit": unit, "inputs": inputs, "method": method,
        "basis": basis, "detail": detail or {},
    }


def _coupon_detail(coupon) -> Dict[str, Any]:
    return {"accrual_start": _iso(coupon.accrualStartDate()),
            "accrual_end": _iso(coupon.accrualEndDate()),
            "notional": float(coupon.nominal()), "accrual_fraction": coupon.accrualPeriod()}


def _fixed_rows(leg, curve, valuation: ql.Date) -> List[Dict[str, Any]]:
    out = []
    for number, coupon in enumerate(leg.coupons, start=1):
        pay = _iso(coupon.date())
        if coupon.date() <= valuation:
            out.append(_derived("fixed", number, pay, "excluded_cashflow", None, "-",
                                "payment date on or before the valuation date",
                                "ql.DiscountingSwapEngine excludes it (OI-10)", "OI-10"))
            continue
        out.append(_derived(
            "fixed", number, pay, "coupon_amount", _r(coupon.amount()), "currency",
            f"notional {coupon.nominal():g} x fixed rate {coupon.rate() * 100:g}% x "
            f"{coupon.dayCounter().name()} {coupon.accrualPeriod():.10f}",
            "ql.FixedRateCoupon (instruments/rates/irs/fixed_leg.py)", "trade terms",
            detail=_coupon_detail(coupon),
        ))
        position = curve_position(curve, date.fromisoformat(pay))
        out.append(_derived(
            "fixed", number, pay, "discount_factor", position["discount_factor"], "-",
            f"curve {curve.market_data.currency} {curve.market_data.benchmark}: "
            f"{position['lower_pillar']} / {position['upper_pillar']}, weight "
            f"{position['weight']:.6f}, zero {position['zero_rate_pct']:.6f}%",
            "linear zero, ACT/365F continuous (market/curves/irs_zero_curve.py:243)",
            "market data at pillars; interpolation between pillars is Optima's convention",
            detail=position,
        ))
    return out


# Trade floating benchmark -> market-snapshot fixing name of its overnight index.
_OVERNIGHT_FIXING_NAMES = {"SOFRRATE": "SOFR", "MUTKCALM": "TONA"}


def _overnight_rows(leg, curve, valuation: ql.Date,
                    fixing_provenance: Dict[str, str]) -> List[Dict[str, Any]]:
    out = []
    settings = leg.observation_settings
    contractual = settings.contractual
    for number, coupon in enumerate(leg.coupons, start=1):
        pay = _iso(coupon.date())
        if coupon.date() <= valuation:
            out.append(_derived("floating", number, pay, "excluded_cashflow", None, "-",
                                "payment date on or before the valuation date; its fixings "
                                "are historical", "ql.DiscountingSwapEngine excludes it; no "
                                "historical fixings are supported (OI-10)", "OI-10"))
            continue
        fixings = list(coupon.fixingDates())
        historical = sum(1 for d in fixings if d < valuation)
        window = f"{fixings[0].ISO()} -> {fixings[-1].ISO()}"
        out.append(_derived(
            "floating", number, pay, "observation_window", window, "dates",
            f"accrual {_iso(coupon.accrualStartDate())} -> {_iso(coupon.accrualEndDate())}; "
            f"lookback {settings.lookback_days} bd, no observation shift, lockout "
            f"{settings.quantlib_lockout_days}; rate cutoff {contractual.cutoff_days} not applied",
            "ql.OvernightLeg (instruments/rates/irs/floating_leg.py:203-221), SOFR calendar",
            "lookback from the Bloomberg source (OI-3 for the TC1 fixture); rate cutoff not "
            "mapped to lockout (OI-2)",
            detail={"first_fixing": fixings[0].ISO(), "last_fixing": fixings[-1].ISO(),
                    "fixings": len(fixings), "historical_fixings": historical,
                    "valuation_date_fixing": any(d == valuation for d in fixings)},
        ))
        index_rate = (coupon.rate() - coupon.spread()) / coupon.gearing()
        index_name = leg.terms.benchmark
        stored = set(leg.index.timeSeries().dates())
        known = [d for d in fixings if d in stored]
        note = ""
        if known:
            note = (f"; {len(known)} fixing(s) on or before the valuation date from market data "
                    f"({', '.join(d.ISO() for d in known)}): "
                    + fixing_provenance.get(_OVERNIGHT_FIXING_NAMES.get(index_name, ""), ""))
        elif any(d == valuation for d in fixings):
            note = "; the valuation-date fixing is projected (no fixing supplied)"
        out.append(_derived(
            "floating", number, pay, "compounded_index_rate", _r(index_rate * 100), "pct",
            f"{len(fixings)} daily {index_name} fixings, projected from the forecast curve"
            + note,
            "ql.CompoundingOvernightIndexedCouponPricer (compound, spread excluded)",
            "market data + overnight index; observation conventions as above",
            detail={"fixings_from_market_data": [d.ISO() for d in known]},
        ))
        out.append(_derived(
            "floating", number, pay, "coupon_amount", _r(coupon.amount()), "currency",
            f"notional {coupon.nominal():g} x (index {index_rate * 100:.6f}% + spread "
            f"{coupon.spread() * 100:g}%) x ACT/360 {coupon.accrualPeriod():.10f}",
            "ql.OvernightIndexedCoupon.amount()", "derived from the projected index rate",
            detail=_coupon_detail(coupon),
        ))
        position = curve_position(curve, date.fromisoformat(pay))
        out.append(_derived(
            "floating", number, pay, "discount_factor", position["discount_factor"], "-",
            f"curve {curve.market_data.currency} {curve.market_data.benchmark}: "
            f"{position['lower_pillar']} / {position['upper_pillar']}, weight "
            f"{position['weight']:.6f}, zero {position['zero_rate_pct']:.6f}%",
            "linear zero, ACT/365F continuous (market/curves/irs_zero_curve.py:243)",
            "market data at pillars; interpolation between pillars is Optima's convention",
            detail=position,
        ))
    return out


def _term_rate_rows(leg, curve, valuation: ql.Date,
                    fixing_provenance: Dict[str, str]) -> List[Dict[str, Any]]:
    out = []
    benchmark = leg.spec.benchmark
    fallback = not hasattr(benchmark, "spot_lag")
    status = ("provisional fallback convention (OI-12)" if fallback
              else "provisional projected-term convention (OI-15)")
    rate_item = "compounded_rfr" if fallback else "projected_term_rate"
    rate_method = ("fallback_rate: ql.OvernightIndexedCoupon, compound, observation shift "
                   "(term_rate_leg.py)" if fallback
                   else "projected_term_rate: simple forward on the forecast curve "
                   "(term_rate_leg.py)")
    method = getattr(leg.spec, "observation_method", "reset_date_fallback")
    contractual = method == "contractual_accrual"
    if contractual:
        status = ("Method A (contractual_accrual): PROVISIONAL operational choice, not "
                  "Bloomberg- or SME-confirmed (OI-17)")
        rate_method = ("contractual_accrual_rate: ql.OvernightIndexedCoupon, compound, "
                       "no observation shift (term_rate_leg.py)")
    elif fallback:
        status += "; Method B (reset_date_fallback)"
    for number, (coupon, period) in enumerate(zip(leg.coupons, leg.period_details), start=1):
        pay = _iso(coupon.date())
        for k, reset in enumerate(period.resets, start=1):
            if reset.source == "fixing":
                out.append(_derived(
                    "floating", number, pay, "reset_rate", _r(reset.reset_rate * 100), "pct",
                    f"historical {benchmark.name} fixing of {reset.reset_date.isoformat()}",
                    "market-data fixing (term_rate_leg._reset_rate)",
                    "market data: " + fixing_provenance.get(benchmark.name, "fixing"),
                    sub_period=k, detail={"reset_date": reset.reset_date.isoformat(),
                                          "source": "fixing"},
                ))
            else:
                window = (f"{reset.observation_start.isoformat()} -> "
                          f"{reset.observation_end.isoformat()}")
                if contractual:
                    basis = (f"contractual period {reset.start.isoformat()} -> "
                             f"{reset.end.isoformat()}, no shift (reset "
                             f"{reset.reset_date.isoformat()} not used)")
                    source_fn = rate_method.split(":")[0]
                else:
                    basis = (f"reset {reset.reset_date.isoformat()}; rate period from "
                             f"{reset.rate_start.isoformat()} ({benchmark.tenor}"
                             + (f", shift {benchmark.shift_days} bd)" if fallback else ")"))
                    source_fn = ("term_rate_leg.rate_period_start + "
                                 + rate_method.split(":")[0])
                out.append(_derived(
                    "floating", number, pay, "observation_window", window, "dates",
                    basis, source_fn, status, sub_period=k,
                    detail={"observation_method": method,
                            "observation_rule": getattr(reset, "observation_rule", ""),
                            "reset_date": reset.reset_date.isoformat(),
                            "contractual_start": reset.start.isoformat(),
                            "contractual_end": reset.end.isoformat(),
                            "rate_start": reset.rate_start.isoformat(),
                            "ibor_period_end": (reset.ibor_period_end.isoformat()
                                                if reset.ibor_period_end else None),
                            "observation_start": reset.observation_start.isoformat(),
                            "observation_end": reset.observation_end.isoformat()},
                ))
                out.append(_derived(
                    "floating", number, pay, rate_item, _r(reset.rfr_compounded_rate * 100),
                    "pct", f"{benchmark.rfr} curve over {window}", rate_method, status,
                    sub_period=k,
                ))
                out.append(_derived(
                    "floating", number, pay, "reset_rate", _r(reset.reset_rate * 100), "pct",
                    f"{rate_item} {reset.rfr_compounded_rate * 100:.8f}% + spread adjustment "
                    f"{reset.spread_adjustment * 100:g}%",
                    "term_rate_leg._reset_rate", status, sub_period=k,
                    detail={"reset_date": reset.reset_date.isoformat(), "source": "projected"},
                ))
            out.append(_derived(
                "floating", number, pay, "sub_period_amount", _r(reset.amount), "currency",
                f"accrual fraction {reset.accrual_fraction:.10f}; "
                + ("flat compounding, margin not compounded" if len(period.resets) > 1
                   else "single reset"),
                "flat_compounded_amount (term_rate_leg.py)",
                "flat compounding confirmed by Bloomberg payments; reset rate as above",
                sub_period=k,
                detail={"accrual_fraction": reset.accrual_fraction,
                        "notional": float(coupon.nominal()),
                        "margin": float(leg.terms.floating_spread_rate),
                        "reset_rate": reset.reset_rate},
            ))
        out.append(_derived(
            "floating", number, pay, "equivalent_coupon", _r(period.equivalent_rate * 100), "pct",
            f"payment / (notional {coupon.nominal():g} x {coupon.accrualPeriod():.10f})",
            "term_rate_leg.build_term_rate_floating_leg (represented as ql.FixedRateCoupon)",
            "representation of the payment", detail=_coupon_detail(coupon),
        ))
        out.append(_derived(
            "floating", number, pay, "coupon_amount", _r(coupon.amount()), "currency",
            "sum of the sub-period amounts",
            "ql.FixedRateCoupon at the equivalent coupon", "derived from the reset rates",
            detail=_coupon_detail(coupon),
        ))
        position = curve_position(curve, date.fromisoformat(pay))
        out.append(_derived(
            "floating", number, pay, "discount_factor", position["discount_factor"], "-",
            f"curve {curve.market_data.currency} {curve.market_data.benchmark}: "
            f"{position['lower_pillar']} / {position['upper_pillar']}, weight "
            f"{position['weight']:.6f}, zero {position['zero_rate_pct']:.6f}%",
            "linear zero, ACT/365F continuous (market/curves/irs_zero_curve.py:243)",
            "market data at pillars; interpolation between pillars is Optima's convention",
            detail=position,
        ))
    return out


def _with_engine_check(derived: Dict[str, Any], legs: Dict[str, float], engine_npv: float,
                       price_irs_npv: Optional[float]) -> Dict[str, Any]:
    """Tie the derived rows to the engine: future-cashflow PVs must equal the engine's leg
    NPVs, and a rebuild must reproduce price_irs exactly."""
    check = {
        "engine_npv": _r(engine_npv),
        "engine_leg_npv": {k: _r(v) for k, v in legs.items()},
        "future_cashflow_pv_matches_engine": all(
            # derived PVs are stored at 12 significant digits (_r)
            abs(derived["future_cashflow_pv"][k] - legs[k]) <= max(1e-8, 1e-10 * abs(legs[k]))
            for k in ("fixed", "floating")
        ),
    }
    if price_irs_npv is not None:
        check["price_irs_npv"] = _r(price_irs_npv)
        check["rebuild_matches_price_irs"] = engine_npv == price_irs_npv
    return {**derived, "engine_check": check}


def derived_inputs(instrument, market_doc, currency: str) -> Dict[str, Any]:
    """Values Optima calculates rather than reads from the trade input, read from the
    production-built swap (``instrument.last_built``) after pricing, with the evaluation
    date set to the valuation date and restored afterwards. Nothing is re-priced."""
    snapshot = parse_market_snapshot(market_doc)
    assignment = snapshot.assignment(currency)
    curve = resolve_market_environment(snapshot).curves[assignment.discount_curve_id]
    built = instrument.last_built
    valuation = ql.Date(VALUATION_DATE.day, VALUATION_DATE.month, VALUATION_DATE.year)
    previous = ql.Settings.instance().evaluationDate
    ql.Settings.instance().evaluationDate = valuation
    try:
        rows: List[Dict[str, Any]] = []
        for side, leg in (("pay", built.pay_leg), ("receive", built.receive_leg)):
            if isinstance(leg, QuantLibTermRateFloatingLeg):
                leg_rows = _term_rate_rows(leg, curve, valuation, snapshot.fixing_provenance)
            elif isinstance(leg, QuantLibFloatingLeg) and leg.index is not None:
                leg_rows = _overnight_rows(leg, curve, valuation, snapshot.fixing_provenance)
            else:
                leg_rows = _fixed_rows(leg, curve, valuation)
            rows += [{**row, "side": side} for row in leg_rows]
        future_pv = {}
        for side, leg in (("pay", built.pay_leg), ("receive", built.receive_leg)):
            sign = -1.0 if side == "pay" else 1.0
            kind = "floating" if isinstance(leg, QuantLibFloatingLeg) else "fixed"
            future_pv[kind] = _r(sum(
                sign * c.amount() * curve.term_structure.discount(c.date())
                for c in leg.quantlib_leg if c.date() > valuation
            ))
    finally:
        ql.Settings.instance().evaluationDate = previous
    rows.sort(key=lambda r: (r["leg"] != "fixed", r["period"], r["sub_period"] or 0))
    return {
        "schema_version": DERIVED_INPUTS_SCHEMA_VERSION,
        "discount_curve": assignment.discount_curve_id,
        "forecast_curve": assignment.forecast_curve_id,
        "future_cashflow_pv": future_pv,
        "rows": rows,
    }


# --- audit ---------------------------------------------------------------------------


class CaseAuditError(Exception):
    """An unexpected failure while auditing one case (not a missing input)."""

    def __init__(self, case_id: str, stage: str, cause: BaseException):
        super().__init__(f"{case_id} failed during {stage}: {type(cause).__name__}: {cause}")
        self.case_id, self.stage, self.cause = case_id, stage, cause


class SharedStateCorrupted(RuntimeError):
    """A case left QuantLib's evaluation date or index fixings changed."""


@dataclass
class _Stage:
    name: str = "start"


def audit_case(case_id: str, market_doc, snapshot) -> Dict[str, Any]:
    """Audit one case; an unexpected exception becomes CaseAuditError with its stage."""
    stage = _Stage()
    try:
        return _audit_case(case_id, market_doc, snapshot, stage)
    except Exception as exc:
        raise CaseAuditError(case_id, stage.name, exc) from exc


def _error_record(error: CaseAuditError) -> Dict[str, Any]:
    record = {key: None for key in CASE_RECORD_KEYS}
    record.update(
        case_id=error.case_id, status="error", blockers=[], observations=[], limitations=[],
        hypotheses=[],
        error={"stage": error.stage, "type": type(error.cause).__name__,
               "message": str(error.cause)},
    )
    return record


CASE_RECORD_KEYS = (
    "case_id", "trade_id", "source_layout", "currency", "valuation_date", "effective_date",
    "maturity_date", "fixed_leg", "floating_leg", "features", "market_data", "bloomberg",
    "blockers", "observations", "limitations", "hypotheses", "trade_input", "pricing",
    "differences", "cashflows", "derived_inputs", "settled", "status", "error",
)


def _audit_case(case_id: str, market_doc, snapshot, stage: _Stage) -> Dict[str, Any]:
    stage.name = "reading Bloomberg source terms"
    terms = read_terms(case_id)
    stage.name = "reading Bloomberg references"
    bloomberg = read_bloomberg(case_id)
    stage.name = "capability and market-data checks"
    coverage = market_data_coverage(terms.currency, terms.maturity_date, snapshot)
    blockers = blockers_for(terms, coverage)
    notionals = [p["notional"] for p in terms.periods]
    record: Dict[str, Any] = {
        "case_id": case_id,
        "error": None,
        "trade_id": terms.trade_id,
        "source_layout": terms.layout,
        "currency": terms.currency,
        "valuation_date": terms.valuation_date,
        "effective_date": terms.effective_date,
        "maturity_date": terms.maturity_date,
        "fixed_leg": terms.fixed,
        "floating_leg": terms.floating,
        "features": {
            "periods": len(terms.periods),
            "amortising": len(set(notionals)) > 1,
            "source_notionals": notionals,
            "starts_before_valuation": terms.effective_date < terms.valuation_date,
            "payment_on_valuation_date": any(
                p["pay_date"] == terms.valuation_date for p in terms.periods
            ),
            "principal_exchange": terms.principal_exchange,
        },
        "market_data": coverage,
        "bloomberg": {k: v for k, v in bloomberg.items() if k != "cashflows"},
        "blockers": blockers,
        "observations": data_quality(terms, bloomberg),
        "limitations": [],
        "hypotheses": [],
        "trade_input": None,
        "pricing": None,
        "differences": None,
        "cashflows": None,
        "derived_inputs": None,
        "settled": [],
    }
    trade_path = trade_input_path(case_id)
    if not blockers and not trade_path.exists():
        blockers.append({"code": "NO_TRADE_INPUT_FILE",
                         "detail": f"no canonical trade input {_rel(trade_path)}"})
    if blockers:
        record["status"] = "blocked"
        return record

    stage.name = "reading trade input"
    trade_doc = _read(trade_path)
    record["trade_input"] = _rel(trade_path)
    fixings = snapshot.fixings
    try:
        stage.name = "pricing with price_irs"
        valuation = price_irs(trade_doc, market_doc)
    except Exception as exc:  # noqa: BLE001 - classified below, otherwise re-raised
        if not _missing_fixings(exc):
            if not isinstance(exc, CashflowExtractionError):
                raise
        else:
            record["status"] = "blocked"
            record["blockers"].append({"code": "MISSING_FIXINGS", "detail": str(exc)})
            return record
        stage.name = "engine-only pricing after cashflow extraction was refused"
        with overnight_fixings_applied(fixings):
            instrument, environment, result, legs = _engine_only(trade_doc, market_doc)
        record["status"] = "partially_audited"
        record["limitations"].append(
            {
                "code": "CASHFLOW_EXTRACTION_REFUSED",
                "detail": str(exc),
                "effect": "price_irs stops; engine NPV reported below; no cashflow table "
                "(no cashflow is omitted or rebuilt)",
            }
        )
        record["pricing"] = {
            "path": "build_trade + resolve_market_environment + "
            "PricingService.price (production engine)",
            "npv": _r(result.npv),
            "fixed_leg_npv": _r(legs["fixed"]),
            "floating_leg_npv": _r(legs["floating"]),
            "engine": result.engine_used,
            "model": result.model_used,
        }
        record["differences"] = _differences(record["pricing"], bloomberg)
        stage.name = "reading derived inputs from the production-built swap"
        with overnight_fixings_applied(fixings):
            record["derived_inputs"] = _with_engine_check(
                derived_inputs(instrument, market_doc, terms.currency), legs, result.npv, None)
        stage.name = "latest_index hypothesis test"
        evidence = latest_index_evidence(terms, instrument, environment, bloomberg)
        if evidence is not None:
            record["hypotheses"].append(evidence)
        return record

    record["status"] = "priced"
    record["pricing"] = {
        "path": "price_irs",
        "npv": _r(valuation.npv),
        "fixed_leg_npv": _r(valuation.fixed_leg_npv),
        "floating_leg_npv": _r(valuation.floating_leg_npv),
        "engine": valuation.engine,
        "model": valuation.model,
    }
    record["differences"] = _differences(record["pricing"], bloomberg)
    record["settled"] = [
        {"leg": s.leg, "period": s.period, "accrual_start": s.accrual_start.isoformat(),
         "accrual_end": s.accrual_end.isoformat(), "payment_date": s.payment_date.isoformat()}
        for s in valuation.settled
    ]
    stage.name = "reading derived inputs from a production rebuild of the swap"
    with overnight_fixings_applied(fixings):
        instrument, _, rebuilt, legs = _engine_only(trade_doc, market_doc)
        record["derived_inputs"] = _with_engine_check(
            derived_inputs(instrument, market_doc, terms.currency), legs, rebuilt.npv,
            valuation.npv)
    stage.name = "comparing cashflows with Bloomberg"
    # Production extractor rows (ISO dates) from the valuation result.
    record["cashflows"] = _compare_rows(valuation.to_dict()["cashflows"], bloomberg["cashflows"])
    return record


def discount_factor_evidence(cases: List[Dict[str, Any]], market_doc) -> List[Dict[str, Any]]:
    """Bloomberg DF at every payment date of the USD cases that were priced or partially
    audited, against the configured discount curve."""
    resolved = resolve_market_environment(parse_market_snapshot(market_doc))
    curve = resolved.environment.discount_curves["USD"]
    dates: Dict[str, Dict[str, Any]] = {}
    for case in cases:
        if case["currency"] != "USD" or case["status"] not in ("priced", "partially_audited"):
            continue
        for row in read_bloomberg(case["case_id"])["cashflows"]:
            entry = dates.setdefault(row["pay_date"], {"bloomberg": set(), "cases": set()})
            entry["bloomberg"].add(row["discount_factor"])
            entry["cases"].add(case["case_id"])
    out = []
    for pay in sorted(dates):
        d = date.fromisoformat(pay)
        optima = curve.discount(ql.Date(d.day, d.month, d.year))
        values = sorted(dates[pay]["bloomberg"])
        bbg = values[0]
        t = (d - VALUATION_DATE).days / 365.0
        out.append(
            {
                "payment_date": pay,
                "cases": sorted(dates[pay]["cases"]),
                "bloomberg_discount_factor": bbg,
                "bloomberg_values_agree": len(values) == 1,
                "optima_discount_factor": _r(optima),
                "difference": _r(optima - bbg),
                "zero_rate_difference_bp": _r(-math.log(optima / bbg) / t * 1e4),
                "within_display_tolerance": abs(optima - bbg) <= DF_DISPLAY_TOL,
                "open_item": OPEN_ITEM_DATES.get(pay),
            }
        )
    return out


def market_data_date_cross_check(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Where a Bloomberg payment date equals a market_data display date, compare the DFs.
    A difference shows the display-date DFs are not the trade's DFs at that date."""
    out = []
    for case in cases:
        if case["status"] == "error":
            continue
        path = MARKET_DATA_DIR / case["currency"] / "market_data.json"
        if not path.exists():
            continue
        by_date = {o["date"]: o["discount_factor"] for o in _read(path)["observations"]}
        for row in read_bloomberg(case["case_id"])["cashflows"]:
            if row["pay_date"] in by_date and row["leg"] == "fixed":
                out.append(
                    {
                        "currency": case["currency"],
                        "case_id": case["case_id"],
                        "date": row["pay_date"],
                        "bloomberg_trade_df": row["discount_factor"],
                        "market_data_df": by_date[row["pay_date"]],
                        "agree_within_display_tolerance": abs(
                            row["discount_factor"] - by_date[row["pay_date"]]
                        )
                        <= DF_DISPLAY_TOL,
                    }
                )
    return out


# Current open questions (14-Oct-2026). The evidence requests that answer them, with the
# outcomes each would imply, are in scripts/irs_evidence_register.py (R1-R9).
OPEN_QUESTIONS = [
    "TC7 (SF0006M, provisional fallback, OI-12/OI-13): remaining reset gaps -0.054/-0.052/"
    "-0.014 bp; curve interpolation vs compounding/rounding (R1: curve-234 DFs at 7+ "
    "decimals). latest_index is not used for these resets (SME, 14-Oct-2026).",
    "INR IRSWOF (OI-15): how SWPM sets the rate for reset periods shorter than 6M, whether "
    "TC9's first reset is projected or stored, and the index definition (R6).",
    "Bloomberg curve 490 members and settings between the 18M and 3Y pillars (OI-1, OI-7; R2).",
    "TC2 SARON observation convention (OI-17, R9): Method A (contractual accrual, no shift) "
    "is the provisional default; Method B (reset-date fallback) is preserved. Method B "
    "needs SARON fixings 29-Jan-2026 to 30-Mar-2026 (R3) and has the P1 observation-end "
    "question (rule 30-Jul-2026, Bloomberg 29-Jul-2026; R8).",
    "Confirm the market-data fixings: SOFR and TONA for 31-Mar-2026 (R4, R5) and the TC8 "
    "IRSWOF fixing of 27-Feb-2026 (R7).",
    "Meaning of Bloomberg 'market' / 'leg_valuation' leg values that differ from cashflow-leg "
    "NPVs (OI-9 pattern; seen in all ten cases).",
]


# Overnight indexes the production path can create (SOFR legs; SARON for the CHF
# term-rate fallback). Their fixing counts are part of the monitored shared state.
MONITORED_INDEXES = (ql.Sofr, ql.Saron, ql.Tonar)


def shared_state() -> Tuple[int, Tuple[str, ...], Tuple[int, ...]]:
    """QuantLib global state the audit must leave unchanged: the evaluation date, the
    names of indexes with a stored history, and the number of stored fixings of each
    monitored index.

    Reading a time series registers an (empty) history under the index name, so the
    monitored counts are read first; otherwise this check would change its own result."""
    evaluation_date = ql.Settings.instance().evaluationDate.serialNumber()
    fixings = tuple(len(index().timeSeries()) for index in MONITORED_INDEXES)
    return (
        evaluation_date,
        tuple(sorted(ql.IndexManager.instance().histories())),
        fixings,
    )


def load_market_document() -> Dict[str, Any]:
    """Merge the per-currency snapshot files into one market document. Every file must
    have the same valuation date, and a curve id or currency may appear only once."""
    docs = [_read(path) for path in MARKET_SNAPSHOT_FILES]
    dates = {d["valuation_date"] for d in docs}
    if len(dates) != 1:
        raise ValueError(f"market snapshots have different valuation dates: {sorted(dates)}")
    merged: Dict[str, Any] = {
        "schema_version": docs[0]["schema_version"],
        "valuation_date": docs[0]["valuation_date"],
        "provenance": " | ".join(d["provenance"] for d in docs),
        "curves": {},
        "assignments": {},
        "fixings": {},
    }
    for path, doc in zip(MARKET_SNAPSHOT_FILES, docs):
        for section in ("curves", "assignments", "fixings"):
            if section not in doc:
                continue
            clash = set(merged[section]) & set(doc[section])
            if clash:
                raise ValueError(f"{_rel(path)}: {section} {sorted(clash)} already defined")
            merged[section].update(doc[section])
    return merged


def run_audit() -> Dict[str, Any]:
    market_doc = load_market_document()
    snapshot = parse_market_snapshot(market_doc)
    cases = []
    for case_id in CASE_IDS:
        before = shared_state()
        try:
            record = audit_case(case_id, market_doc, snapshot)
        except CaseAuditError as error:
            record = _error_record(error)
        after = shared_state()
        if after != before:
            # Never continue (or report an ordinary error) on corrupted global state.
            raise SharedStateCorrupted(
                f"{case_id} left QuantLib state changed: before {before}, after {after}"
            )
        cases.append(record)
    summary = {
        status: [c["case_id"] for c in cases if c["status"] == status]
        for status in ("priced", "partially_audited", "blocked", "error")
    }
    return {
        "audit_schema_version": AUDIT_SCHEMA_VERSION,
        "audit": "fresh IRS - Bloomberg ten-case audit",
        "valuation_date": VALUATION_DATE.isoformat(),
        "quantlib_version": ql.__version__,
        "inputs": {
            "fixtures": _rel(FIXTURES),
            "market_snapshots": [_rel(p) for p in MARKET_SNAPSHOT_FILES],
            "market_data_dir": _rel(MARKET_DATA_DIR),
            "tolerances": {
                "coupon_pct": COUPON_DISPLAY_TOL_PCT,
                "discount_factor": DF_DISPLAY_TOL,
                "payment": PAYMENT_TOL,
            },
        },
        "summary": summary,
        "cases": cases,
        "evidence": {
            "usd_discount_factors": discount_factor_evidence(cases, market_doc),
            "market_data_display_date_cross_check": market_data_date_cross_check(cases),
        },
        "open_questions": OPEN_QUESTIONS,
    }


def to_json(result: Dict[str, Any]) -> str:
    return json.dumps(result, indent=2, sort_keys=True) + "\n"


def format_summary(result: Dict[str, Any]) -> str:
    lines = [
        f"Bloomberg IRS case audit (valuation {result['valuation_date']}, "
        f"QuantLib {result['quantlib_version']})",
        "",
    ]
    lines.append(
        f"  {'Case':<5} {'Trade':<9} {'Ccy':<4} {'Index':<14} {'Status':<18}"
        f"{'Optima NPV':>16}{'Bloomberg':>14}{'Diff':>10}"
    )
    for c in result["cases"]:
        leg = c["floating_leg"]
        index = f"{leg['index']} {leg['index_tenor']}" if leg else "-"
        bbg = f"{c['bloomberg']['npv']:>14,.2f}" if c["bloomberg"] else f"{'-':>14}"
        if c["pricing"]:
            values = (
                f"{c['pricing']['npv']:>16,.4f}{bbg}"
                f"{c['differences']['npv']:>+10.4f}"
            )
        else:
            values = f"{'-':>16}{bbg}{'-':>10}"
        lines.append(
            f"  {c['case_id']:<5} {c['trade_id'] or '-':<9} {c['currency'] or '-':<4} "
            f"{index:<14} {c['status']:<18}{values}"
        )
    for c in result["cases"]:
        lines.append("")
        lines.append(f"{c['case_id']} ({c['trade_id']}, {c['currency']}): {c['status']}")
        if c["error"]:
            e = c["error"]
            lines.append(f"  ERROR during {e['stage']}: {e['type']}: {e['message']}")
        for b in c["blockers"]:
            lines.append(f"  blocker {b['code']}: {b['detail']}")
        for lim in c["limitations"]:
            lines.append(f"  limitation {lim['code']}: {lim['detail']}")
        if c["differences"]:
            d = c["differences"]
            lines.append(
                f"  Optima - Bloomberg: fixed {d['fixed_leg_npv']:+.4f}, floating "
                f"{d['floating_leg_npv']:+.4f}, total {d['npv']:+.4f}"
            )
        for row in c["cashflows"] or []:
            diff = row.get("difference") or {}
            flag = "" if row.get("within_display_tolerance") else "  outside display tolerance"
            tag = f"  [{row['open_item']}]" if row["open_item"] else ""
            rate = "" if diff.get("rate_bp") is None else f"rate {diff['rate_bp']:+.3f}bp, "
            lines.append(
                f"    {row['leg']:<8} P{row['period']} {row['payment_date']}: {rate}"
                f"amount {diff.get('amount', 0):+.2f}, DF {diff.get('discount_factor', 0):+.1e}"
                f"{flag}{tag}"
            )
        for h in c["hypotheses"]:
            if h.get("status") == "tested":
                bp_forecast = h["residual_bp_forecast"]
                bp_latest = h["residual_bp_with_latest_index"]
                pay_forecast = h["residual_payment_forecast"]
                pay_latest = h["residual_payment_with_latest_index"]
                lines.append(
                    f"  HYPOTHESIS ({h['statement']}): P{h['period']} rate residual "
                    f"{bp_forecast:+.4f}bp with the curve forecast "
                    f"({h['forecast_fixing_pct']:.5f}%), {bp_latest:+.4f}bp "
                    f"with latest_index {h['latest_index_pct']}%; payment residual "
                    f"{pay_forecast:+.3f} -> {pay_latest:+.3f}"
                )
            else:
                lines.append(f"  latest_index {h['latest_index_pct']}: {h['status']}")
        for note in c["observations"]:
            lines.append(f"  observation: {note}")
    lines.append("")
    lines.append("USD discount factors at Bloomberg payment dates (Optima - Bloomberg):")
    for e in result["evidence"]["usd_discount_factors"]:
        flag = "" if e["within_display_tolerance"] else "  outside display tolerance"
        tag = f"  [{e['open_item']}]" if e["open_item"] else ""
        lines.append(
            f"  {e['payment_date']} {','.join(e['cases']):<8} {e['difference']:+.2e} "
            f"(zero {e['zero_rate_difference_bp']:+.3f}bp){flag}{tag}"
        )
    lines.append("")
    lines.append("Bloomberg trade DFs vs market_data DFs on identical dates:")
    for e in result["evidence"]["market_data_display_date_cross_check"] or [{}]:
        if not e:
            lines.append("  (no identical dates)")
            continue
        verdict = "agree" if e["agree_within_display_tolerance"] else "DIFFER"
        lines.append(
            f"  {e['currency']} {e['date']} {e['case_id']}: trade {e['bloomberg_trade_df']} "
            f"vs market_data {e['market_data_df']} -> {verdict}"
        )
    lines.append("")
    s = result["summary"]
    lines.append(
        f"Priced: {', '.join(s['priced']) or '-'} | partially audited: "
        f"{', '.join(s['partially_audited']) or '-'} | blocked: {', '.join(s['blocked']) or '-'}"
        f" | error: {', '.join(s['error']) or '-'}"
    )
    lines.append("Open questions:")
    lines.extend(f"  - {q}" for q in result["open_questions"])
    return "\n".join(lines)


class OutputPathRefused(ValueError):
    """The requested JSON output path is not allowed."""


def _inside(path: Path, base: Path) -> bool:
    p, b = os.path.normcase(str(path)), os.path.normcase(str(base))
    return p == b or p.startswith(b.rstrip(os.sep) + os.sep)


def validate_output_path(raw: str) -> Path:
    """Resolve the requested output path and refuse anything unsafe.

    Refused: a symlink; an existing file or directory (no overwrite, whatever
    path or link leads to it); a missing parent directory; and any location inside
    the protected source directories, judged on the fully resolved path so that an
    alternative spelling or a symlinked directory cannot get round it."""
    requested = Path(raw).expanduser()
    if requested.is_symlink():
        raise OutputPathRefused(f"output path {raw!r} is a symbolic link")
    resolved = requested.resolve()
    if requested.exists() or resolved.exists():
        raise OutputPathRefused(f"output path {raw!r} already exists; it is never overwritten")
    for base in PROTECTED_OUTPUT_DIRS:
        if _inside(resolved, base.resolve()):
            raise OutputPathRefused(
                f"output path {raw!r} resolves inside the protected directory {_rel(base)}"
            )
    if not resolved.parent.is_dir():
        raise OutputPathRefused(f"output directory {str(resolved.parent)!r} does not exist")
    return resolved


def write_json(path: Path, result: Dict[str, Any]) -> None:
    """Create the file exclusively, so an existing file is never replaced."""
    with open(path, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(to_json(result))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Audit the ten Bloomberg IRS cases.")
    parser.add_argument("--json", help="write the machine-readable result to this new file")
    args = parser.parse_args(argv)
    output = None
    if args.json:
        try:
            output = validate_output_path(args.json)
        except OutputPathRefused as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    try:
        result = run_audit()
    except SharedStateCorrupted as exc:
        print(f"audit stopped: {exc}", file=sys.stderr)
        return 3
    print(format_summary(result))
    if output is not None:
        try:
            write_json(output, result)
        except FileExistsError:
            print(f"error: output path {args.json!r} was created by something else; "
                  "not overwritten", file=sys.stderr)
            return 2
        print(f"\nJSON written to {output}")
    return 1 if result["summary"]["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
