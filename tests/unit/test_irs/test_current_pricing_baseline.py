"""Reproducible, diagnostic-only baseline for the supported Bloomberg IRS cases.

This test composes the existing fresh IRS schedule, leg, curve, instrument, and
engine functions. It does not assert equality with Bloomberg outputs. Unsupported
benchmark mappings are recorded as such instead of being implemented here.
"""

from __future__ import annotations

import json
import math
from datetime import date
from decimal import Decimal
from pathlib import Path

import QuantLib as ql

from core.enums.definitions import DayCountConvention, Frequency
from core.types.value_objects import Money
from instruments.rates.irs.domain import (
    IRSLegKind,
    IRSLegTerms,
    IRSTrade,
    ObservationConventions,
)
from instruments.rates.irs.engine import attach_discounting_engine
from instruments.rates.irs.fixed_leg import build_fixed_leg
from instruments.rates.irs.floating_leg import (
    build_floating_leg,
)
from instruments.rates.irs.instrument import assemble_quantlib_irs
from instruments.rates.irs.quantlib_schedule import translate_leg_schedule
from instruments.rates.irs.schedule import CouponPeriod, LegSchedule
from market.curves.irs_market_data import (
    DiscountCurveMarketData,
    DiscountFactorObservation,
    SimpleForwardCurveMarketData,
    SimpleForwardObservation,
    build_discount_curve,
)
from market.curves.irs_provisional_projection import build_provisional_projection_curve

import pytest  # noqa: E402

# Validation-phase test (reads Bloomberg fixtures): excluded from the default run;
# run with `pytest -m validation`.
pytestmark = pytest.mark.validation


ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = ROOT / "tests/fixtures/bloomberg_irs"
MARKET_ROOT = ROOT / "market_data/2026-03-31"
SUPPORTED_CASES = ("TC1", "TC3", "TC4")
UNSUPPORTED_REASON = (
    "fresh floating-index builder supports only SOFRRATE/1D/USD/Daily; "
    "no alternate currency/benchmark mapping is implemented"
)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _frequency(value: str) -> Frequency:
    normalized = value.replace("-", "").replace("_", "").lower()
    return {
        "annual": Frequency.ANNUAL,
        "semiannual": Frequency.SEMIANNUAL,
        "quarterly": Frequency.QUARTERLY,
        "monthly": Frequency.MONTHLY,
        "weekly": Frequency.WEEKLY,
        "daily": Frequency.DAILY,
        "once": Frequency.ONCE,
    }[normalized]


def _day_count(value: str) -> DayCountConvention:
    return {
        "ACT/360": DayCountConvention.ACT_360,
        "ACT/365": DayCountConvention.ACT_365,
        "30/360": DayCountConvention.THIRTY_360,
    }[value]


def _period_rows(case_id: str, case: dict) -> tuple[list[dict], list[dict]]:
    if case_id == "TC1":
        trade = case["trade"]
        boundaries = case["schedule_inputs"]["pay_leg"]["explicit_accrual_boundaries"]
        payment_dates = case["schedule_inputs"]["pay_leg"]["payment_dates"]
        balances = (530000, 265000)
        rows = [
            {
                "accrual_start": boundaries[i],
                "accrual_end": boundaries[i + 1],
                "pay_date": payment_dates[i],
                "balance": balances[i],
            }
            for i in range(len(payment_dates))
        ]
        return rows, rows

    inputs = case["input_sections"]
    return inputs["leg_1"]["amortization"], inputs["leg_2"]["amortization"]


def _make_case_terms(case_id: str, case: dict):
    if case_id == "TC1":
        trade_data = case["trade"]
        fixed_data = trade_data["pay_leg"]
        float_data = trade_data["receive_leg"]
        fixed_frequency = fixed_data["payment_frequency"]
        float_frequency = float_data["payment_frequency"]
        fixed_coupon = fixed_data["fixed_coupon"]["value"]
        spread_bps = float_data["floating_spread"]["value"]
        benchmark, tenor = "SOFRRATE", float_data["benchmark_tenor"]
        reset_frequency = float_data["reset_frequency"]
        observation = float_data["observation"]
        fixed_dc, float_dc = fixed_data["day_count"], float_data["day_count"]
        notional = Decimal(str(fixed_data["original_notional"]["amount"]))
    else:
        inputs = case["input_sections"]
        trade_data = inputs["trade"]
        fixed_data, float_data = inputs["leg_1"], inputs["leg_2"]
        fixed_frequency, float_frequency = fixed_data["pay_frequency"], float_data["pay_frequency"]
        fixed_coupon, spread_bps = fixed_data["coupon"], float_data["spread"]
        benchmark, tenor = float_data["index"], float_data["index_tenor"]
        reset_frequency = float_data["reset_frequency"]
        observation = {
            "lookback_days": float_data["days_before_accrual"],
            "lookback_type": float_data["days_before_type"],
            "cutoff_days": float_data["rate_cut_off_days"],
            "reset_timing": float_data["reset_type"],
            "compounding": float_data["compounding"],
        }
        fixed_dc, float_dc = fixed_data["day_count"], float_data["day_count"]
        notional = Decimal(str(fixed_data["notional"]))

    currency = trade_data["currency"]
    fixed_terms = IRSLegTerms(
        kind=IRSLegKind.FIXED,
        payment_frequency=_frequency(fixed_frequency),
        day_count=_day_count(fixed_dc),
        original_notional=Money(notional, currency),
        fixed_coupon_rate=Decimal(str(fixed_coupon)) / Decimal(100),
    )
    floating_terms = IRSLegTerms(
        kind=IRSLegKind.FLOATING,
        payment_frequency=_frequency(float_frequency),
        day_count=_day_count(float_dc),
        original_notional=Money(notional, currency),
        benchmark=benchmark,
        benchmark_tenor=tenor,
        floating_spread_rate=Decimal(str(spread_bps)) / Decimal(10000),
        floating_leverage=Decimal(str(float_data.get("leverage", 1.0))),
        reset_frequency=_frequency(reset_frequency),
        observation=ObservationConventions(
            lookback_days=observation["lookback_days"],
            cutoff_days=observation["cutoff_days"],
            reset_timing=observation["reset_timing"],
            compounding=observation["compounding"],
            lookback_type=observation["lookback_type"],
        ),
    )
    return trade_data, fixed_terms, floating_terms


def _leg_schedule(rows: list[dict], currency: str, fallback_notional: Decimal) -> LegSchedule:
    periods = tuple(
        CouponPeriod(
            accrual_start=date.fromisoformat(row["accrual_start"]),
            accrual_end=date.fromisoformat(row["accrual_end"]),
            payment_date=date.fromisoformat(row["pay_date"]),
            notional=Money(Decimal(str(row.get("balance", fallback_notional))), currency),
        )
        for row in rows
    )
    return LegSchedule(periods=periods, principal_repayments=())


def _case_reference(case_id: str) -> dict:
    return _json(FIXTURE_ROOT / "references" / f"{case_id}.json")["source_oracle_sections"]


def _price_case(case_id: str) -> dict:
    case = _json(FIXTURE_ROOT / "cases" / f"{case_id}.json")
    market = _json(MARKET_ROOT / "USD/market_data.json")
    trade_data, fixed_terms, floating_terms = _make_case_terms(case_id, case)

    valuation_date = date.fromisoformat(trade_data["valuation_date"])
    effective_date = date.fromisoformat(trade_data["effective_date"])
    maturity_date = date.fromisoformat(trade_data["maturity_date"])
    currency = trade_data["currency"]
    ql.Settings.instance().evaluationDate = ql.Date(
        valuation_date.day, valuation_date.month, valuation_date.year
    )

    trade = IRSTrade(
        trade_id=case["source"]["trade_id"],
        currency=currency,
        valuation_date=valuation_date,
        effective_date=effective_date,
        maturity_date=maturity_date,
        pay_leg=fixed_terms,
        receive_leg=floating_terms,
        principal_exchange="Never",
    )
    fixed_rows, floating_rows = _period_rows(case_id, case)
    fixed_schedule = translate_leg_schedule(
        _leg_schedule(fixed_rows, currency, fixed_terms.original_notional.amount)
    )
    floating_schedule = translate_leg_schedule(
        _leg_schedule(floating_rows, currency, floating_terms.original_notional.amount)
    )

    points = market["observations"]
    reference_date = date.fromisoformat(market["reference_date"])
    discount_data = DiscountCurveMarketData(
        reference_date,
        currency,
        tuple(
            DiscountFactorObservation(
                date.fromisoformat(point["date"]), Decimal(str(point["discount_factor"]))
            )
            for point in points
        ),
    )
    projection_data = SimpleForwardCurveMarketData(
        reference_date,
        currency,
        "SOFR",
        tuple(
            SimpleForwardObservation(
                date.fromisoformat(point["date"]), Decimal(str(point["market_rate"]))
            )
            for point in points
        ),
    )
    discount_curve = build_discount_curve(
        discount_data, day_counter=ql.Actual360(), expected_currency=currency
    )
    projection_curve = build_provisional_projection_curve(
        projection_data,
        day_counter=ql.Actual360(),
        expected_currency=currency,
        expected_benchmark="SOFR",
    )

    fixed_leg = build_fixed_leg(trade.pay_leg, fixed_schedule)
    floating_leg = build_floating_leg(
        trade.receive_leg,
        floating_schedule,
        currency,
        forwarding_curve=projection_curve.handle,
    )
    instrument = assemble_quantlib_irs(fixed_leg, floating_leg)
    attach_discounting_engine(instrument, discount_curve)
    swap = instrument.quantlib_instrument

    fixed_npv, floating_npv, total_npv = (
        swap.legNPV(0), swap.legNPV(1), swap.NPV()
    )
    if not all(math.isfinite(value) for value in (fixed_npv, floating_npv, total_npv)):
        raise ValueError(f"{case_id} produced a non-finite NPV")

    reference = _case_reference(case_id)
    fixed_oracle = reference["cashflow_leg_1"]
    float_oracle = reference["cashflow_leg_2"]
    fixed_rows_oracle = fixed_oracle["cashflows"]
    float_rows_oracle = float_oracle["cashflows"]

    valuation_ql_date = ql.Date(valuation_date.day, valuation_date.month, valuation_date.year)

    def cashflow_rows(coupons, source_rows, direction):
        output = []
        source_by_date = {row["pay_date"]: row for row in source_rows}
        for index, coupon in enumerate(coupons):
            pay_date = coupon.date().ISO()
            source_row = source_by_date.get(pay_date, {})
            discount_factor = discount_curve.handle.discount(coupon.date())
            try:
                coupon_rate = coupon.rate()
                coupon_amount = coupon.amount()
                cashflow_status = "available"
            except RuntimeError:
                if coupon.date() > valuation_ql_date:
                    raise
                # An already-due overnight coupon can require historical SOFR
                # fixings that are absent from these forward-only market inputs.
                coupon_rate = None
                coupon_amount = None
                cashflow_status = "historical fixing unavailable"
            output.append({
                "date": pay_date,
                "accrual_start": coupon.accrualStartDate().ISO(),
                "accrual_end": coupon.accrualEndDate().ISO(),
                "notional": coupon.nominal(),
                "coupon": coupon_rate,
                "amount": None if coupon_amount is None else coupon_amount * direction,
                "discount_factor": discount_factor,
                "pv": (
                    None if coupon_amount is None or coupon.date() <= valuation_ql_date
                    else coupon_amount * discount_factor * direction
                ),
                "status": cashflow_status,
                "bloomberg_notional": source_row.get("notional"),
                "bloomberg_coupon": source_row.get("equivalent_coupon", source_row.get("equiv_coupon")),
                "bloomberg_amount": source_row.get("payment"),
                "bloomberg_discount_factor": source_row.get("discount_factor", source_row.get("discount")),
                "bloomberg_pv": source_row.get("pv"),
            })
        return output

    return {
        "case_id": case_id,
        "trade_id": trade.trade_id,
        "currency": currency,
        "status": "priced",
        "fixed_npv": fixed_npv,
        "floating_npv": floating_npv,
        "total_npv": total_npv,
        "reference": reference,
        "fixed_cashflows": cashflow_rows(fixed_leg.coupons, fixed_rows_oracle, -1),
        "floating_cashflows": cashflow_rows(floating_leg.coupons, float_rows_oracle, 1),
    }


def collect_baseline() -> list[dict]:
    results = []
    for number in range(1, 11):
        case_id = f"TC{number}"
        if case_id not in SUPPORTED_CASES:
            benchmark, tenor, reset = _unsupported_case_mapping(case_id)
            results.append({
                "case_id": case_id,
                "currency": _case_currency(case_id),
                "trade_id": _json(FIXTURE_ROOT / "cases" / f"{case_id}.json")["source"]["trade_id"],
                "status": "unsupported",
                "reason": (
                    f"unsupported mapping ({_case_currency(case_id)}, {benchmark}, "
                    f"{tenor}, {reset}); {UNSUPPORTED_REASON}"
                ),
            })
            continue
        results.append(_price_case(case_id))
    return results


def _case_currency(case_id: str) -> str:
    case = _json(FIXTURE_ROOT / "cases" / f"{case_id}.json")
    if case_id == "TC1":
        return case["trade"]["currency"]
    sections = case["input_sections"]
    if int(case_id[2:]) <= 5:
        return sections["trade"]["currency"]
    if int(case_id[2:]) <= 9:
        return sections["trade"]["legs"]["floating"]["currency"]
    return sections["trade"]["currency"]


def _unsupported_case_mapping(case_id: str) -> tuple[str, str, str]:
    case = _json(FIXTURE_ROOT / "cases" / f"{case_id}.json")
    number = int(case_id[2:])
    if number <= 5:
        floating = case["input_sections"]["leg_2"]
        return floating["index"], floating["index_tenor"], floating["reset_frequency"]
    if number <= 9:
        floating = case["input_sections"]["trade"]["legs"]["floating"]
        return floating["index"], floating["index_tenor"], floating["reset_frequency"]
    floating = case["input_sections"]["floating_leg"]
    return floating["index"], floating["index_tenor"], floating["reset_frequency"]


def _fmt(value):
    return "—" if value is None else f"{value:.6f}"


def render_baseline_report(results: list[dict]) -> str:
    lines = [
        "# Current IRS Pricing Baseline — TC1–TC10",
        "",
        "Diagnostic baseline for the existing fresh IRS component path. No production pricing code, fixture, market data, or reference values were changed. The supported cases are composed from the repository's fixed/floating leg builders, discount curve, explicitly provisional projection curve, QuantLib swap, and discounting engine. There is not yet a general IRS PricingService adapter for these fixtures.",
        "",
        "Projection inputs use the existing provisional projection-curve builder. This report records current behavior; it does not validate that methodology against Bloomberg.",
        "",
        "## 1. Execution status",
        "",
        "| TC | Currency | Trade ID | Status | Reason when unsupported |",
        "|---|---|---|---|---|",
    ]
    for result in results:
        lines.append(
            f"| {result['case_id']} | {result['currency']} | {result.get('trade_id', '—')} | "
            f"{result['status']} | {result.get('reason', '—')} |"
        )

    lines += [
        "",
        "## 2. NPV comparison",
        "",
        "Differences are Optima minus Bloomberg. Bloomberg NPVs are taken from the detailed cashflow NPV fields in each reference fixture; separate market-summary/leg-summary NPVs are retained in the oracle reconnaissance report and are not substituted here.",
        "",
        "| TC | Currency | Bloomberg Fixed NPV | Optima Fixed NPV | Diff | Bloomberg Float NPV | Optima Float NPV | Diff | Bloomberg Total NPV | Optima Total NPV | Diff | Status |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for result in results:
        if result["status"] != "priced":
            lines.append(f"| {result['case_id']} | {result['currency']} | — | — | — | — | — | — | — | — | — | unsupported |")
            continue
        ref = result["reference"]
        bfixed = ref["cashflow_leg_1"]["npv"]
        bfloat = ref["cashflow_leg_2"]["npv"]
        btotal = ref["cashflow"]["npv"] if "cashflow" in ref else ref["cashflows"]["net_npv"]
        lines.append(
            f"| {result['case_id']} | {result['currency']} | {bfixed:.6f} | {result['fixed_npv']:.6f} | {result['fixed_npv']-bfixed:.6f} | "
            f"{bfloat:.6f} | {result['floating_npv']:.6f} | {result['floating_npv']-bfloat:.6f} | "
            f"{btotal:.6f} | {result['total_npv']:.6f} | {result['total_npv']-btotal:.6f} | priced |"
        )

    lines += ["", "## 3. Cashflow comparison", "", "Payment-date matching is used. Bloomberg source notionals, payment amounts, and PVs retain their supplied signs; QuantLib leg coupon amounts are signed as Pay negative / Receive positive for comparison. A dash means the reference has no detailed cashflow for that date, a historical fixing is missing, or the engine excludes a cashflow paid on the valuation date. Optima discount factors are queried from the current direct discount curve. Accrual dates are those exposed by the QuantLib coupon objects.", "", "| TC | Leg | Accrual start | Accrual end | Pay date | Bloomberg signed notional | Optima nominal | Bloomberg equivalent coupon | Optima coupon | Bloomberg signed amount | Optima signed amount | Bloomberg DF | Optima DF | Bloomberg signed PV | Optima signed PV |", "|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for result in results:
        if result["status"] != "priced":
            continue
        for leg_name in ("fixed_cashflows", "floating_cashflows"):
            label = "Fixed (Pay)" if leg_name == "fixed_cashflows" else "Floating (Receive)"
            for row in result[leg_name]:
                lines.append(
                    f"| {result['case_id']} | {label} | {row['accrual_start']} | {row['accrual_end']} | {row['date']} | {_fmt(row['bloomberg_notional'])} | {_fmt(row['notional'])} | "
                    f"{_fmt(row['bloomberg_coupon'])} | {_fmt(row['coupon'])} | {_fmt(row['bloomberg_amount'])} | {_fmt(row['amount'])} | "
                    f"{_fmt(row['bloomberg_discount_factor'])} | {_fmt(row['discount_factor'])} | {_fmt(row['bloomberg_pv'])} | {_fmt(row['pv'])} |"
                )

    lines += ["", "## 4. Notional/amortisation comparison", "", "Period notionals below are QuantLib coupon nominals and are compared against the signed Bloomberg source nominal. Pay-leg QuantLib nominals are positive coupon bases while Bloomberg stores Pay-side notionals as negative. TC3/TC4 absolute period notionals agree for matched future payment dates. TC1 raw oracle cashflow notionals remain at the residual 1000x scale (530000000 / 265000000), while the normalized case and current QuantLib coupon bases are 530000 / 265000; the source oracle was not altered. No separate principal exchange cashflows are generated by this path.", "", "## 5. Market-data / benchmark limitations", "", f"The current floating-index builder supports only `('SOFRRATE', '1D', 'USD', Daily)`. TC2 and TC5–TC10 cannot be constructed through this builder because their currencies and/or benchmarks differ. TC3 and TC4 match the USD SOFR mapping. TC1 is measured through the existing TC1 pattern, which supplies the Bloomberg source identifier `SOFRRATE` to the builder; the normalized domain case field is `SOFR` and is not accepted by the current mapping directly.", "", "The curve module has a stable direct discount-factor builder. The confirmed forward-curve builder still raises `ProjectionCurveMethodologyUnspecified`; supported-case pricing therefore uses the separately named provisional projection builder already used by the TC1 pricing test. TC4's already-due 2026-03-31 floating coupon cannot expose a coupon amount or rate because the market inputs contain no historical SOFR fixing for its accrual; this did not prevent calculation of the swap NPV at the valuation date.", "", "## 6. Observed discrepancy patterns", ""]
    for result in results:
        if result["status"] != "priced":
            continue
        ref = result["reference"]
        bf, bl, bt = ref["cashflow_leg_1"]["npv"], ref["cashflow_leg_2"]["npv"], ref["cashflow"]["npv"]
        lines.append(
            f"- {result['case_id']}: fixed difference {result['fixed_npv']-bf:.6f}; floating difference {result['floating_npv']-bl:.6f}; total difference {result['total_npv']-bt:.6f}. "
                f"Period counts are {len(result['fixed_cashflows'])} fixed and {len(result['floating_cashflows'])} floating."
        )
    lines += ["", "## 7. Baseline conclusion", "", f"{sum(r['status']=='priced' for r in results)} of 10 cases priced through the current fresh IRS component path; {sum(r['status']=='unsupported' for r in results)} were unsupported by the current floating benchmark mapping.", "TC1 remains a discrepancy, and the measured TC3 and TC4 results show additional discrepancies. This baseline does not diagnose or correct them.", ""]
    return "\n".join(lines)


def test_current_pricing_baseline_report_can_be_generated():
    settings = ql.Settings.instance()
    previous_evaluation_date = settings.evaluationDate
    try:
        results = collect_baseline()
    finally:
        settings.evaluationDate = previous_evaluation_date
    assert [result["status"] for result in results].count("priced") == 3
    assert [result["status"] for result in results].count("unsupported") == 7
    report = render_baseline_report(results)
    assert report.startswith("# Current IRS Pricing Baseline — TC1–TC10")
    assert all(f"| TC{number} |" in report for number in range(1, 11))
    assert "Differences are Optima minus Bloomberg" in report
    assert "unsupported" in report

