"""Reproduce the USD SOFR prepared snapshot from its raw zero-rate source, byte for byte.

    python -m scripts.build_usd_curve_snapshot                    # check (default): compare
    python -m scripts.build_usd_curve_snapshot --output <new.json>  # write to a NEW file

Source: ``market_data/2026-03-31/USD/2026-03-31-USD-SOFR-zero.json`` (Bloomberg
490-USDSOFR export, "Zero Rate" column supplied by the SME, with the discount factors
and the inferred tenors). Target: ``market_data/2026-03-31/USD/usd_sofr_2026-03-31.json``.

What is derived from the source, per row (20 rows, in order):
    tenor           = inferred_tenor
    zero_rate       = zero_rate_percent / 100   (decimal arithmetic, then float)
    discount_factor = discount_factor           (kept for the 1e-6 consistency check)
plus the reference date, currency and benchmark (checked against the constants below).

What is NOT derived from the source and is fixed in this builder as recorded when the
snapshot was created (Oct 2026): the curve id, the conventions block (calendar US-SOFR,
spot lag 2, Modified Following, no end-of-month, ACT/365F continuous zero rates,
linear-zero interpolation, flat first zero, no extrapolation, DF check tolerance 1e-6;
these restate the source file's provenance/conventions text in engine terms), the
assignment (USD discount and forecast on this curve) and the provenance text, kept
verbatim, including the source path it named at the time.

This is a reproduction of the existing snapshot, not a curve methodology: the zero rates
are Bloomberg's, not an Optima bootstrap from the par rates in ``market_data.json``
(building the USD curve from par rates is a separate open item, OI-1). The builder never
overwrites the canonical snapshot: ``--output`` refuses an existing file.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from market.market_data_layout import currency_dir, curve_snapshot_path  # noqa: E402

VALUATION = "2026-03-31"
SOURCE = currency_dir(VALUATION, "USD") / "2026-03-31-USD-SOFR-zero.json"
TARGET = curve_snapshot_path(VALUATION, "USD", "SOFR")
CURVE_ID = "USD-SOFR-490"
EXPECTED_ROWS = 20

# Recorded at snapshot creation; not derived from the source (see module docstring).
PROVENANCE = (
    "Bloomberg 490-USDSOFR curve export, 31-Mar-2026 (zero rates and discount factors), "
    "converted from tests/fixtures/bloomberg_irs/curves/2026-03-31-USD-SOFR-zero.json: "
    "zero_rate = Zero Rate % / 100, tenors as inferred there. Bloomberg-derived: keep local "
    "(OI-6). Known curve differences vs Bloomberg: OI-1, OI-7."
)
CONVENTIONS: Dict[str, Any] = {
    "calendar": "US-SOFR",
    "spot_lag_days": 2,
    "business_day_convention": "modified_following",
    "end_of_month": False,
    "day_count": "ACT/365F",
    "compounding": "continuous",
    "interpolation": "linear_zero",
    "front_extrapolation": "flat_first_zero",
    "allow_extrapolation": False,
    "discount_factor_check_tolerance": 1e-06,
}


class SourceError(ValueError):
    pass


def build_document(source: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in (("reference_date", VALUATION), ("currency", "USD"),
                       ("benchmark", "SOFR")):
        if source.get(key) != value:
            raise SourceError(f"source {key} is {source.get(key)!r}, expected {value!r}")
    rows = source.get("observations")
    if not isinstance(rows, list) or len(rows) != EXPECTED_ROWS:
        raise SourceError(f"source must have {EXPECTED_ROWS} observations")
    observations = []
    for index, row in enumerate(rows, start=1):
        try:
            observations.append({
                "tenor": row["inferred_tenor"],
                "zero_rate": float(Decimal(repr(row["zero_rate_percent"])) / 100),
                "discount_factor": row["discount_factor"],
            })
        except (KeyError, TypeError, ArithmeticError) as exc:
            raise SourceError(f"source observation {index}: {exc!r}") from exc
    return {
        "schema_version": 1,
        "valuation_date": VALUATION,
        "provenance": PROVENANCE,
        "curves": {CURVE_ID: {
            "currency": "USD",
            "benchmark": "SOFR",
            "reference_date": VALUATION,
            "conventions": dict(CONVENTIONS),
            "observations": observations,
        }},
        "assignments": {"USD": {"discount": CURVE_ID, "forecast": CURVE_ID}},
    }


def to_bytes(document: Dict[str, Any]) -> bytes:
    return (json.dumps(document, indent=2) + "\n").encode("utf-8")


def build(source_path: Path = SOURCE) -> bytes:
    return to_bytes(build_document(json.loads(Path(source_path).read_text(encoding="utf-8"))))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Reproduce the USD SOFR prepared snapshot.")
    parser.add_argument("--source", default=SOURCE, help="zero-rate source file")
    parser.add_argument("--target", default=TARGET, help="snapshot to compare with (check)")
    parser.add_argument("--output", default=None,
                        help="write the reproduction to this NEW file instead of checking")
    args = parser.parse_args(argv)
    try:
        generated = build(Path(args.source))
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.output:
        out = Path(args.output)
        if out.exists() or out.resolve() == TARGET.resolve():
            print(f"ERROR: {out} exists; the builder never overwrites a snapshot",
                  file=sys.stderr)
            return 2
        out.write_bytes(generated)
        print(f"wrote {out}")
        return 0
    target = Path(args.target)
    stored = target.read_bytes() if target.exists() else b""
    if stored == generated:
        print(f"{target}: byte-identical to the reproduction from {Path(args.source).name}")
        return 0
    diff = difflib.unified_diff(stored.decode("utf-8", "replace").splitlines(),
                                generated.decode("utf-8").splitlines(), "stored", "generated",
                                lineterm="", n=1)
    print(f"{target}: DIFFERS from the reproduction", file=sys.stderr)
    for line in list(diff)[:20]:
        print(line, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
