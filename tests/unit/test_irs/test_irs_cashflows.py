"""Period cashflow rows read from the swap the engine priced (TC1 and TC3).

Four kinds of assertion, kept apart:
1. Engine agreement: row PVs sum to the engine's leg NPVs and total NPV, so the
   rows show what was priced (no second pricing path).
2. Contract: dates and amortising notionals equal the trade inputs.
3. Optima regression: rates, amounts and DFs equal the existing TC1/TC3
   baselines (imported, not copied).
4. Bloomberg reconciliation against ``cashflow_leg_*``: reconciled periods within
   the existing display tolerances; documented differences (OI-1, OI-7) equal the
   existing KNOWN_DIFFERENCES entries.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
import QuantLib as ql
from test_tc1_bloomberg_reconciliation import BASELINE as TC1_BASELINE
from test_tc1_bloomberg_reconciliation import (
    BASELINE_TOLERANCE,
    DF_DISPLAY_TOL,
    PAYMENT_TOL,
)
from test_tc1_bloomberg_reconciliation import KNOWN_DIFFERENCES as TC1_KNOWN_DIFFERENCES
from test_tc1_pricing_service_e2e import _tc1_params
from test_tc3_pricing_service_e2e import BASELINE as TC3_BASELINE
from test_tc3_pricing_service_e2e import FIXTURES, tc3_params
from test_tc3_pricing_service_e2e import KNOWN_DIFFERENCES as TC3_KNOWN_DIFFERENCES

from api.v1.helpers import build_instrument_from_request
from api.v1.schemas import InstrumentRequest
from instruments.rates.irs.cashflows import (
    CashflowExtractionError,
    settled_cashflows,
    IRSCashflowRow,
    irs_cashflow_rows,
)
from market.curves.irs_market_environment import build_single_curve_irs_environment
from market.curves.irs_zero_curve import build_zero_curve
from services.pricers.pricing_service import PricingService

VALUATION_DATE = date(2026, 3, 31)
FIXED_AMOUNT_TOL = 0.005  # as in the TC1/TC3 fixed-cashflow reconciliation tests

# Floating periods with a documented difference (open item -> metric prefix).
KNOWN_FLOATING_PERIODS = {"TC1": {2: "OI-1"}, "TC3": {3: "OI-1", 4: "OI-7"}}


def _json(kind: str, case_id: str) -> dict:
    return json.loads((FIXTURES / kind / f"{case_id}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def environment(usd_sofr_market_data, usd_sofr_curve_conventions):
    curve = build_zero_curve(usd_sofr_market_data, usd_sofr_curve_conventions)
    return build_single_curve_irs_environment(VALUATION_DATE, curve)


@pytest.fixture(scope="module")
def priced(tc1_documents, environment):
    """Price TC1 and TC3 through PricingService and read rows from the priced swaps."""
    case1, source1, _ = tc1_documents
    params = {"TC1": _tc1_params(case1, source1), "TC3": tc3_params(_json("cases", "TC3"))}
    previous = ql.Settings.instance().evaluationDate
    out = {}
    try:
        for case_id, case_params in params.items():
            instrument = build_instrument_from_request(
                InstrumentRequest(type="ois", params=case_params)
            )
            result = PricingService().price(
                instrument=instrument,
                market_env=environment,
                model_type="analytical",
                engine_type="discounting",
            )
            evaluation_before = ql.Settings.instance().evaluationDate
            rows = irs_cashflow_rows(instrument.last_built, environment.discount_curves["USD"])
            swap = instrument.last_built.quantlib_instrument
            out[case_id] = {
                "instrument": instrument,
                "result": result,
                "rows": rows,
                "legs": instrument.leg_npvs(),
                # Read while the pricing evaluation date is still set.
                "engine_leg_npvs": (swap.legNPV(0), swap.legNPV(1)),
                "evaluation_unchanged": ql.Settings.instance().evaluationDate
                == evaluation_before,
            }
    finally:
        ql.Settings.instance().evaluationDate = previous
    return out


def _rows(priced, case_id: str, leg: str):
    return [row for row in priced[case_id]["rows"] if row.leg == leg]


def _bloomberg(case_id: str, leg: str) -> list:
    sections = _json("references", case_id)["source_oracle_sections"]
    return sections["cashflow_leg_1" if leg == "fixed" else "cashflow_leg_2"]["cashflows"]


CASES = ["TC1", "TC3"]


# --- 1. engine agreement -------------------------------------------------------------


@pytest.mark.parametrize("case_id", CASES)
def test_pvs_sum_to_engine_leg_npvs_and_total(priced, case_id):
    engine_leg_npvs = priced[case_id]["engine_leg_npvs"]
    for leg, index in (("fixed", 0), ("floating", 1)):  # both trades pay fixed
        total = sum(row.present_value for row in _rows(priced, case_id, leg))
        assert total == pytest.approx(engine_leg_npvs[index], abs=1e-9)
        assert total == pytest.approx(priced[case_id]["legs"][leg], abs=1e-9)
    total = sum(row.present_value for row in priced[case_id]["rows"])
    assert total == pytest.approx(priced[case_id]["result"].npv, abs=1e-9)


@pytest.mark.parametrize("case_id", CASES)
def test_rows_are_internally_consistent(priced, case_id):
    for row in priced[case_id]["rows"]:
        assert isinstance(row, IRSCashflowRow)
        sign = -1.0 if row.side == "pay" else 1.0
        assert row.side == ("pay" if row.leg == "fixed" else "receive")
        assert row.amount == pytest.approx(
            sign * row.notional * row.rate * row.day_count_fraction, abs=1e-8
        )
        assert row.present_value == pytest.approx(row.amount * row.discount_factor, abs=1e-12)
        assert (row.spread is None) == (row.leg == "fixed")
    assert priced[case_id]["evaluation_unchanged"]


# --- 2. contract: dates and amortising notionals ---------------------------------------


def test_tc1_dates_and_notionals(priced, tc1_documents):
    case, _, _ = tc1_documents
    periods = case["trade"]["amortization_source"]["period_notionals"]
    payments = case["schedule_inputs"]["receive_leg"]["payment_dates"]
    for leg in ("fixed", "floating"):
        rows = _rows(priced, "TC1", leg)
        assert len(rows) == len(periods) == 2
        for row, period, payment in zip(rows, periods, payments):
            assert row.accrual_start == date.fromisoformat(period["period_start"])
            assert row.accrual_end == date.fromisoformat(period["period_end"])
            assert row.payment_date == date.fromisoformat(payment)
            assert row.notional == period["notional"]
    assert [row.notional for row in _rows(priced, "TC1", "floating")] == [530000.0, 265000.0]


def test_tc3_dates_and_amortising_notionals(priced):
    sections = _json("cases", "TC3")["input_sections"]
    for leg, source in (("fixed", "leg_1"), ("floating", "leg_2")):
        rows = _rows(priced, "TC3", leg)
        schedule = sections[source]["amortization"]
        assert len(rows) == len(schedule) == 4
        for row, period in zip(rows, schedule):
            assert row.accrual_start == date.fromisoformat(period["accrual_start"])
            assert row.accrual_end == date.fromisoformat(period["accrual_end"])
            assert row.payment_date == date.fromisoformat(period["pay_date"])
            assert row.notional == period["balance"]
        assert [row.notional for row in rows] == [790000.0, 592500.0, 395000.0, 197500.0]
        assert rows[0].accrual_start == date(2026, 5, 31)  # effective date, unadjusted
        assert rows[-1].accrual_end == date(2028, 4, 28)  # contractual 30-Apr-2028 adjusted


# --- 3. Optima regression baseline ----------------------------------------------------


def _tolerance(metric: str) -> float:
    return next(tol for suffix, tol in BASELINE_TOLERANCE.items() if metric.endswith(suffix))


@pytest.mark.parametrize("case_id, baseline", [("TC1", TC1_BASELINE), ("TC3", TC3_BASELINE)])
def test_rows_match_recorded_baselines(priced, case_id, baseline):
    for row in _rows(priced, case_id, "floating"):
        n = row.period
        assert row.rate * 100 == pytest.approx(
            baseline[f"floating_p{n}_rate_pct"], abs=_tolerance("rate_pct")
        )
        assert row.amount == pytest.approx(
            baseline[f"floating_p{n}_amount"], abs=_tolerance("amount")
        )
        assert row.discount_factor == pytest.approx(
            baseline[f"p{n}_discount_factor"], abs=_tolerance("discount_factor")
        )
    for row in _rows(priced, case_id, "fixed"):
        assert -row.amount == pytest.approx(
            baseline[f"fixed_p{row.period}_amount"], abs=_tolerance("amount")
        )


# --- 4. Bloomberg reconciliation --------------------------------------------------------


@pytest.mark.parametrize("case_id", CASES)
@pytest.mark.parametrize("leg", ["fixed", "floating"])
def test_dates_and_days_match_bloomberg(priced, case_id, leg):
    for row, bbg in zip(_rows(priced, case_id, leg), _bloomberg(case_id, leg), strict=True):
        assert row.accrual_start == date.fromisoformat(bbg["accrual_start"])
        assert row.accrual_end == date.fromisoformat(bbg["accrual_end"])
        assert row.payment_date == date.fromisoformat(bbg["pay_date"])
        assert (row.accrual_end - row.accrual_start).days == bbg["days"]
        assert bbg["principal"] == 0.0  # no principal exchange


def test_bloomberg_notional_columns(priced):
    """TC3 notionals match Bloomberg. The TC1 Bloomberg export shows notionals
    1000x the confirmed trade (fixture README: 530,000 -> 265,000 scale); its
    payments are on the confirmed scale."""
    for leg in ("fixed", "floating"):
        sign = -1.0 if leg == "fixed" else 1.0
        for row, bbg in zip(_rows(priced, "TC3", leg), _bloomberg("TC3", leg), strict=True):
            assert sign * row.notional == bbg["notional"]
        for row, bbg in zip(_rows(priced, "TC1", leg), _bloomberg("TC1", leg), strict=True):
            assert sign * row.notional * 1000 == bbg["notional"]


@pytest.mark.parametrize("case_id", CASES)
def test_fixed_amounts_reconcile(priced, case_id):
    for row, bbg in zip(_rows(priced, case_id, "fixed"), _bloomberg(case_id, "fixed"), strict=True):
        assert row.amount == pytest.approx(bbg["payment"], abs=FIXED_AMOUNT_TOL)


@pytest.mark.parametrize("case_id", CASES)
def test_reconciled_floating_periods(priced, case_id):
    known = KNOWN_FLOATING_PERIODS[case_id]
    for row, bbg in zip(
        _rows(priced, case_id, "floating"), _bloomberg(case_id, "floating"), strict=True
    ):
        if row.period in known:
            continue
        assert row.amount == pytest.approx(bbg["payment"], abs=PAYMENT_TOL)
        assert row.discount_factor == pytest.approx(bbg["discount_factor"], abs=DF_DISPLAY_TOL)
        assert row.present_value == pytest.approx(bbg["pv"], abs=PAYMENT_TOL)


@pytest.mark.parametrize(
    "case_id, period, known",
    [
        ("TC1", 2, TC1_KNOWN_DIFFERENCES),  # OI-1
        ("TC3", 3, TC3_KNOWN_DIFFERENCES),  # OI-1
        ("TC3", 4, TC3_KNOWN_DIFFERENCES),  # OI-7
    ],
)
def test_documented_floating_differences_are_kept(priced, case_id, period, known):
    row = _rows(priced, case_id, "floating")[period - 1]
    bbg = _bloomberg(case_id, "floating")[period - 1]
    for metric, observed in (
        (f"floating_p{period}_rate_pct", row.rate * 100 - bbg["equivalent_coupon"]),
        (f"floating_p{period}_amount", row.amount - bbg["payment"]),
        (f"p{period}_discount_factor", row.discount_factor - bbg["discount_factor"]),
    ):
        expected, tolerance = known[metric]
        assert observed == pytest.approx(expected, abs=tolerance), metric


@pytest.mark.parametrize(
    "case_id, period, known",
    [("TC1", 2, TC1_KNOWN_DIFFERENCES), ("TC3", 3, TC3_KNOWN_DIFFERENCES),
     ("TC3", 4, TC3_KNOWN_DIFFERENCES)],
)
def test_fixed_rows_on_known_dates_differ_only_by_the_documented_df(priced, case_id, period, known):
    row = _rows(priced, case_id, "fixed")[period - 1]
    bbg = _bloomberg(case_id, "fixed")[period - 1]
    expected, tolerance = known[f"p{period}_discount_factor"]
    assert row.discount_factor - bbg["discount_factor"] == pytest.approx(expected, abs=tolerance)
    assert row.amount == pytest.approx(bbg["payment"], abs=FIXED_AMOUNT_TOL)


# --- explicit failures ----------------------------------------------------------------


def test_wrong_evaluation_date_is_rejected(priced, environment):
    built = priced["TC1"]["instrument"].last_built
    previous = ql.Settings.instance().evaluationDate
    try:
        ql.Settings.instance().evaluationDate = ql.Date(1, 4, 2026)
        with pytest.raises(CashflowExtractionError, match="differs from the discount curve"):
            irs_cashflow_rows(built, environment.discount_curves["USD"])
        assert ql.Settings.instance().evaluationDate == ql.Date(1, 4, 2026)  # not changed
    finally:
        ql.Settings.instance().evaluationDate = previous


def test_settled_cashflows_are_excluded_like_the_engine(priced):
    """Seasoned trades: a coupon paying on the valuation date is excluded (as by
    ql.DiscountingSwapEngine) and listed as settled; later coupons are still valued."""
    built = priced["TC1"]["instrument"].last_built
    valuation = ql.Date(28, 5, 2027)  # TC1 period 1 pays on this date
    curve = ql.YieldTermStructureHandle(ql.FlatForward(valuation, 0.04, ql.Actual365Fixed()))
    previous = ql.Settings.instance().evaluationDate
    try:
        ql.Settings.instance().evaluationDate = valuation
        settled = settled_cashflows(built, valuation)
        assert {(s.leg, s.period) for s in settled} == {("fixed", 1), ("floating", 1)}
        rows = irs_cashflow_rows(built, curve)
        assert [(r.leg, r.period) for r in rows] == [("fixed", 2), ("floating", 2)]
        for r in rows:
            assert r.present_value == pytest.approx(r.amount * r.discount_factor)
        assert ql.Settings.instance().evaluationDate == valuation  # not changed
    finally:
        ql.Settings.instance().evaluationDate = previous


def test_missing_historical_fixings_are_reported_clearly(priced):
    """A coupon still to be paid whose fixings precede the valuation date needs them."""
    built = priced["TC1"]["instrument"].last_built
    valuation = ql.Date(15, 6, 2027)  # TC1 period 2 observes SOFR from 28-May-2027
    curve = ql.YieldTermStructureHandle(ql.FlatForward(valuation, 0.04, ql.Actual365Fixed()))
    previous = ql.Settings.instance().evaluationDate
    try:
        ql.Settings.instance().evaluationDate = valuation
        with pytest.raises(CashflowExtractionError,
                           match="floating period 2 .* fixings before the valuation date"):
            irs_cashflow_rows(built, curve)
    finally:
        ql.Settings.instance().evaluationDate = previous


def test_empty_curve_and_wrong_object_are_rejected(priced):
    built = priced["TC1"]["instrument"].last_built
    with pytest.raises(CashflowExtractionError, match="not usable"):
        irs_cashflow_rows(built, ql.YieldTermStructureHandle())
    with pytest.raises(CashflowExtractionError, match="QuantLibIRSInstrument"):
        irs_cashflow_rows(built.quantlib_instrument, ql.YieldTermStructureHandle())
