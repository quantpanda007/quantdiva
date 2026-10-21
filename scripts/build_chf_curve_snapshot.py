"""Derive the CHF market snapshot (Bloomberg curve 234, CHF OIS SARON, 31-Mar-2026)
from the supplied discount factors.

Run from the project root; the document is printed to stdout:

    python -m scripts.build_chf_curve_snapshot > market_data/2026-03-31/CHF/chf_saron_2026-03-31.json

Inputs: ``market_data/2026-03-31/CHF/market_data.json`` (dated Market Rate and
Discount Factor rows). Only the discount factors are used. Each row is mapped to
its Bloomberg tenor from the display-date offset (7/14 days -> 1W/2W, 30n days ->
nM, 540 days -> 18M, 365n days -> nY), the term list shown on the SWPM Curves tab
for curve 234. Pillars are spot (2 Swiss business days) + tenor, Modified
Following, and zero rates are ACT/365F continuously compounded from the curve
date (SWPM Curves tab and Bloomberg Help Desk, 9-Oct-2026). Each zero rate is
-ln(DF) / t(pillar), so the curve reproduces every supplied DF; the DF is kept
in the observation as the builder's consistency check.

Bloomberg-derived: keep local (OI-6).
"""

from __future__ import annotations

import json
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict

import QuantLib as ql

from market.curves.irs_zero_curve import ZeroCurveConventions, derive_pillar_dates

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "market_data" / "2026-03-31" / "CHF" / "market_data.json"
CURVE_ID = "CHF-SARON-234"
CONVENTIONS = {
    "calendar": "CH-SARON",
    "spot_lag_days": 2,
    "business_day_convention": "modified_following",
    "end_of_month": False,
    "day_count": "ACT/365F",
    "compounding": "continuous",
    "interpolation": "linear_zero",
    "front_extrapolation": "flat_first_zero",
    "allow_extrapolation": False,
    "discount_factor_check_tolerance": 1e-6,
}


def tenor_for_offset(days: int) -> str:
    """Bloomberg tenor for a display-date offset; anything unrecognised is rejected."""
    if days in (7, 14):
        return f"{days // 7}W"
    if days == 540:
        return "18M"
    if days % 30 == 0 and 1 <= days // 30 <= 12:
        return f"{days // 30}M"
    if days % 365 == 0 and days // 365 >= 2:
        return f"{days // 365}Y"
    raise ValueError(f"no Bloomberg tenor for a display offset of {days} days")


def build_document() -> Dict[str, Any]:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    reference = date.fromisoformat(source["reference_date"])
    rows = source["observations"]
    tenors = tuple(tenor_for_offset((date.fromisoformat(r["date"]) - reference).days) for r in rows)
    conventions = ZeroCurveConventions(
        calendar=ql.Switzerland(),
        spot_lag_days=CONVENTIONS["spot_lag_days"],
        business_day_convention=ql.ModifiedFollowing,
        end_of_month=CONVENTIONS["end_of_month"],
        day_counter=ql.Actual365Fixed(),
        compounding=ql.Continuous,
        interpolation=CONVENTIONS["interpolation"],
        front_extrapolation=CONVENTIONS["front_extrapolation"],
        allow_extrapolation=CONVENTIONS["allow_extrapolation"],
        discount_factor_tolerance=CONVENTIONS["discount_factor_check_tolerance"],
    )
    _, pillars = derive_pillar_dates(reference, tenors, conventions)
    observations = []
    for tenor, pillar, row in zip(tenors, pillars, rows):
        t = (pillar - reference).days / 365.0
        zero = -math.log(row["discount_factor"]) / t
        observations.append({
            "tenor": tenor,
            "zero_rate": float(f"{zero:.12g}"),
            "discount_factor": row["discount_factor"],
        })
    return {
        "schema_version": 1,
        "valuation_date": reference.isoformat(),
        "provenance": (
            "Bloomberg curve 234 (CHF OIS SARON, Mid, Piecewise Linear (Cont)), 31-Mar-2026. "
            "Zero rates derived from the discount factors in "
            "market_data/2026-03-31/CHF/market_data.json by scripts/build_chf_curve_snapshot.py "
            "(pillar = spot + tenor; zero = -ln(DF)/t, ACT/365F continuous). "
            "Bloomberg-derived: keep local (OI-6)."
        ),
        "curves": {
            CURVE_ID: {
                "currency": "CHF",
                "benchmark": "SARON",
                "reference_date": reference.isoformat(),
                "conventions": CONVENTIONS,
                "observations": observations,
            }
        },
        "assignments": {"CHF": {"discount": CURVE_ID, "forecast": CURVE_ID}},
    }


def to_text(document: Dict[str, Any]) -> str:
    return json.dumps(document, indent=2) + "\n"


def main() -> int:
    sys.stdout.write(to_text(build_document()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
