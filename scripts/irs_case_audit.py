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
snapshot, ``BENCHMARK_CURVES``, ``AccrualDateAdjustment`` calendars, the
instrument's daily-only reset) and from data-presence checks. No market data,
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
MARKET_SNAPSHOT_FILE = EXAMPLES / "usd_sofr_2026-03-31.json"
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
            "equivalent_coupon", r.get("equivalent_coupon_pct", r.get("coupon_rate_pct"))
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
            f"market snapshot {_rel(MARKET_SNAPSHOT_FILE)} assigns no curve for {terms.currency}",
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
    if str(fl["reset_frequency"]).lower() != "daily":
        add(
            "UNSUPPORTED_FLOATING_LEG",
            f"reset {fl['reset_frequency']} ({fl.get('reset_type') or 'reset type not given'}, "
            f"compounding {fl.get('compounding') or 'not given'}); the fresh instrument "
            "supports daily overnight compounding only",
        )
    for leg_name, calendar in (("fixed", terms.fixed["calendar"]), ("floating", fl["calendar"])):
        try:
            AccrualDateAdjustment(
                calendar=calendar, business_day_convention=BusinessDayConvention.MODIFIED_FOLLOWING
            )
        except InvalidIRSParameters:
            add("UNSUPPORTED_CALENDAR", f"{leg_name} calculation calendar {calendar!r}")
    for p in terms.periods:
        if p["accrual_start"] < terms.valuation_date < p["pay_date"]:
            add(
                "NEEDS_FIXINGS",
                f"period {p['accrual_start']} -> {p['pay_date']} is in progress at the valuation "
                "date; historical fixings are not supported (OI-10)",
            )
            break
    return blockers


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
        entry = {
            "leg": row["leg"],
            "period": row["period"],
            "payment_date": row["payment_date"],
            "accrual_start": row["accrual_start"],
            "accrual_end": row["accrual_end"],
            "notional": _r(row["notional"]),
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
    "differences", "cashflows", "status", "error",
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
    try:
        stage.name = "pricing with price_irs"
        valuation = price_irs(trade_doc, market_doc)
    except CashflowExtractionError as exc:
        stage.name = "engine-only pricing after cashflow extraction was refused"
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


OPEN_QUESTIONS = [
    "What does Bloomberg's latest_index represent (the valuation-date fixing, or the last "
    "published rate carried forward), and how is it applied? Needed before supporting fixings.",
    "Bloomberg curve 490 members and settings between the 18M and 3Y pillars (OI-1, OI-7).",
    "CHF, JPY and INR curves: zero rates with tenors, curve conventions and benchmarks; the "
    "market_data files hold only market rates and DFs at display dates.",
    "Index definitions for SF0006M (CHF) and IRSWOF (INR) as Bloomberg projects them, and "
    "MUTKCALM (JPY TONA) mapping.",
    "Meaning of Bloomberg 'market' / 'leg_valuation' leg values that differ from cashflow-leg "
    "NPVs (OI-9 pattern).",
]


def shared_state() -> Tuple[int, Tuple[str, ...], int]:
    """QuantLib global state the audit must leave unchanged: the evaluation date, the
    number of stored SOFR fixings, and the names of indexes with a stored history.

    Reading a time series registers an (empty) history under the index name, so the
    SOFR count is read first; otherwise this check would change its own result."""
    evaluation_date = ql.Settings.instance().evaluationDate.serialNumber()
    sofr_fixings = len(ql.Sofr().timeSeries())
    return (
        evaluation_date,
        tuple(sorted(ql.IndexManager.instance().histories())),
        sofr_fixings,
    )


def run_audit() -> Dict[str, Any]:
    market_doc = _read(MARKET_SNAPSHOT_FILE)
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
            "market_snapshot": _rel(MARKET_SNAPSHOT_FILE),
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
