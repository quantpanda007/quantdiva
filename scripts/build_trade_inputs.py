"""Generate canonical trade inputs (``examples/irs/<case>_trade.json``) for TC2, TC5,
TC6, TC8, TC9 and TC10 from the Bloomberg *source* trade terms
(``tests/fixtures/bloomberg_irs/source``). Only contractual terms are read: dates,
notionals, rates, spreads, conventions and reset dates. No Bloomberg output (coupon,
payment, discount factor, PV, reset rate) is used. Historical fixings are market data
(``examples/irs/fixings_2026-03-31.json``), not trade inputs.

Case notes (evidence: docs/IRS_OPEN_ITEMS.md OI-11, OI-15, OI-16):

* TC2 (CHF SF0006M): notional basis 20,000 (OI-11, settled); the schedule balances in
  the source are 1,000x and are scaled. One reset per quarterly period, at the source
  reset date. SARON observation dates: ``TC2_OBSERVATION_DATES`` (OI-17) - Method A
  (contractual accrual dates, no shift; provisional default) or Method B (reset date
  + 1 EN business day starts the 6M IBOR period, 2-day shift; reproduces Bloomberg's
  effective reset dates for P2-P8, P1 differs by one day).
* TC5 (INR IRSWOF): annual payments with semiannual resets, flat compounding. The
  sub-reset period starts 6M after each period start (Forward EOM roll on the RB
  calendar) and fixes 1 RB business day before: 31-Dec-2026 / 30-Dec-2026, which is the
  effective reset date Bloomberg shows.
* TC8, TC9 (INR IRSWOF): one reset per payment period at the source reset date (TC9's
  quarterly periods share semiannual resets).
* TC6, TC10 (JPY TONA overnight): daily compounding in arrears; lookback and rate
  cutoff from the source (cutoff is kept as contractual metadata, OI-2).

Run from the project root: ``python -m scripts.build_trade_inputs [--check]``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

import QuantLib as ql

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tests" / "fixtures" / "bloomberg_irs" / "source"
VALUATION = "2026-03-31"
CASES = ("TC2", "TC5", "TC6", "TC8", "TC9", "TC10")
TC2_NOTIONAL_SCALE = 1 / 1000  # OI-11: analysis notional 20,000 vs source 20,000,000
# OI-17: TC2's SARON observation dates. "contractual_accrual" (Method A) is the
# PROVISIONAL operational default (user decision 14-Oct-2026, not Bloomberg- or
# SME-confirmed); "reset_date_fallback" (Method B) restores the previous behaviour.
TC2_OBSERVATION_DATES = "contractual_accrual"

_FREQ = {"Annual": "annual", "SemiAnnual": "semiannual", "Quarterly": "quarterly"}
_DC = {"ACT/360": "ACT/360", "ACT/365": "ACT/365", "30/360": "30/360"}
_CAL = {"RB": ql.India, "EN": ql.UnitedKingdom, "SZ": ql.Switzerland, "JN": ql.Japan}


def _read(case: str) -> Dict[str, Any]:
    return json.loads((SOURCE / f"{case}.json").read_text(encoding="utf-8"))


def _adjustment(calendar: str) -> Dict[str, str]:
    return {"calendar": calendar, "business_day_convention": "modified_following"}


def _periods(rows: List[Dict[str, Any]], scale: float = 1.0) -> List[Dict[str, Any]]:
    return [{"accrual_start": r["accrual_start"], "accrual_end": r["accrual_end"],
             "payment_date": r["pay_date"], "notional": _num(r["balance"] * scale)}
            for r in rows]


def _num(value: float):
    return int(value) if float(value).is_integer() else round(float(value), 2)


def _iso(d: ql.Date) -> str:
    return date(d.year(), d.month(), d.dayOfMonth()).isoformat()


def _ql(s: str) -> ql.Date:
    y, m, d = map(int, s.split("-"))
    return ql.Date(d, m, y)


def _document(params: Dict[str, Any]) -> Dict[str, Any]:
    return {"schema_version": 1, "instrument_type": "ois", "params": params}


def _fixed(leg: Dict[str, Any], rows, calendar: str, scale: float = 1.0) -> Dict[str, Any]:
    return {
        "day_count": _DC[leg["day_count"]],
        "payment_frequency": _FREQ[leg["pay_frequency"]],
        "fixed_rate": leg["coupon"] / 100,
        "accrual_date_adjustment": _adjustment(calendar),
        "periods": _periods(rows, scale),
    }


def _term_floating(benchmark: str, tenor: str, leg: Dict[str, Any], periods, calendar: str,
                   fixing_calendar: str, fixing_days: int, compounding: str,
                   observation_dates: str = "") -> Dict[str, Any]:
    term_rate = {"compounding": compounding, "fixing_calendar": fixing_calendar,
                 "fixing_days": fixing_days}
    if observation_dates:
        term_rate["observation_dates"] = observation_dates
    return {
        "day_count": _DC[leg["day_count"]],
        "payment_frequency": _FREQ[leg["pay_frequency"]],
        "benchmark": benchmark,
        "benchmark_tenor": tenor,
        "spread": leg["spread_bp"] / 10000,
        "leverage": 1.0,
        "reset_frequency": _FREQ[leg["reset_frequency"]],
        "accrual_date_adjustment": _adjustment(calendar),
        "term_rate": term_rate,
        "periods": periods,
    }


def _single_reset_periods(rows, scale: float = 1.0) -> List[Dict[str, Any]]:
    return [dict(p, resets=[{"reset_date": r["reset_date"], "start": r["accrual_start"],
                             "end": r["accrual_end"]}])
            for p, r in zip(_periods(rows, scale), rows)]


def _top(trade_id, currency, effective, maturity, fixed, floating) -> Dict[str, Any]:
    return {"trade_id": trade_id, "currency": currency, "valuation_date": VALUATION,
            "effective_date": effective, "maturity_date": maturity, "fixed_leg_side": "pay",
            "fixed_leg": fixed, "floating_leg": floating}


def tc2() -> Dict[str, Any]:
    s = _read("TC2")
    t, fx, fl = s["trade"], s["leg_1"], s["leg_2"]
    floating_leg = {"day_count": fl["day_count"], "pay_frequency": fl["pay_frequency"],
                    "spread_bp": fl["spread"], "reset_frequency": fl["reset_frequency"]}
    periods = _single_reset_periods(fl["amortization"], TC2_NOTIONAL_SCALE)
    return _document(_top(
        t["swap_id"], t["currency"], t["effective_date"], t["maturity_date"],
        _fixed(fx, fx["amortization"], fx["contract_detail"]["calculation_calendar"],
               TC2_NOTIONAL_SCALE),
        _term_floating(fl["index"], fl["index_tenor"], floating_leg, periods,
                       fl["contract_detail"]["calculation_calendar"],
                       fl["contract_detail"]["fixing_calendar"], fl["days_before_accrual"],
                       "none", TC2_OBSERVATION_DATES),
    ))


def tc5() -> Dict[str, Any]:
    s = _read("TC5")
    t, fx, fl = s["trade"], s["leg_1"], s["leg_2"]
    cal_code = fl["contract_detail"]["calculation_calendar"]
    fixing_code = fl["contract_detail"]["fixing_calendar"]
    calendar, fixing_calendar = _CAL[cal_code](), _CAL[fixing_code]()
    lag = fl["days_before_accrual"]
    periods = []
    for p, r in zip(_periods(fl["amortization"]), fl["amortization"]):
        start, end = _ql(r["accrual_start"]), _ql(r["accrual_end"])
        # Semiannual sub-resets, Forward EOM roll from the period start (source roll).
        middle = calendar.advance(start, ql.Period("6M"), ql.ModifiedFollowing, True)
        bounds = [start] + ([middle] if middle < end else []) + [end]
        resets = [{"reset_date": _iso(fixing_calendar.advance(a, -lag, ql.Days)),
                   "start": _iso(a), "end": _iso(b)} for a, b in zip(bounds, bounds[1:])]
        if resets[0]["reset_date"] != r["reset_date"]:
            raise ValueError(f"TC5: generated first reset {resets[0]} != source {r}")
        periods.append(dict(p, resets=resets))
    floating_leg = {"day_count": fl["day_count"], "pay_frequency": fl["pay_frequency"],
                    "spread_bp": fl["spread"], "reset_frequency": fl["reset_frequency"]}
    return _document(_top(
        t["swap_id"], t["currency"], t["effective_date"], t["maturity_date"],
        _fixed(fx, fx["amortization"], fx["contract_detail"]["calculation_calendar"]),
        _term_floating(fl["index"], fl["index_tenor"], floating_leg, periods, cal_code,
                       fixing_code, lag, "flat"),
    ))


def _layout_b_inr(case: str) -> Dict[str, Any]:
    t = _read(case)["trade"]
    fx, fl = t["legs"]["fixed"], t["legs"]["floating"]
    return _document(_top(
        t["swap_id"], t["currency"], t["effective_date"], t["maturity_date"],
        _fixed(fx, fx["amortization_schedule"], fx["calculation_calendar"]),
        _term_floating(fl["index"], fl["index_tenor"], fl,
                       _single_reset_periods(fl["amortization_schedule"]),
                       fl["calculation_calendar"], fl["fixing_calendar"],
                       fl["days_before_accrual"], "none"),
    ))


def _overnight(leg_freq: str, day_count: str, spread_bp: float, calendar: str, periods,
               lookback: int, cutoff: int, reset_type: str, compounding: str) -> Dict[str, Any]:
    return {
        "day_count": _DC[day_count],
        "payment_frequency": _FREQ[leg_freq],
        "benchmark": "MUTKCALM",
        "benchmark_tenor": "1D",
        "spread": spread_bp / 10000,
        "leverage": 1.0,
        "reset_frequency": "daily",
        "accrual_date_adjustment": _adjustment(calendar),
        "observation": {"lookback_days": lookback, "cutoff_days": cutoff,
                        "reset_timing": reset_type, "compounding": compounding,
                        "lookback_type": "Lookback"},
        "periods": periods,
    }


def tc6() -> Dict[str, Any]:
    t = _read("TC6")["trade"]
    fx, fl = t["legs"]["fixed"], t["legs"]["floating"]
    rows = fl["amortization_schedule"]
    return _document(_top(
        t["swap_id"], t["currency"], t["effective_date"], t["maturity_date"],
        _fixed(fx, rows, fx["calculation_calendar"]),
        _overnight(fl["pay_frequency"], fl["day_count"], fl["spread_bp"],
                   fl["calculation_calendar"], _periods(rows), fl["days_before_accrual"],
                   fl["rate_cutoff_days"], fl["reset_type"], fl["compounding"]),
    ))


def tc10() -> Dict[str, Any]:
    s = _read("TC10")
    t, fx, fl = s["trade"], s["fixed_leg"], s["floating_leg"]
    rows = [{"accrual_start": r["accrual_start"], "accrual_end": r["accrual_end"],
             "pay_date": r["pay_date"], "balance": r["balance"]}
            for r in s["amortization_schedule"]]
    fixed = {"day_count": _DC[fx["day_count"]], "payment_frequency": _FREQ[fx["pay_frequency"]],
             "fixed_rate": fx["coupon_rate_pct"] / 100,
             "accrual_date_adjustment": _adjustment(fx["date_adjustment"]["calendar"]),
             "periods": _periods(rows)}
    return _document(_top(
        t["trade_id"], t["currency"], t["effective_date"], t["maturity_date"], fixed,
        _overnight(fl["pay_frequency"], fl["day_count"], fl["spread_bps"],
                   fl["date_adjustments"]["calendar"], _periods(rows), fl["lookback_days"],
                   fl["rate_cutoff_days"], fl["reset_type"], fl["compounding"]),
    ))


BUILDERS = {"TC2": tc2, "TC5": tc5, "TC6": tc6, "TC8": lambda: _layout_b_inr("TC8"),
            "TC9": lambda: _layout_b_inr("TC9"), "TC10": tc10}


def to_text(document: Dict[str, Any]) -> str:
    return json.dumps(document, indent=2) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate canonical trade inputs.")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    status = 0
    for case in CASES:
        text = to_text(BUILDERS[case]())
        path = ROOT / "examples" / "irs" / f"{case.lower()}_trade.json"
        if args.check:
            same = path.exists() and path.read_text(encoding="utf-8").replace("\r\n", "\n") == text
            print(f"{path.name}: {'up to date' if same else 'DIFFERS'}")
            status |= 0 if same else 1
        else:
            path.write_text(text, encoding="utf-8")
            print(f"wrote {path.name}")
    return status


if __name__ == "__main__":
    sys.exit(main())
