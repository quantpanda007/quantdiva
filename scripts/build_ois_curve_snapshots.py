"""Build the INR and JPY curve snapshots by bootstrapping OIS par rates in QuantLib.

Inputs: ``market_data/2026-03-31/<CCY>/market_data.json`` (Bloomberg curve exports:
date, Market Rate, Discount Factor). ``Market Rate`` is the OIS par rate (established).
Each row is an OIS of the stated tenor; the curve is bootstrapped with
``ql.OISRateHelper`` and written as zero rates (ACT/365F, continuous) at the bootstrap
nodes, which equal the production pillar dates (spot + tenor, Modified Following), so
``build_zero_curve`` (linear zero, flat first zero) rebuilds exactly the bootstrapped
curve.

Conventions (evidence, 14-Oct-2026; docs/IRS_OPEN_ITEMS.md OI-15, OI-16):

* INR (MIBOR OIS): settlement T+0 on ql.India, tenors up to 1Y a single payment,
  longer tenors semiannual, ACT/365F. Reproduces all ten Bloomberg payment-date DFs of
  TC5/TC8/TC9 within 4.3e-7 (display precision 5e-7).
* JPY (TONA OIS): settlement T+2 on ql.Japan, tenors up to 1Y a single payment,
  longer tenors annual, ACT/365F. The row displayed at +390 days is the 15M quote
  (any other reading misses Bloomberg's TC6/TC10 DFs by 2e-4 to 5e-4; 15M reproduces
  all five within 1.0e-6); +21 days is 3W, +630 days is 21M.

The supplied ``Discount Factor`` column is NOT used: it does not reproduce Bloomberg's
trade DFs for either currency (differences up to 1.5e-3 INR, 2.7e-3 JPY), so it is
kept as a reference only and compared in the tests.

Run from the project root:

    python -m scripts.build_ois_curve_snapshots [--check]

``--check`` compares the files on disk with the generator output instead of writing
(numerically: zero rates within ``ZERO_RATE_TOLERANCE``, everything else exactly).
Bloomberg-derived output: keep local (OI-6).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

import QuantLib as ql

ROOT = Path(__file__).resolve().parents[1]
VALUATION = date(2026, 3, 31)


@dataclass(frozen=True)
class OISCurveDefinition:
    currency: str
    curve_id: str
    benchmark: str
    calendar_name: str  # Optima market-snapshot calendar name
    calendar: Callable[[], ql.Calendar]
    currency_ql: Callable[[], ql.Currency]
    settlement_days: int
    long_frequency: int  # payment frequency above 1Y
    tenors: Dict[int, str]  # display offset (days from valuation) -> tenor
    output: str
    evidence: str


def _standard_tenor(days: int) -> str:
    if days % 365 == 0:
        return f"{days // 365}Y"
    if days % 30 == 0 and days <= 360:
        return f"{days // 30}M"
    raise ValueError(f"no tenor rule for a display offset of {days} days")


DEFINITIONS = {
    "INR": OISCurveDefinition(
        currency="INR", curve_id="INR-MIBOR-OIS", benchmark="MIBOR",
        calendar_name="IN-MIBOR", calendar=ql.India, currency_ql=ql.INRCurrency,
        settlement_days=0, long_frequency=ql.Semiannual,
        tenors={}, output="market_data/2026-03-31/INR/inr_mibor_2026-03-31.json",
        evidence="reproduces Bloomberg's TC5/TC8/TC9 payment-date DFs within 4.3e-7",
    ),
    "JPY": OISCurveDefinition(
        currency="JPY", curve_id="JPY-TONA-OIS", benchmark="TONA",
        calendar_name="JP-TONA", calendar=ql.Japan, currency_ql=ql.JPYCurrency,
        settlement_days=2, long_frequency=ql.Annual,
        tenors={7: "1W", 14: "2W", 21: "3W", 390: "15M", 540: "18M", 630: "21M"},
        output="market_data/2026-03-31/JPY/jpy_tona_2026-03-31.json",
        evidence="reproduces Bloomberg's TC6/TC10 payment-date DFs within 1.0e-6 "
        "(+390-day row read as 15M)",
    ),
}


def source_rows(definition: OISCurveDefinition) -> List[Tuple[str, float, float, date]]:
    """(tenor, par rate decimal, supplied DF, display date) for every source row."""
    path = ROOT / "market_data" / VALUATION.isoformat() / definition.currency / "market_data.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for o in doc["observations"]:
        shown = date.fromisoformat(o["date"])
        days = (shown - VALUATION).days
        tenor = definition.tenors.get(days) or _standard_tenor(days)
        rows.append((tenor, o["market_rate"] / 100.0, o["discount_factor"], shown))
    return rows


def _months(period: ql.Period) -> float:
    units = {ql.Years: 12.0, ql.Months: 1.0, ql.Weeks: 12.0 / 52.0, ql.Days: 12.0 / 365.0}
    return period.length() * units[period.units()]


def bootstrap(definition: OISCurveDefinition) -> Tuple[ql.PiecewiseLinearZero, List[Any]]:
    """Bootstrap at the current evaluation date (must be the valuation date)."""
    reference = ql.Date(VALUATION.day, VALUATION.month, VALUATION.year)
    if ql.Settings.instance().evaluationDate != reference:
        raise RuntimeError("set the QuantLib evaluation date to the valuation date first")
    calendar = definition.calendar()
    index = ql.OvernightIndex(definition.benchmark, 0, definition.currency_ql(), calendar,
                              ql.Actual365Fixed())
    helpers = []
    for tenor, rate, _, _ in source_rows(definition):
        period = ql.Period(tenor)
        frequency = ql.Once if _months(period) <= 12 else definition.long_frequency
        helpers.append(ql.OISRateHelper(
            definition.settlement_days, period, ql.QuoteHandle(ql.SimpleQuote(rate)), index,
            ql.YieldTermStructureHandle(), False, 0, ql.ModifiedFollowing, frequency, calendar,
        ))
    curve = ql.PiecewiseLinearZero(reference, helpers, ql.Actual365Fixed())
    return curve, helpers


def build_document(definition: OISCurveDefinition) -> Dict[str, Any]:
    reference = ql.Date(VALUATION.day, VALUATION.month, VALUATION.year)
    previous = ql.Settings.instance().evaluationDate
    ql.Settings.instance().evaluationDate = reference
    try:
        curve, helpers = bootstrap(definition)
        observations = []
        for (tenor, rate, df, shown), helper in zip(source_rows(definition), helpers):
            pillar = helper.pillarDate()
            zero = curve.zeroRate(pillar, ql.Actual365Fixed(), ql.Continuous).rate()
            observations.append({"tenor": tenor, "zero_rate": zero})
    finally:
        ql.Settings.instance().evaluationDate = previous
    return {
        "schema_version": 1,
        "valuation_date": VALUATION.isoformat(),
        "provenance": (
            f"{definition.currency} {definition.benchmark} OIS curve bootstrapped in QuantLib "
            f"from the OIS par rates (Market Rate) in market_data/{VALUATION.isoformat()}/"
            f"{definition.currency}/market_data.json by scripts/build_ois_curve_snapshots.py: "
            f"T+{definition.settlement_days}, {definition.calendar_name}, single payment up "
            f"to 1Y, {'semiannual' if definition.long_frequency == ql.Semiannual else 'annual'}"
            f" above, ACT/365F, linear zero; {definition.evidence}. The supplied Discount "
            "Factor column is not used (it does not reproduce Bloomberg's trade DFs). "
            "Bloomberg-derived: keep local (OI-6)."
        ),
        "curves": {
            definition.curve_id: {
                "currency": definition.currency,
                "benchmark": definition.benchmark,
                "reference_date": VALUATION.isoformat(),
                "conventions": {
                    "calendar": definition.calendar_name,
                    "spot_lag_days": definition.settlement_days,
                    "business_day_convention": "modified_following",
                    "end_of_month": False,
                    "day_count": "ACT/365F",
                    "compounding": "continuous",
                    "interpolation": "linear_zero",
                    "front_extrapolation": "flat_first_zero",
                    "allow_extrapolation": False,
                    "discount_factor_check_tolerance": 1e-06,
                },
                "observations": observations,
            }
        },
        "assignments": {
            definition.currency: {"discount": definition.curve_id,
                                  "forecast": definition.curve_id}
        },
    }


def to_text(document: Dict[str, Any]) -> str:
    return json.dumps(document, indent=2) + "\n"


# Bootstrapped zero rates can differ in the last few binary digits between platforms
# (observed: 4e-17 on one INR node, Windows vs Linux). The committed snapshot is compared
# with the generator output numerically at this tolerance; everything else must be equal.
ZERO_RATE_TOLERANCE = 1e-12


def same_document(stored: Any, generated: Any, tolerance: float = ZERO_RATE_TOLERANCE) -> bool:
    """True if two snapshot documents are equal, floats within ``tolerance``."""
    if isinstance(stored, dict) and isinstance(generated, dict):
        return stored.keys() == generated.keys() and all(
            same_document(stored[k], generated[k], tolerance) for k in stored)
    if isinstance(stored, list) and isinstance(generated, list):
        return len(stored) == len(generated) and all(
            same_document(a, b, tolerance) for a, b in zip(stored, generated))
    if isinstance(stored, float) and isinstance(generated, float):
        return abs(stored - generated) <= tolerance
    return type(stored) is type(generated) and stored == generated


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Bootstrap the INR and JPY OIS snapshots.")
    parser.add_argument("--check", action="store_true", help="compare instead of writing")
    args = parser.parse_args(argv)
    status = 0
    for definition in DEFINITIONS.values():
        document = build_document(definition)
        text = to_text(document)
        path = ROOT / definition.output
        if args.check:
            same = path.exists() and same_document(
                json.loads(path.read_text(encoding="utf-8")), document)
            print(f"{definition.output}: {'up to date' if same else 'DIFFERS'}")
            status |= 0 if same else 1
        else:
            path.write_text(text, encoding="utf-8")
            print(f"wrote {definition.output}")
    return status


if __name__ == "__main__":
    sys.exit(main())
