"""Validate source-independent IRS trade inputs and convert them to the engine's trade
document (``services.irs_inputs.contract``).

What this module does: required-field checks, date and number conversion, unit
conversion (percent -> decimal rate, basis points -> decimal spread), mapping of the
analyst labels to the engine's enumerations, the notional schedule, and a consistency
check of the market-data reference. The resulting trade document is then parsed by the
engine's own ``FreshOISInstrument.from_dict`` so it is known to be accepted.

What it does not do: no defaults (every value comes from the inputs), no pricing, no
curve selection or construction, no Excel.

Options are in three groups:
* supported: mapped to the engine;
* not supported by the engine: rejected with the reason (e.g. "Compound Spread");
* semantics not yet defined: rejected until the convention is agreed and implemented
  ("Percentage per Period", interpolation labels other than "Piecewise Linear (Cont)").
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional, Tuple

from instruments.rates.irs.pricing_instrument import FreshOISInstrument, InvalidIRSParameters
from market.market_data_layout import curve_snapshot_name
from services.irs_inputs.contract import (
    SCHEDULE_ROW_KEYS,
    SECTION_KEYS,
    InputValidationError,
    MarketDataRequest,
    NormalizedIRSTrade,
    TradeInputs,
)
from services.pricers.irs_valuation import BENCHMARK_CURVES

# --- label -> engine value (supported) -------------------------------------------------------

CURRENCIES = ("USD", "CHF", "JPY", "INR")
DIRECTIONS = {"Pay": "pay", "Receive": "receive"}
PAYMENT_FREQUENCIES = {"Annual": "annual", "Semiannual": "semiannual",
                       "Quarterly": "quarterly", "Monthly": "monthly"}
DAY_COUNTS = {"ACT/360": "ACT/360", "ACT/365": "ACT/365", "30/360": "30/360"}
BUSINESS_DAY_CONVENTIONS = {"Modified Following": "modified_following",
                            "Following": "following", "Preceding": "preceding",
                            "Unadjusted": "unadjusted"}
# Engine calendar codes (instruments.rates.irs.pricing_instrument; a test keeps them equal).
CALENDARS = ("FD", "JN", "RB", "SZ")
# (benchmark label, index tenor, currency) -> engine overnight benchmark (daily reset).
OVERNIGHT_BENCHMARKS = {("SOFR", "1D", "USD"): "SOFRRATE", ("TONAR", "1D", "JPY"): "MUTKCALM"}
RESET_FREQUENCIES = {"Daily": "daily"}
RATE_TIMINGS = {"In Arrears": "In Arrears", "In Advance": "In Advance"}
LOOKBACK_TYPES = {"Lookback": "Lookback"}
COMPOUNDING = {"Daily Compounded": "daily_compounded"}  # checked only; implied by daily reset
SPREAD_TREATMENTS = {"Exclude Spread": "ExcludeSprd"}
PRINCIPAL_EXCHANGES = {"Never": "never"}
AMORTISATION_TYPES = {"Custom Schedule": "custom", "Bullet / No Amortisation": "bullet"}
# Curve label -> (currency, curve benchmark as in the prepared snapshot).
CURVES = {"USD SOFR": ("USD", "SOFR"), "CHF SARON": ("CHF", "SARON"),
          "JPY TONAR": ("JPY", "TONA"), "INR OIS": ("INR", "MIBOR")}
# Interpolation label -> prepared-snapshot convention. "Piecewise Linear (Cont)" is
# Bloomberg's label for linear interpolation of continuously compounded zero rates; the
# CHF snapshot of Bloomberg curve 234 (labelled so) is built as "linear_zero".
INTERPOLATIONS = {"Piecewise Linear (Cont)": "linear_zero"}

# --- known options that are rejected, with the reason ----------------------------------------

_TERM_RATE = ("is a term-rate (IBOR-fallback) leg; it needs explicit reset inputs that this "
              "input contract does not have")
UNSUPPORTED = {
    "floating_leg.benchmark": {"SARON": _TERM_RATE, "INR OIS": _TERM_RATE},
    "floating_leg.index_tenor": {t: _TERM_RATE for t in ("3M", "6M", "1Y")},
    "floating_leg.reset_frequency": {
        f: "only daily reset (overnight legs) is supported"
        for f in ("Monthly", "Quarterly", "Semiannual", "Annual")},
    "floating_leg.compounding": {"Simple": "not supported by the engine (overnight legs are "
                                           "daily compounded)"},
    "floating_leg.spread_treatment": {"Compound Spread": "not supported by the engine "
                                                         "(only Exclude Spread)"},
    "notional.principal_exchange": {
        p: "principal exchange is not supported by the engine (only Never)"
        for p in ("At Start", "At End", "Start & End")},
}
SEMANTICS_PENDING = {
    "notional.amortisation_type": {
        "Percentage per Period": "semantics not yet defined: whether the percentage is of "
                                 "the original or the outstanding notional must be agreed "
                                 "before it can be priced; use Custom Schedule"},
    "market_data.interpolation": {
        label: "meaning not yet defined against the prepared snapshot's conventions, so it "
               "cannot be checked; leave it empty or use Piecewise Linear (Cont)"
        for label in ("Linear", "Log Linear")},
}


class _Issues:
    def __init__(self) -> None:
        self.items: List[str] = []

    def add(self, path: str, message: str) -> None:
        self.items.append(f"{path}: {message}")


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _text(value: Any, path: str, issues: _Issues, required: bool = True) -> Optional[str]:
    if _missing(value):
        if required:
            issues.add(path, "is required")
        return None
    if not isinstance(value, str):
        issues.add(path, f"must be text, got {value!r}")
        return None
    return value.strip()


def _choice(value: Any, mapping: Mapping[str, Any], path: str, issues: _Issues,
            required: bool = True) -> Optional[Any]:
    label = _text(value, path, issues, required)
    if label is None:
        return None
    if label in mapping:
        return mapping[label]
    for group in (UNSUPPORTED, SEMANTICS_PENDING):
        reason = group.get(path, {}).get(label)
        if reason:
            issues.add(path, f"{label!r} {reason}" if group is UNSUPPORTED
                       else f"{label!r}: {reason}")
            return None
    issues.add(path, f"{label!r} is not a recognised value; expected one of {sorted(mapping)}")
    return None


def _date(value: Any, path: str, issues: _Issues, required: bool = True) -> Optional[date]:
    if _missing(value):
        if required:
            issues.add(path, "is required")
        return None
    if isinstance(value, datetime):
        if value.time() != datetime.min.time():
            issues.add(path, f"must be a date without a time of day, got {value!r}")
            return None
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            pass
    issues.add(path, f"must be a date (YYYY-MM-DD), got {value!r}")
    return None


def _number(value: Any, path: str, issues: _Issues, required: bool = True) -> Optional[Decimal]:
    if _missing(value):
        if required:
            issues.add(path, "is required")
        return None
    if isinstance(value, bool):
        issues.add(path, f"must be a number, got {value!r}")
        return None
    try:
        number = Decimal(str(value).strip()) if isinstance(value, (str, float)) else Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        issues.add(path, f"must be a number, got {value!r}")
        return None
    if not number.is_finite():
        issues.add(path, f"must be a finite number, got {value!r}")
        return None
    return number


def _whole(value: Any, path: str, issues: _Issues) -> Optional[int]:
    number = _number(value, path, issues)
    if number is None:
        return None
    if number != number.to_integral_value() or number < 0:
        issues.add(path, f"must be a whole number of days >= 0, got {value!r}")
        return None
    return int(number)


def _plain(number: Decimal):
    """Engine-document number: int when whole, else float."""
    return int(number) if number == number.to_integral_value() else float(number)


def _section(inputs: TradeInputs, name: str, issues: _Issues) -> Dict[str, Any]:
    section = inputs.get(name) if isinstance(inputs, Mapping) else None
    if not isinstance(section, Mapping):
        issues.add(name, "section is missing")
        return {}
    missing = [k for k in SECTION_KEYS[name] if k not in section]
    unknown = sorted(set(section) - set(SECTION_KEYS[name]))
    for key in missing:
        issues.add(f"{name}.{key}", "field is missing from the inputs")
    for key in unknown:
        issues.add(f"{name}.{key}", "is not a field of the input contract")
    return dict(section)


def _schedule(rows: Any, trade_notional: Optional[Decimal], effective: Optional[date],
              amortisation: Optional[str], issues: _Issues) -> List[Dict[str, Any]]:
    if not isinstance(rows, (list, tuple)) or not rows:
        issues.add("notional.schedule", "at least one period is required")
        return []
    periods: List[Dict[str, Any]] = []
    previous_notional = trade_notional
    previous_end: Optional[date] = None
    for index, row in enumerate(rows, start=1):
        path = f"notional.schedule[{index}]"
        if not isinstance(row, Mapping) or set(row) != set(SCHEDULE_ROW_KEYS):
            issues.add(path, f"must have exactly the fields {list(SCHEDULE_ROW_KEYS)}")
            continue
        number = _whole(row["period"], f"{path}.period", issues)
        if number is not None and number != index:
            issues.add(f"{path}.period", f"periods must be numbered 1, 2, ... in order; "
                                         f"expected {index}, got {number}")
        start = _date(row["accrual_start"], f"{path}.accrual_start", issues)
        end = _date(row["accrual_end"], f"{path}.accrual_end", issues)
        pay = _date(row["payment_date"], f"{path}.payment_date", issues)
        notional = _number(row["notional"], f"{path}.notional", issues)
        if notional is not None and notional <= 0:
            issues.add(f"{path}.notional", f"must be positive, got {row['notional']!r}")
        if start and end and not start < end:
            issues.add(path, f"accrual_start {start} must be before accrual_end {end}")
        if index == 1 and start and effective and start != effective:
            issues.add(f"{path}.accrual_start", f"must equal the effective date {effective} "
                                                f"(unadjusted), got {start}")
        if previous_end and start and start != previous_end:
            issues.add(f"{path}.accrual_start", f"periods must be contiguous: expected "
                                                f"{previous_end}, got {start}")
        if index == 1 and notional is not None and trade_notional is not None \
                and notional != trade_notional:
            issues.add(f"{path}.notional", f"the first period notional must equal "
                                           f"trade.notional {trade_notional}, got {notional}")
        expected_amount = (previous_notional - notional
                           if previous_notional is not None and notional is not None else None)
        amount = _number(row["amortisation_amount"], f"{path}.amortisation_amount", issues,
                         required=False)
        if amount is not None and expected_amount is not None and amount != expected_amount:
            issues.add(f"{path}.amortisation_amount", f"{amount} is inconsistent with the "
                       f"notionals (previous {previous_notional} - this {notional} = "
                       f"{expected_amount})")
        percent = _number(row["amortisation_percent"], f"{path}.amortisation_percent", issues,
                          required=False)
        if percent is not None and not (percent == 0 and expected_amount == 0):
            issues.add(f"{path}.amortisation_percent", "must be empty: its base (original or "
                       "outstanding notional) is not yet defined, so only the notional and "
                       "amortisation amount are used")
        if not _missing(row["action"]):
            issues.add(f"{path}.action", f"has no defined meaning yet and must be empty, got "
                                         f"{row['action']!r}")
        if amortisation == "bullet" and notional is not None and trade_notional is not None \
                and notional != trade_notional:
            issues.add(f"{path}.notional", f"Bullet / No Amortisation requires every period "
                                           f"notional to equal {trade_notional}")
        previous_notional, previous_end = notional, end
        if start and end and pay and notional is not None:
            periods.append({"accrual_start": start.isoformat(), "accrual_end": end.isoformat(),
                            "payment_date": pay.isoformat(), "notional": _plain(notional)})
    return periods


def normalize(inputs: TradeInputs, source: str = "trade inputs") -> NormalizedIRSTrade:
    """Validate ``inputs`` and return the engine trade document and market request.
    Raises ``InputValidationError`` listing every problem found."""
    issues = _Issues()
    if not isinstance(inputs, Mapping):
        raise InputValidationError(["inputs must be a mapping of sections"], source)
    unknown = sorted(set(inputs) - set(SECTION_KEYS))
    for name in unknown:
        issues.add(name, "is not a section of the input contract")
    trade = _section(inputs, "trade", issues)
    fixed = _section(inputs, "fixed_leg", issues)
    floating = _section(inputs, "floating_leg", issues)
    notional_section = _section(inputs, "notional", issues)
    market = _section(inputs, "market_data", issues)

    trade_id = _text(trade.get("trade_id"), "trade.trade_id", issues)
    currency = _choice(trade.get("currency"), {c: c for c in CURRENCIES}, "trade.currency",
                       issues)
    trade_notional = _number(trade.get("notional"), "trade.notional", issues)
    effective = _date(trade.get("effective_date"), "trade.effective_date", issues)
    maturity = _date(trade.get("maturity_date"), "trade.maturity_date", issues)
    valuation = _date(trade.get("valuation_date"), "trade.valuation_date", issues)
    if effective and maturity and not effective < maturity:
        issues.add("trade", f"effective_date {effective} must be before maturity_date {maturity}")

    fixed_side = _choice(fixed.get("direction"), DIRECTIONS, "fixed_leg.direction", issues)
    rate_percent = _number(fixed.get("rate_percent"), "fixed_leg.rate_percent", issues)
    fixed_frequency = _choice(fixed.get("payment_frequency"), PAYMENT_FREQUENCIES,
                              "fixed_leg.payment_frequency", issues)
    fixed_day_count = _choice(fixed.get("day_count"), DAY_COUNTS, "fixed_leg.day_count", issues)
    fixed_bdc = _choice(fixed.get("business_day_convention"), BUSINESS_DAY_CONVENTIONS,
                        "fixed_leg.business_day_convention", issues)
    fixed_calendar = _choice(fixed.get("calendar"), {c: c for c in CALENDARS},
                             "fixed_leg.calendar", issues)

    float_side = _choice(floating.get("direction"), DIRECTIONS, "floating_leg.direction", issues)
    if fixed_side and float_side and fixed_side == float_side:
        issues.add("floating_leg.direction", f"must be the opposite of the fixed leg "
                                             f"({fixed.get('direction')})")
    benchmark_label = _choice(floating.get("benchmark"),
                              {b: b for b, _, _ in OVERNIGHT_BENCHMARKS},
                              "floating_leg.benchmark", issues)
    tenor = _choice(floating.get("index_tenor"), {"1D": "1D"}, "floating_leg.index_tenor",
                    issues)
    benchmark = None
    if benchmark_label and tenor and currency:
        benchmark = OVERNIGHT_BENCHMARKS.get((benchmark_label, tenor, currency))
        if benchmark is None:
            issues.add("floating_leg.benchmark", f"{benchmark_label} {tenor} is not a "
                       f"supported {currency} overnight benchmark; supported: "
                       f"{sorted(OVERNIGHT_BENCHMARKS)}")
    spread_bp = _number(floating.get("spread_bp"), "floating_leg.spread_bp", issues)
    leverage = _number(floating.get("leverage"), "floating_leg.leverage", issues)
    reset = _choice(floating.get("reset_frequency"), RESET_FREQUENCIES,
                    "floating_leg.reset_frequency", issues)
    float_frequency = _choice(floating.get("payment_frequency"), PAYMENT_FREQUENCIES,
                              "floating_leg.payment_frequency", issues)
    float_day_count = _choice(floating.get("day_count"), DAY_COUNTS, "floating_leg.day_count",
                              issues)
    float_bdc = _choice(floating.get("business_day_convention"), BUSINESS_DAY_CONVENTIONS,
                        "floating_leg.business_day_convention", issues)
    float_calendar = _choice(floating.get("calendar"), {c: c for c in CALENDARS},
                             "floating_leg.calendar", issues)
    rate_timing = _choice(floating.get("rate_timing"), RATE_TIMINGS, "floating_leg.rate_timing",
                          issues)
    lookback = _whole(floating.get("lookback_days"), "floating_leg.lookback_days", issues)
    lookback_type = _choice(floating.get("lookback_type"), LOOKBACK_TYPES,
                            "floating_leg.lookback_type", issues)
    cutoff = _whole(floating.get("rate_cutoff_days"), "floating_leg.rate_cutoff_days", issues)
    _choice(floating.get("compounding"), COMPOUNDING, "floating_leg.compounding", issues)
    spread_treatment = _choice(floating.get("spread_treatment"), SPREAD_TREATMENTS,
                               "floating_leg.spread_treatment", issues)

    _choice(notional_section.get("principal_exchange"), PRINCIPAL_EXCHANGES,
            "notional.principal_exchange", issues)
    amortisation = _choice(notional_section.get("amortisation_type"), AMORTISATION_TYPES,
                           "notional.amortisation_type", issues)
    periods = _schedule(notional_section.get("schedule"), trade_notional, effective,
                        amortisation, issues)

    curve = _choice(market.get("curve"), CURVES, "market_data.curve", issues)
    curve_benchmark = None
    if curve and currency:
        curve_currency, curve_benchmark = curve
        if curve_currency != currency:
            issues.add("market_data.curve", f"{market.get('curve')} is not a {currency} curve")
        if benchmark and BENCHMARK_CURVES.get(benchmark) != curve_benchmark:
            issues.add("market_data.curve", f"{benchmark_label} is projected on the "
                       f"{BENCHMARK_CURVES.get(benchmark)} curve, not {curve_benchmark}")
    folder = _text(market.get("snapshot_folder"), "market_data.snapshot_folder", issues,
                   required=False)
    if folder and valuation and currency:
        expected_folder = f"market_data/{valuation.isoformat()}/{currency}/"
        if folder.replace("\\", "/").rstrip("/") + "/" != expected_folder:
            issues.add("market_data.snapshot_folder", f"{folder!r} does not match the "
                       f"valuation date and currency ({expected_folder!r})")
    curve_file = _text(market.get("curve_source_file"), "market_data.curve_source_file", issues)
    if curve_file and valuation and currency and curve_benchmark:
        expected_file = curve_snapshot_name(valuation, currency, curve_benchmark)
        if curve_file != expected_file:
            issues.add("market_data.curve_source_file", f"{curve_file!r} is not the prepared "
                       f"{currency} {curve_benchmark} snapshot for {valuation} "
                       f"({expected_file!r})")
    fixings_file = _text(market.get("fixings_source_file"), "market_data.fixings_source_file",
                         issues, required=False)
    reference_date = _date(market.get("reference_date"), "market_data.reference_date", issues,
                           required=False)
    interpolation = _choice(market.get("interpolation"), INTERPOLATIONS,
                            "market_data.interpolation", issues, required=False)

    if issues.items:
        raise InputValidationError(issues.items, source)

    adjustment = {"calendar": fixed_calendar, "business_day_convention": fixed_bdc}
    float_adjustment = {"calendar": float_calendar, "business_day_convention": float_bdc}
    params = {
        "trade_id": trade_id,
        "currency": currency,
        "valuation_date": valuation.isoformat(),
        "effective_date": effective.isoformat(),
        "maturity_date": maturity.isoformat(),
        "fixed_leg_side": fixed_side,
        "fixed_leg": {
            "day_count": fixed_day_count,
            "payment_frequency": fixed_frequency,
            "fixed_rate": float(rate_percent / 100),
            "accrual_date_adjustment": adjustment,
            "periods": [dict(p) for p in periods],
        },
        "floating_leg": {
            "day_count": float_day_count,
            "payment_frequency": float_frequency,
            "benchmark": benchmark,
            "benchmark_tenor": tenor,
            "spread": float(spread_bp / 10000),
            "leverage": float(leverage),
            "reset_frequency": reset,
            "accrual_date_adjustment": float_adjustment,
            "observation": {
                "lookback_days": lookback,
                "cutoff_days": cutoff,
                "reset_timing": rate_timing,
                "compounding": spread_treatment,
                "lookback_type": lookback_type,
            },
            "periods": [dict(p) for p in periods],
        },
    }
    try:
        FreshOISInstrument.from_dict(params)  # the engine's own validation
    except InvalidIRSParameters as exc:
        raise InputValidationError([f"engine rejected the trade: {exc}"], source) from exc
    document = {"schema_version": 1, "instrument_type": "ois", "params": params}
    request = MarketDataRequest(valuation_date=valuation, currency=currency,
                                curve_benchmark=curve_benchmark, curve_file=curve_file,
                                fixings_file=fixings_file, reference_date=reference_date,
                                interpolation=interpolation)
    notes: Tuple[str, ...] = ()
    if interpolation is None:
        notes += ("market_data.interpolation not stated: the prepared snapshot's convention "
                  "applies and is not checked",)
    return NormalizedIRSTrade(trade_document=document, market=request, notes=notes)
