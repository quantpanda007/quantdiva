"""TC3 (SLLSL90) end-to-end through the generic pricing path, on the fresh IRS.

PricingRequest -> build_instrument_from_request -> PricingService.price, with
instrument "ois", model "analytical", engine "discounting", and the same USD SOFR
single-curve environment as TC1.

TC3: pay 2.00% fixed vs receive SOFR + 70 bp, both legs semiannual ACT/360,
790,000 amortising 25% per period, contractual 31-May-2026 to 30-Apr-2028.

Dates: the contractual maturity 30-Apr-2028 is a Sunday; the final accrual end is
28-Apr-2028 (Modified Following, calendar FD). ``maturity_date`` is passed as the
contractual date and is not normalised; each leg's final accrual end is checked
against it adjusted with the leg's calendar and convention (OI-8).

Three kinds of assertion are kept apart:
1. Optima regression baseline: Optima's own outputs, pinned (BASELINE).
2. Reconciled with Bloomberg: P1, P2 and the fixed cashflows within Bloomberg
   display precision (tolerances shared with TC1).
3. Documented Bloomberg differences (KNOWN_DIFFERENCES): P3 is OI-1 (same dates
   and the same difference as TC1 Period 2), P4 is OI-7. Nothing is tuned.

Bloomberg leg references are the ``cashflow_leg_*`` sections. The ``leg_*_market``
values are not leg PVs and are recorded as unexplained (OI-9).

Inputs come from tests/fixtures/bloomberg_irs/cases/TC3.json (raw Bloomberg
``input_sections``); Bloomberg values from references/TC3.json. The baseline was
recorded on 09-Oct-2026 with QuantLib 1.43.
"""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import pytest
import QuantLib as ql
from test_tc1_bloomberg_reconciliation import BASELINE as TC1_BASELINE
from test_tc1_bloomberg_reconciliation import (
    BASELINE_TOLERANCE,
    COUPON_DISPLAY_TOL_PCT,
    DF_DISPLAY_TOL,
    PAYMENT_TOL,
)
from test_tc1_bloomberg_reconciliation import KNOWN_DIFFERENCES as TC1_KNOWN_DIFFERENCES
from test_tc1_pricing_service_e2e import accrual_date_adjustment

from api.v1.helpers import build_instrument_from_request
from api.v1.schemas import InstrumentRequest, MarketDataRequest, PricingRequest, UnderlyingData
from core.interfaces.base import MarketEnvironment
from instruments.rates.irs.pricing_instrument import FreshOISInstrument, InvalidIRSParameters
from market.curves.irs_market_environment import build_single_curve_irs_environment
from market.curves.irs_zero_curve import build_zero_curve
from services.pricers.pricing_service import PricingService

FIXTURES = Path(__file__).resolve().parents[3] / "tests/fixtures/bloomberg_irs"
VALUATION_DATE = date(2026, 3, 31)
CONTRACTUAL_MATURITY = date(2028, 4, 30)  # Sunday
FINAL_ACCRUAL_END = date(2028, 4, 28)  # Modified Following, FD
EFFECTIVE_DATE = date(2026, 5, 31)  # Sunday, left unadjusted

# --- 1. Optima regression baseline (QuantLib 1.43) ----------------------------------
BASELINE = {
    "floating_p1_rate_pct": 4.375713958938917,
    "floating_p1_amount": 17572.13797343887,
    "p1_discount_factor": 0.9755910947649191,
    "floating_p2_rate_pct": 4.3276322240549465,
    "floating_p2_amount": 12749.384850075208,
    "p2_discount_factor": 0.9583057566822694,
    "floating_p3_rate_pct": 4.239707547099463,
    "floating_p3_amount": 8652.53648570549,
    "p3_discount_factor": 0.9410945591947374,
    "floating_p4_rate_pct": 4.126212307260155,
    "floating_p4_amount": 3395.528877849503,
    "p4_discount_factor": 0.9278486982398019,
    "fixed_p1_amount": 8031.666666666659,
    "fixed_p2_amount": 5892.083333333386,
    "fixed_p3_amount": 4081.6666666666556,
    "fixed_p4_amount": 1645.8333333333276,
    "fixed_leg_npv": -18850.35846160478,
    "floating_leg_npv": 40654.422277931924,
    "npv": 21804.063816327143,
}

# --- 3. Documented Bloomberg differences (Optima baseline minus Bloomberg) ----------
# OI-1: 30-Nov-2027 (TC3 P3 = TC1 Period 2 dates). OI-7: 28-Apr-2028 (TC3 P4).
KNOWN_DIFFERENCES = {
    "p3_discount_factor": (+2.56e-6, 1e-8),  # OI-1
    "floating_p3_rate_pct": (-0.0005425, 1e-6),  # OI-1, -0.054 bp
    "floating_p3_amount": (-1.1035, 1e-3),  # OI-1
    "p4_discount_factor": (-5.30e-6, 1e-8),  # OI-7
    "floating_p4_rate_pct": (+0.0021723, 1e-6),  # OI-7, +0.217 bp
    "floating_p4_amount": (+1.7889, 1e-3),  # OI-7
    "floating_leg_npv": (+0.5923, 1e-3),  # P3 and P4 effects, opposite signs
    "fixed_leg_npv": (+0.0015, 1e-3),  # P3/P4 DF effects plus display rounding
    "npv": (+0.5938, 1e-3),
}


def _tolerance_for(metric: str) -> float:
    for suffix, tolerance in BASELINE_TOLERANCE.items():
        if metric.endswith(suffix):
            return tolerance
    raise KeyError(metric)


def _load(kind: str) -> dict:
    return json.loads((FIXTURES / kind / "TC3.json").read_text(encoding="utf-8"))


def _periods(leg: dict) -> list:
    return [
        {
            "accrual_start": row["accrual_start"],
            "accrual_end": row["accrual_end"],
            "payment_date": row["pay_date"],
            "notional": row["balance"],
        }
        for row in leg["amortization"]
    ]


def tc3_params(case: dict) -> dict:
    """Request params from the raw Bloomberg ``input_sections`` of cases/TC3.json."""
    sections = case["input_sections"]
    trade, fixed, floating = sections["trade"], sections["leg_1"], sections["leg_2"]
    assert fixed["type"] == "Fixed" and floating["type"] == "Floating"
    return {
        "trade_id": trade["swap_id"],
        "currency": trade["currency"],
        "valuation_date": trade["valuation_date"],
        "effective_date": trade["effective_date"],
        "maturity_date": trade["maturity_date"],  # contractual, unadjusted
        "fixed_leg_side": fixed["pay_receive"].lower(),
        "fixed_leg": {
            "day_count": fixed["day_count"],
            "payment_frequency": fixed["pay_frequency"].lower(),
            "fixed_rate": fixed["coupon"] / 100.0,
            "accrual_date_adjustment": accrual_date_adjustment(fixed["contract_detail"]),
            "periods": _periods(fixed),
        },
        "floating_leg": {
            "day_count": floating["day_count"],
            "payment_frequency": floating["pay_frequency"].lower(),
            "benchmark": floating["index"],
            "benchmark_tenor": floating["index_tenor"],
            "spread": floating["spread"] / 10000.0,
            "leverage": floating["leverage"],
            "reset_frequency": floating["reset_frequency"].lower(),
            "accrual_date_adjustment": accrual_date_adjustment(floating["contract_detail"]),
            "observation": {
                "lookback_days": floating["days_before_accrual"],
                "cutoff_days": floating["rate_cut_off_days"],
                "reset_timing": floating["reset_type"],
                "compounding": floating["compounding"],
                "lookback_type": floating["days_before_type"],
            },
            "periods": _periods(floating),
        },
    }


@pytest.fixture(scope="module")
def tc3_case() -> dict:
    return _load("cases")


@pytest.fixture(scope="module")
def tc3_reference() -> dict:
    return _load("references")["source_oracle_sections"]


@pytest.fixture(scope="module")
def tc3_parameters(tc3_case) -> dict:
    return tc3_params(tc3_case)


@pytest.fixture(scope="module")
def tc3_request(tc3_parameters) -> PricingRequest:
    return PricingRequest(
        instrument=InstrumentRequest(type="ois", params=tc3_parameters),
        market_data=MarketDataRequest(
            pricing_date=VALUATION_DATE.isoformat(),
            underlyings={"USD": UnderlyingData(spot=1.0)},
        ),
        model="analytical",
        engine="discounting",
    )


@pytest.fixture(scope="module")
def usd_sofr_environment(usd_sofr_market_data, usd_sofr_curve_conventions) -> MarketEnvironment:
    curve = build_zero_curve(
        usd_sofr_market_data,
        usd_sofr_curve_conventions,
        expected_currency="USD",
        expected_benchmark="SOFR",
    )
    return build_single_curve_irs_environment(VALUATION_DATE, curve)


@pytest.fixture(scope="module")
def service_run(tc3_request, usd_sofr_environment):
    """Price once through the service, capturing the exact swap object it priced."""
    previous = ql.Settings.instance().evaluationDate
    try:
        instrument = build_instrument_from_request(tc3_request.instrument)
        built_swaps = []
        original_build = instrument.build

        def capture(environment):
            swap = original_build(environment)
            built_swaps.append(swap)
            return swap

        instrument.build = capture
        result = PricingService().price(
            instrument=instrument,
            market_env=usd_sofr_environment,
            model_type=tc3_request.model,
            engine_type=tc3_request.engine,
        )
        legs = instrument.leg_npvs()
        swap = built_swaps[-1]
        # Discount factors are read with the evaluation date still at valuation.
        ql.Settings.instance().evaluationDate = ql.Date(
            VALUATION_DATE.day, VALUATION_DATE.month, VALUATION_DATE.year
        )
        curve = usd_sofr_environment.discount_curves["USD"]
        optima = {}
        for i, cashflow in enumerate(swap.leg(1), start=1):
            coupon = ql.as_floating_rate_coupon(cashflow)
            optima[f"floating_p{i}_rate_pct"] = coupon.rate() * 100.0
            optima[f"floating_p{i}_amount"] = cashflow.amount()
            optima[f"p{i}_discount_factor"] = curve.discount(cashflow.date())
        for i, cashflow in enumerate(swap.leg(0), start=1):
            optima[f"fixed_p{i}_amount"] = cashflow.amount()
        optima["fixed_leg_npv"] = legs["fixed"]
        optima["floating_leg_npv"] = legs["floating"]
        optima["npv"] = result.npv
        return {
            "instrument": instrument,
            "result": result,
            "legs": legs,
            "built_swaps": built_swaps,
            "captured_npv": swap.NPV(),
            "optima": optima,
        }
    finally:
        ql.Settings.instance().evaluationDate = previous


@pytest.fixture(scope="module")
def optima(service_run) -> dict:
    return service_run["optima"]


@pytest.fixture(scope="module")
def bloomberg(tc3_reference) -> dict:
    floating = tc3_reference["cashflow_leg_2"]["cashflows"]
    fixed = tc3_reference["cashflow_leg_1"]["cashflows"]
    values = {}
    for i, (flt, fix) in enumerate(zip(floating, fixed), start=1):
        values[f"floating_p{i}_rate_pct"] = flt["equivalent_coupon"]
        values[f"floating_p{i}_amount"] = flt["payment"]
        values[f"p{i}_discount_factor"] = flt["discount_factor"]
        values[f"fixed_p{i}_amount"] = -fix["payment"]  # paid leg shown negative
    values["fixed_leg_npv"] = tc3_reference["cashflow_leg_1"]["npv"]
    values["floating_leg_npv"] = tc3_reference["cashflow_leg_2"]["npv"]
    values["npv"] = tc3_reference["valuation_results"]["npv"]
    return values


# --- wiring and dates -------------------------------------------------------------


def test_case_terms_equal_the_bloomberg_source(tc3_case):
    source = json.loads((FIXTURES / "source" / "TC3.json").read_text(encoding="utf-8"))
    sections = tc3_case["input_sections"]
    assert sections["trade"] == source["trade"]
    for leg in ("leg_1", "leg_2"):
        trimmed = {key: value for key, value in source[leg].items() if key != "market"}
        assert sections[leg] == trimmed


def test_request_builds_the_fresh_instrument(service_run):
    instrument = service_run["instrument"]
    assert type(instrument) is FreshOISInstrument
    observation = instrument.trade.floating_terms.observation
    assert observation.lookback_days == 0  # case and source agree for TC3
    assert observation.cutoff_days == 1  # kept as metadata, lockoutDays 0 (OI-2)


def test_contractual_maturity_is_kept_and_final_accrual_end_is_adjusted(service_run):
    instrument = service_run["instrument"]
    trade = instrument.trade
    assert instrument.maturity() == CONTRACTUAL_MATURITY
    assert trade.maturity_date == CONTRACTUAL_MATURITY
    for periods in (trade.fixed_periods, trade.floating_periods):
        assert periods[0].accrual_start == EFFECTIVE_DATE  # start exact
        assert periods[-1].accrual_end == FINAL_ACCRUAL_END  # end adjusted
        assert periods[-1].payment_date == FINAL_ACCRUAL_END
    for adjustment in (trade.fixed_date_adjustment, trade.floating_date_adjustment):
        assert adjustment.adjust(CONTRACTUAL_MATURITY) == FINAL_ACCRUAL_END
    swap = service_run["built_swaps"][0]
    for leg in (swap.leg(0), swap.leg(1)):
        assert leg[len(leg) - 1].date() == ql.Date(28, 4, 2028)


def test_period_notionals_amortise(service_run):
    swap = service_run["built_swaps"][0]
    expected = [790000.0, 592500.0, 395000.0, 197500.0]
    for leg in (swap.leg(0), swap.leg(1)):
        assert [ql.as_coupon(cashflow).nominal() for cashflow in leg] == expected


def test_leg_npvs_come_from_the_swap_the_engine_priced(service_run):
    instrument, result = service_run["instrument"], service_run["result"]
    assert len(service_run["built_swaps"]) == 1
    assert instrument.last_built.quantlib_instrument is service_run["built_swaps"][0]
    assert service_run["captured_npv"] == result.npv
    legs = service_run["legs"]
    assert legs["fixed"] + legs["floating"] == pytest.approx(result.npv, abs=1e-9)
    assert result.engine_used == "discounting" and result.model_used == "analytical"


# --- 1. Optima regression baseline ------------------------------------------------


@pytest.mark.parametrize("metric", sorted(BASELINE))
def test_optima_matches_recorded_baseline(optima, metric):
    assert optima[metric] == pytest.approx(BASELINE[metric], abs=_tolerance_for(metric))


def test_shared_dates_agree_with_tc1_baseline(optima):
    """Same curve and accrual dates as TC1: TC3 P2/P3 discount factors equal TC1
    P1/P2, and the compounded SOFR in TC3 P3 equals TC1 Period 2 (spreads 70 vs 10 bp)."""
    assert optima["p2_discount_factor"] == TC1_BASELINE["p1_discount_factor"]
    assert optima["p3_discount_factor"] == TC1_BASELINE["p2_discount_factor"]
    assert optima["floating_p3_rate_pct"] - 0.70 == pytest.approx(
        TC1_BASELINE["floating_p2_rate_pct"] - 0.10, abs=1e-9
    )


# --- 2. Reconciled with Bloomberg --------------------------------------------------


@pytest.mark.parametrize("period", [1, 2])
def test_early_periods_reconcile(optima, bloomberg, period):
    rate, amount, df = (
        f"floating_p{period}_rate_pct",
        f"floating_p{period}_amount",
        f"p{period}_discount_factor",
    )
    assert optima[rate] == pytest.approx(bloomberg[rate], abs=COUPON_DISPLAY_TOL_PCT)
    assert optima[amount] == pytest.approx(bloomberg[amount], abs=PAYMENT_TOL)
    assert optima[df] == pytest.approx(bloomberg[df], abs=DF_DISPLAY_TOL)


@pytest.mark.parametrize("period", [1, 2, 3, 4])
def test_fixed_cashflows_reconcile(optima, bloomberg, period):
    metric = f"fixed_p{period}_amount"
    assert optima[metric] == pytest.approx(bloomberg[metric], abs=0.005)


# --- 3. Documented Bloomberg differences --------------------------------------------


@pytest.mark.parametrize("metric", sorted(KNOWN_DIFFERENCES))
def test_open_difference_is_the_documented_one(optima, bloomberg, metric):
    expected, tolerance = KNOWN_DIFFERENCES[metric]
    assert optima[metric] - bloomberg[metric] == pytest.approx(expected, abs=tolerance)


def test_period3_difference_is_tc1_oi1(optima, bloomberg):
    """OI-1 seen in a second trade: the same rate and DF difference as TC1 Period 2."""
    for tc3_metric, tc1_metric in (
        ("floating_p3_rate_pct", "floating_p2_rate_pct"),
        ("p3_discount_factor", "p2_discount_factor"),
    ):
        expected, tolerance = TC1_KNOWN_DIFFERENCES[tc1_metric]
        assert optima[tc3_metric] - bloomberg[tc3_metric] == pytest.approx(
            expected, abs=tolerance
        )


def test_floating_leg_gap_comes_from_periods_3_and_4(optima, bloomberg):
    """P3 (OI-1) and P4 (OI-7) payment effects have opposite signs and explain the gap."""
    effects = {
        period: (optima[f"floating_p{period}_amount"] - bloomberg[f"floating_p{period}_amount"])
        * bloomberg[f"p{period}_discount_factor"]
        for period in (3, 4)
    }
    assert effects[3] == pytest.approx(-1.04, abs=0.01)
    assert effects[4] == pytest.approx(+1.66, abs=0.01)
    total_gap = optima["floating_leg_npv"] - bloomberg["floating_leg_npv"]
    assert abs(total_gap - effects[3] - effects[4]) < 0.05


def test_bloomberg_market_leg_values_are_not_cashflow_leg_npvs(tc3_reference):
    """OI-9: ``leg_*_market`` NPVs sum to the trade NPV but are not the cashflow-leg
    PVs; they are recorded, not used as references."""
    market = tc3_reference["leg_1_market"]["npv"] + tc3_reference["leg_2_market"]["npv"]
    cashflow = tc3_reference["cashflow_leg_1"]["npv"] + tc3_reference["cashflow_leg_2"]["npv"]
    assert market == pytest.approx(tc3_reference["valuation_results"]["npv"], abs=0.01)
    assert cashflow == pytest.approx(tc3_reference["valuation_results"]["npv"], abs=0.01)
    assert tc3_reference["leg_1_market"]["npv"] != tc3_reference["cashflow_leg_1"]["npv"]
    assert tc3_reference["leg_2_market"]["npv"] != tc3_reference["cashflow_leg_2"]["npv"]


# --- date validation ---------------------------------------------------------------


def _with_convention(params: dict, convention: str) -> dict:
    params = copy.deepcopy(params)
    for leg in ("fixed_leg", "floating_leg"):
        params[leg]["accrual_date_adjustment"]["business_day_convention"] = convention
    return params


@pytest.mark.parametrize(
    "convention, adjusted_maturity",
    [("unadjusted", "2028-04-30"), ("following", "2028-05-01")],
)
def test_incorrect_convention_is_rejected(tc3_parameters, convention, adjusted_maturity):
    params = _with_convention(tc3_parameters, convention)
    with pytest.raises(
        InvalidIRSParameters,
        match=f"i.e. {adjusted_maturity}; final accrual_end is 2028-04-28",
    ):
        FreshOISInstrument.from_dict(params)


def test_conventions_are_checked_per_leg(tc3_parameters):
    params = copy.deepcopy(tc3_parameters)
    params["floating_leg"]["accrual_date_adjustment"]["business_day_convention"] = "following"
    with pytest.raises(InvalidIRSParameters, match="floating periods must end"):
        FreshOISInstrument.from_dict(params)


def test_adjusted_first_accrual_start_is_rejected(tc3_parameters):
    """Start exact: 31-May-2026 (Sunday) adjusted to 29-May-2026 is not accepted."""
    params = copy.deepcopy(tc3_parameters)
    params["fixed_leg"]["periods"][0]["accrual_start"] = "2026-05-29"
    with pytest.raises(InvalidIRSParameters, match="must start on the effective_date"):
        FreshOISInstrument.from_dict(params)


def test_unsupported_calendar_is_rejected(tc3_parameters):
    params = copy.deepcopy(tc3_parameters)
    params["floating_leg"]["accrual_date_adjustment"]["calendar"] = "GT"
    with pytest.raises(InvalidIRSParameters, match="'GT' is not supported"):
        FreshOISInstrument.from_dict(params)


def test_one_way_validation_limitation(tc3_parameters):
    """Known limitation (OI-8): an already-adjusted date supplied as maturity_date also
    validates, because adjusting a business day leaves it unchanged. It is stored as
    given; the check cannot tell that it is not the contractual date."""
    params = copy.deepcopy(tc3_parameters)
    params["maturity_date"] = FINAL_ACCRUAL_END.isoformat()
    instrument = FreshOISInstrument.from_dict(params)
    assert instrument.maturity() == FINAL_ACCRUAL_END  # not normalised either way
