"""Internal expected-output suite for the ten IRS test cases (TC1-TC10).

Each case is built and priced with the production engine (``price_irs_engine``: trade ->
resolved market files -> ``FreshOISInstrument`` -> ``PricingService`` /
``ql.DiscountingSwapEngine`` -> production cashflow extraction). The result is compared with
the expected outputs stored in ``tests/fixtures/irs_expected_outputs/<case>.json``.

PROVENANCE - read this before relying on a PASS
-----------------------------------------------
The expected outputs are an **Optima regression baseline**: they were captured from this
same production implementation at the ``validation_phase1`` checkpoint (``capture``
command). They are NOT independent expected results and NOT Bloomberg values. A PASS
means "the implementation still reproduces its validation_phase1 outputs within
tolerance". It does not mean the price is correct. Correctness against Bloomberg is
assessed separately by ``scripts/irs_reconciliation_report.py``, which is unchanged.
This suite never reads the Bloomberg fixtures.

Statuses (from actual execution and assertions):

* PASS    - priced, and every expected field present is within tolerance;
* FAIL    - priced, but at least one field differs beyond tolerance, the cashflow rows
            differ, or an input file changed since the baseline was captured;
* BLOCKED - no expected-output file for the case, or it holds no expected values;
* ERROR   - building or pricing the trade raised an exception.

Tolerances (``TOLERANCES``) and why:
The comparison checks reproducibility of a deterministic calculation, not agreement
with an external source. The largest platform difference observed for this code was
1.7e-10 in an NPV (Windows vs Linux, 14-Oct-2026), and about 4e-17 in a bootstrapped
zero rate. The tolerances leave several orders of magnitude of headroom over that, while
staying far below anything visible in a report.

* currency amounts (NPV, leg NPVs, cashflow amounts and PVs): 1e-6 absolute, in the
  trade's currency units. That is ~4 orders above the observed 1.7e-10 and 0.0001% of the
  smallest displayed unit (0.01).
* rates (decimal), discount factors, day-count fractions: 1e-12 absolute (1e-8 bp for a
  rate).
* notionals: 1e-9 absolute (they are inputs).
* dates, leg, side, period numbers and the set of rows: exact.

Commands (from the quantlib-pricing root):

    python -m scripts.irs_expected_output_suite run [--output-dir DIR]
    python -m scripts.irs_expected_output_suite capture [--case TC1 ...] [--overwrite --reason R]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import QuantLib as ql

import price_irs_engine as engine

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "irs"
EXPECTED_DIR = ROOT / "tests" / "fixtures" / "irs_expected_outputs"
CASES = tuple(f"TC{i}" for i in range(1, 11))
SCHEMA_VERSION = 1
CHECKPOINT = "validation_phase1"

TOLERANCES = {
    "currency": 1e-6,
    "rate": 1e-12,
    "discount_factor": 1e-12,
    "day_count_fraction": 1e-12,
    "notional": 1e-9,
}
CASHFLOW_KEY = ("leg", "period", "payment_date")
CASHFLOW_EXACT = ("side", "accrual_start", "accrual_end")
CASHFLOW_NUMERIC = {
    "notional": "notional", "day_count_fraction": "day_count_fraction", "rate": "rate",
    "amount": "currency", "discount_factor": "discount_factor", "present_value": "currency",
}
TOP_NUMERIC = ("npv", "fixed_leg_npv", "floating_leg_npv")

PROVENANCE_STATEMENT = (
    "Optima regression baseline: captured from Optima's own production pricing "
    "(price_irs_engine -> PricingService -> ql.DiscountingSwapEngine) at the "
    "validation_phase1 checkpoint. NOT independent expected results and NOT Bloomberg "
    "values. A match shows the implementation still reproduces these outputs; it does not "
    "show they are correct. Bloomberg comparison: scripts/irs_reconciliation_report.py."
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _rel(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def trade_path(case: str) -> Path:
    return EXAMPLES / f"{case.lower()}_trade.json"


def expected_path(case: str, directory: Path = EXPECTED_DIR) -> Path:
    return Path(directory) / f"{case}.json"


# --- pricing (production engine, unchanged) -------------------------------------------------


def price_case(case: str, market_dir: Path = EXAMPLES) -> Dict[str, Any]:
    """Price one case through the production engine; outputs as plain JSON values."""
    trade_doc = engine.load(trade_path(case))
    selection = engine.resolve_market_files(trade_doc, market_dir)
    instrument, currency, result, legs, rows, settled = engine.price(
        trade_doc, engine.merge_market(list(selection.files)))
    term = trade_doc["params"]["floating_leg"].get("term_rate") or {}
    return {
        "trade_id": str(instrument.trade_id()),
        "currency": currency,
        "valuation_date": instrument.trade.valuation_date.isoformat(),
        "observation_method": term.get("observation_dates"),
        "inputs": {
            "trade_file": {"path": _rel(trade_path(case)), "sha256": _sha256(trade_path(case))},
            "market_files": [{"path": _rel(p), "sha256": _sha256(p)} for p in selection.files],
        },
        "outputs": {
            "npv": result.npv,
            "fixed_leg_npv": legs["fixed"],
            "floating_leg_npv": legs["floating"],
            "cashflows": [
                {"leg": r.leg, "side": r.side, "period": r.period,
                 "accrual_start": r.accrual_start.isoformat(),
                 "accrual_end": r.accrual_end.isoformat(),
                 "payment_date": r.payment_date.isoformat(),
                 "notional": r.notional, "day_count_fraction": r.day_count_fraction,
                 "rate": r.rate, "amount": r.amount, "discount_factor": r.discount_factor,
                 "present_value": r.present_value}
                for r in rows
            ],
            "settled": [
                {"leg": s.leg, "side": s.side, "period": s.period,
                 "payment_date": s.payment_date.isoformat()}
                for s in settled
            ],
        },
    }


# --- capture ----------------------------------------------------------------------------------


def _environment() -> Dict[str, str]:
    return {"python": platform.python_version(), "quantlib": ql.__version__,
            "platform": platform.platform()}


def capture(cases=CASES, directory: Path = EXPECTED_DIR, overwrite: bool = False,
            reason: Optional[str] = None) -> List[Path]:
    """Write the baseline files. Never replaces an existing file unless ``overwrite`` is
    set with a ``reason``, which is recorded in the file."""
    if overwrite and not (reason and reason.strip()):
        raise ValueError("overwriting a baseline requires a reason")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    now = datetime.now(timezone(timedelta(hours=5, minutes=30))).isoformat(timespec="seconds")
    for case in cases:
        path = expected_path(case, directory)
        if path.exists() and not overwrite:
            raise FileExistsError(f"{path} exists; use --overwrite --reason to replace it")
        priced = price_case(case)
        doc = {
            "schema_version": SCHEMA_VERSION,
            "case_id": case,
            "trade_id": priced["trade_id"],
            "currency": priced["currency"],
            "valuation_date": priced["valuation_date"],
            "provenance": {
                "kind": "optima_regression_baseline",
                "independent": False,
                "source": "Optima production pricing (same implementation under test)",
                "statement": PROVENANCE_STATEMENT,
                "checkpoint": CHECKPOINT,
                "captured_at": now,
                "captured_by": "scripts/irs_expected_output_suite.py capture",
                "environment": _environment(),
                "observation_method": priced["observation_method"],
                "inputs": priced["inputs"],
                "recapture_reason": reason if overwrite else None,
            },
            "expected": priced["outputs"],
        }
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        written.append(path)
    return written


# --- comparison -------------------------------------------------------------------------------


@dataclass
class CaseResult:
    case_id: str
    status: str
    fields_compared: List[str] = field(default_factory=list)
    checks: int = 0
    failures: List[str] = field(default_factory=list)
    max_abs_diff: Dict[str, float] = field(default_factory=dict)
    detail: str = ""
    npv: Optional[float] = None
    expected_npv: Optional[float] = None


def _within(actual: float, expected: float, kind: str) -> bool:
    return abs(float(actual) - float(expected)) <= TOLERANCES[kind]


def _track(result: CaseResult, name: str, diff: float) -> None:
    result.max_abs_diff[name] = max(result.max_abs_diff.get(name, 0.0), diff)


def compare(actual: Dict[str, Any], expected: Dict[str, Any], result: CaseResult) -> None:
    """Compare every expected field that is present; record failures on ``result``."""
    for name in TOP_NUMERIC:
        if name not in expected:
            continue
        result.fields_compared.append(name)
        result.checks += 1
        diff = abs(actual[name] - expected[name])
        _track(result, name, diff)
        if diff > TOLERANCES["currency"]:
            result.failures.append(f"{name}: actual {actual[name]!r} expected "
                                   f"{expected[name]!r} (|diff| {diff:.3e} > "
                                   f"{TOLERANCES['currency']:g})")
    if "cashflows" in expected:
        result.fields_compared.append("cashflows")
        exp_rows = {tuple(r[k] for k in CASHFLOW_KEY): r for r in expected["cashflows"]}
        act_rows = {tuple(r[k] for k in CASHFLOW_KEY): r for r in actual["cashflows"]}
        for key in sorted(set(exp_rows) - set(act_rows)):
            result.failures.append(f"cashflow {key}: expected but not produced")
        for key in sorted(set(act_rows) - set(exp_rows)):
            result.failures.append(f"cashflow {key}: produced but not expected")
        for key in sorted(set(exp_rows) & set(act_rows)):
            exp, act = exp_rows[key], act_rows[key]
            for name in CASHFLOW_EXACT:
                if name in exp:
                    result.checks += 1
                    if act[name] != exp[name]:
                        result.failures.append(f"cashflow {key} {name}: actual {act[name]!r} "
                                               f"expected {exp[name]!r}")
            for name, kind in CASHFLOW_NUMERIC.items():
                if name not in exp:
                    continue
                result.checks += 1
                diff = abs(act[name] - exp[name])
                _track(result, f"cashflow.{name}", diff)
                if diff > TOLERANCES[kind]:
                    result.failures.append(f"cashflow {key} {name}: actual {act[name]!r} "
                                           f"expected {exp[name]!r} (|diff| {diff:.3e} > "
                                           f"{TOLERANCES[kind]:g})")
    if "settled" in expected:
        result.fields_compared.append("settled")
        result.checks += 1
        if actual["settled"] != expected["settled"]:
            result.failures.append(f"settled cashflows: actual {actual['settled']!r} expected "
                                   f"{expected['settled']!r}")


def run_case(case: str, directory: Path = EXPECTED_DIR, market_dir: Path = EXAMPLES,
             pricer=None) -> CaseResult:
    path = expected_path(case, directory)
    if not path.exists():
        return CaseResult(case, "BLOCKED", detail=f"no expected-output file {_rel(path)}")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return CaseResult(case, "ERROR", detail=f"cannot read {_rel(path)}: {exc}")
    expected = doc.get("expected") or {}
    if not any(k in expected for k in (*TOP_NUMERIC, "cashflows", "settled")):
        return CaseResult(case, "BLOCKED", detail=f"{_rel(path)} holds no expected values")
    try:
        priced = pricer(case) if pricer is not None else price_case(case, market_dir)
    except Exception as exc:  # noqa: BLE001 - reported as ERROR, never hidden
        return CaseResult(case, "ERROR", detail=f"{type(exc).__name__}: {exc}",
                          expected_npv=expected.get("npv"))
    result = CaseResult(case, "PASS", npv=priced["outputs"]["npv"],
                        expected_npv=expected.get("npv"))
    captured = (doc.get("provenance") or {}).get("inputs")
    if captured is not None and captured != priced["inputs"]:
        result.failures.append(
            "input files differ from those used at capture: "
            f"captured {captured!r}, now {priced['inputs']!r}")
    compare(priced["outputs"], expected, result)
    if result.failures:
        result.status = "FAIL"
    return result


def run(cases=CASES, directory: Path = EXPECTED_DIR) -> List[CaseResult]:
    return [run_case(case, directory) for case in cases]


# --- reporting --------------------------------------------------------------------------------


def to_table(results: List[CaseResult]) -> str:
    lines = [
        "Internal expected-output suite (Optima regression baseline, captured at "
        f"{CHECKPOINT}; NOT independent validation, NOT Bloomberg)",
        f"{'Case':5} {'Status':8} {'Checks':>6} {'NPV':>18} {'Max |diff| NPV':>15}  "
        "Fields compared / detail",
    ]
    for r in results:
        fields = ", ".join(r.fields_compared) or "-"
        npv = f"{r.npv:,.6f}" if r.npv is not None else "-"
        diff = r.max_abs_diff.get("npv")
        diff_s = f"{diff:.2e}" if diff is not None else "-"
        info = fields if r.status == "PASS" else (r.detail or "; ".join(r.failures[:3]))
        lines.append(f"{r.case_id:5} {r.status:8} {r.checks:>6} {npv:>18} {diff_s:>15}  {info}")
    counts = {s: sum(r.status == s for r in results) for s in ("PASS", "FAIL", "BLOCKED", "ERROR")}
    lines.append(" | ".join(f"{k} {v}" for k, v in counts.items()))
    tol = ", ".join(f"{k} {v:g}" for k, v in TOLERANCES.items())
    lines.append(f"Tolerances (absolute): {tol}; dates, legs, sides, periods and row sets exact.")
    return "\n".join(lines)


def write_results(results: List[CaseResult], directory: Path) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "expected_output_results.json").write_text(json.dumps({
        "suite": "irs_expected_output_suite",
        "baseline": {"kind": "optima_regression_baseline", "independent": False,
                     "checkpoint": CHECKPOINT, "statement": PROVENANCE_STATEMENT},
        "tolerances": TOLERANCES,
        "environment": _environment(),
        "results": [asdict(r) for r in results],
    }, indent=2) + "\n", encoding="utf-8")
    (directory / "expected_output_results.md").write_text(
        "```\n" + to_table(results) + "\n```\n", encoding="utf-8")
    return directory


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="IRS internal expected-output suite.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_run = sub.add_parser("run", help="price the cases and compare with the baseline")
    p_run.add_argument("--case", nargs="+", choices=CASES, default=list(CASES))
    p_run.add_argument("--output-dir", help="new folder for results JSON and Markdown")
    p_run.add_argument("--expected-dir", default=str(EXPECTED_DIR),
                       help="folder of expected-output files (default: the baseline)")
    p_cap = sub.add_parser("capture", help="write the Optima regression baseline")
    p_cap.add_argument("--case", nargs="+", choices=CASES, default=list(CASES))
    p_cap.add_argument("--overwrite", action="store_true")
    p_cap.add_argument("--reason", help="required with --overwrite; recorded in the file")
    args = parser.parse_args(argv)
    if args.command == "capture":
        try:
            for path in capture(args.case, overwrite=args.overwrite, reason=args.reason):
                print(f"wrote {_rel(path)}")
        except (FileExistsError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        return 0
    results = run(args.case, Path(args.expected_dir))
    print(to_table(results))
    if args.output_dir:
        print(f"\nResults written to {write_results(results, Path(args.output_dir))}")
    return 0 if all(r.status == "PASS" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
