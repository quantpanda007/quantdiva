"""Price TC1 and TC3 through the fresh IRS service path and compare with Bloomberg.

Diagnostic only: it prints results and changes nothing.

Run from the project root:

    python scripts/irs_fresh_pricing_report.py

Path: InstrumentRequest(type "ois") -> build_instrument_from_request ->
PricingService.price(model "analytical", engine "discounting"), with the
USD SOFR environment from build_single_curve_irs_environment. Trade parameters,
the zero curve and the Bloomberg references come from the same test-side helpers
and fixtures as the end-to-end tests (tests/unit/test_irs), so inputs and
conventions are identical to the tests. Leg NPVs and the period cashflows are
read from the swap the engine priced (FreshOISInstrument.leg_npvs() and
instruments.rates.irs.cashflows.irs_cashflow_rows on instrument.last_built).

Differences are Optima minus Bloomberg. Periods with a documented difference are
tagged with their open item (docs/IRS_OPEN_ITEMS.md): TC1 floating P2 and TC3
floating P3 are OI-1 (30-Nov-2027); TC3 floating P4 is OI-7 (28-Apr-2028). Fixed
rows paying on those dates are tagged "DF": only their discount factor differs.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
IRS_TESTS = ROOT / "tests" / "unit" / "test_irs"
for _path in (ROOT, IRS_TESTS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import QuantLib as ql  # noqa: E402
from conftest import build_usd_sofr_zero_curve, load_tc1  # noqa: E402
from test_tc1_pricing_service_e2e import _tc1_params  # noqa: E402
from test_tc3_pricing_service_e2e import _load as load_tc3  # noqa: E402
from test_tc3_pricing_service_e2e import tc3_params  # noqa: E402

from api.v1.helpers import build_instrument_from_request  # noqa: E402
from api.v1.schemas import InstrumentRequest  # noqa: E402
from core.interfaces.base import MarketEnvironment  # noqa: E402
from instruments.rates.irs.cashflows import IRSCashflowRow, irs_cashflow_rows  # noqa: E402
from market.curves.irs_market_environment import build_single_curve_irs_environment  # noqa: E402
from services.pricers.pricing_service import PricingService  # noqa: E402

VALUATION_DATE = date(2026, 3, 31)
METRICS = ("fixed_leg_npv", "floating_leg_npv", "npv")

# (leg, period) -> open item, for periods with a documented Bloomberg difference.
# "DF" marks fixed-leg rows affected only through the discount factor on the same
# payment date (their amounts reconcile).
KNOWN_DIFFERENCE_TAGS = {
    "TC1": {("floating", 2): "OI-1", ("fixed", 2): "OI-1 DF"},
    "TC3": {
        ("floating", 3): "OI-1",
        ("floating", 4): "OI-7",
        ("fixed", 3): "OI-1 DF",
        ("fixed", 4): "OI-7 DF",
    },
}


@dataclass(frozen=True)
class BloombergCashflow:
    """One Bloomberg cashflow row (``cashflow_leg_*``), signed as Bloomberg shows it."""

    payment_date: date
    rate: float | None  # equivalent coupon, decimal; None if Bloomberg does not show it
    amount: float
    discount_factor: float
    present_value: float


@dataclass(frozen=True)
class TradeReport:
    case_id: str
    trade_id: str
    currency: str
    optima: Dict[str, float]
    bloomberg: Dict[str, float]
    cashflows: Tuple[IRSCashflowRow, ...] = ()
    bloomberg_cashflows: Dict[Tuple[str, int], BloombergCashflow] = field(default_factory=dict)
    tags: Dict[Tuple[str, int], str] = field(default_factory=dict)

    @property
    def differences(self) -> Dict[str, float]:
        return {metric: self.optima[metric] - self.bloomberg[metric] for metric in METRICS}


def _bloomberg_cashflows(sections: dict) -> Dict[Tuple[str, int], BloombergCashflow]:
    """Bloomberg cashflow-leg rows keyed by (leg, period)."""
    rows = {}
    for section in ("cashflow_leg_1", "cashflow_leg_2"):
        label = sections[section]["leg"]  # e.g. "Pay Fixed", "Receive Float"
        leg = "fixed" if "Fixed" in label else "floating"
        for number, row in enumerate(sections[section]["cashflows"], start=1):
            coupon = row.get("equivalent_coupon")
            rows[(leg, number)] = BloombergCashflow(
                payment_date=date.fromisoformat(row["pay_date"]),
                rate=None if coupon is None else coupon / 100.0,
                amount=row["payment"],
                discount_factor=row["discount_factor"],
                present_value=row["pv"],
            )
    return rows


def _tc1_inputs() -> Tuple[dict, Dict[str, float], dict]:
    case, source, reference = load_tc1()
    outputs = {item["name"]: item["value"] for item in reference["outputs"]}
    bloomberg = {
        "fixed_leg_npv": outputs["fixed_leg_npv"],
        "floating_leg_npv": outputs["floating_leg_npv"],
        "npv": outputs["total_npv"],
    }
    return _tc1_params(case, source), bloomberg, reference["source_oracle_sections"]


def _tc3_inputs() -> Tuple[dict, Dict[str, float], dict]:
    sections = load_tc3("references")["source_oracle_sections"]
    bloomberg = {
        # Cashflow-leg PVs; the leg_*_market values are not leg PVs (OI-9).
        "fixed_leg_npv": sections["cashflow_leg_1"]["npv"],
        "floating_leg_npv": sections["cashflow_leg_2"]["npv"],
        "npv": sections["valuation_results"]["npv"],
    }
    return tc3_params(load_tc3("cases")), bloomberg, sections


CASES: Dict[str, Callable[[], Tuple[dict, Dict[str, float], dict]]] = {
    "TC1": _tc1_inputs,
    "TC3": _tc3_inputs,
}


def usd_sofr_environment() -> MarketEnvironment:
    """Same environment as the end-to-end tests: one USD SOFR zero curve for both
    discounting and projection."""
    return build_single_curve_irs_environment(VALUATION_DATE, build_usd_sofr_zero_curve())


def price_case(case_id: str, environment: MarketEnvironment) -> TradeReport:
    params, bloomberg, sections = CASES[case_id]()
    previous = ql.Settings.instance().evaluationDate
    try:
        instrument = build_instrument_from_request(InstrumentRequest(type="ois", params=params))
        result = PricingService().price(
            instrument=instrument,
            market_env=environment,
            model_type="analytical",
            engine_type="discounting",
        )
        legs = instrument.leg_npvs()
        # Read while the pricing evaluation date is still set; same curve as the engine.
        cashflows = irs_cashflow_rows(
            instrument.last_built, environment.discount_curves[instrument.currency()]
        )
    finally:
        ql.Settings.instance().evaluationDate = previous
    return TradeReport(
        case_id=case_id,
        trade_id=str(instrument.trade_id()),
        currency=instrument.currency(),
        optima={
            "fixed_leg_npv": legs["fixed"],
            "floating_leg_npv": legs["floating"],
            "npv": result.npv,
        },
        bloomberg=bloomberg,
        cashflows=cashflows,
        bloomberg_cashflows=_bloomberg_cashflows(sections),
        tags=KNOWN_DIFFERENCE_TAGS.get(case_id, {}),
    )


def run() -> List[TradeReport]:
    environment = usd_sofr_environment()
    return [price_case(case_id, environment) for case_id in CASES]


def _format_cashflows(report: TradeReport) -> List[str]:
    header = (
        f"  {'Leg':<9}{'Per':>3} {'Acc start':>10} {'Acc end':>10} {'Payment':>10}"
        f"{'Notional':>13}{'DCF':>9}{'Rate %':>10}{'Sprd bp':>8}"
        f"{'Amount':>13}{'DF':>11}{'PV':>13}"
        f"{'BBG amount':>13}{'BBG DF':>10}{'BBG PV':>12}"
        f"{'d Amount':>10}{'d DF':>10}{'d PV':>9}  Tag"
    )
    lines = ["  Cashflows (Optima vs Bloomberg; d = Optima - Bloomberg)", header]
    for row in report.cashflows:
        key = (row.leg, row.period)
        bbg = report.bloomberg_cashflows.get(key)
        spread = "" if row.spread is None else f"{row.spread * 1e4:.1f}"
        line = (
            f"  {row.leg:<9}{row.period:>3} {row.accrual_start.isoformat():>10} "
            f"{row.accrual_end.isoformat():>10} {row.payment_date.isoformat():>10}"
            f"{row.notional:>13,.0f}{row.day_count_fraction:>9.6f}{row.rate * 100:>10.6f}"
            f"{spread:>8}{row.amount:>13,.2f}{row.discount_factor:>11.7f}"
            f"{row.present_value:>13,.2f}"
        )
        if bbg is not None:
            line += (
                f"{bbg.amount:>13,.2f}{bbg.discount_factor:>10.6f}{bbg.present_value:>12,.2f}"
                f"{row.amount - bbg.amount:>+10.2f}"
                f"{row.discount_factor - bbg.discount_factor:>+10.1e}"
                f"{row.present_value - bbg.present_value:>+9.2f}"
            )
        line += f"  {report.tags.get(key, '')}"
        lines.append(line.rstrip())
    return lines


def format_report(reports: List[TradeReport]) -> str:
    labels = {
        "fixed_leg_npv": "Fixed-leg NPV",
        "floating_leg_npv": "Floating-leg NPV",
        "npv": "Total NPV",
    }
    lines = [
        f"Fresh IRS pricing via PricingService (valuation {VALUATION_DATE.isoformat()}, "
        f"QuantLib {ql.__version__})",
        "",
    ]
    for report in reports:
        lines.append(f"{report.case_id}  trade {report.trade_id}  currency {report.currency}")
        lines.append(f"  {'':18}{'Optima':>18}{'Bloomberg':>16}{'Optima - BBG':>16}")
        for metric in METRICS:
            lines.append(
                f"  {labels[metric]:<18}{report.optima[metric]:>18,.6f}"
                f"{report.bloomberg[metric]:>16,.2f}{report.differences[metric]:>+16,.4f}"
            )
        if report.cashflows:
            lines.append("")
            lines.extend(_format_cashflows(report))
        lines.append("")
    lines.append(
        "Known differences: docs/IRS_OPEN_ITEMS.md (TC1: OI-1; TC3: OI-1, OI-7). "
        "Pay-leg amounts and PVs are negative."
    )
    return "\n".join(lines)


def main() -> int:
    print(format_report(run()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
