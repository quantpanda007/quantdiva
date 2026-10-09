"""TC1 end-to-end through the generic pricing path, on the fresh IRS implementation.

PricingRequest -> build_instrument_from_request -> PricingService.price, with:
* instrument type "ois" (FreshOISInstrument), model "analytical", engine
  "discounting" (FreshIRSDiscountingEngine);
* the market environment from build_single_curve_irs_environment and the
  production zero-curve builder fed from the committed fixture (typed curve input
  through MarketDataRequest is open item OI-5, so the request's market_data
  carries only the pricing date here);
* request parameters taken from tests/fixtures/bloomberg_irs/cases/TC1.json,
  except the lookback, which comes from the Bloomberg source (0, open item OI-3).

The service path must reproduce the recorded reconciliation baseline exactly; the
Bloomberg differences are the documented OI-1 values. Baseline and known
differences are imported from test_tc1_bloomberg_reconciliation.py so there is a
single source for them.
"""

from __future__ import annotations

import copy
from datetime import date

import pytest
import QuantLib as ql
from test_tc1_bloomberg_reconciliation import BASELINE, KNOWN_DIFFERENCES

from api.v1.helpers import build_instrument_from_request
from api.v1.schemas import InstrumentRequest, MarketDataRequest, PricingRequest, UnderlyingData
from core.exceptions.errors import PricingError
from core.interfaces.base import MarketEnvironment
from core.types.value_objects import PricingDate
from engines.analytic.irs_discounting_engine import FreshIRSDiscountingEngine
from instruments.rates.irs.pricing_instrument import (
    FreshOISInstrument,
    InvalidIRSParameters,
)
from market.curves.irs_market_environment import build_single_curve_irs_environment
from market.curves.irs_zero_curve import build_zero_curve
from registry import engine_registry, instrument_registry
from services.pricers.pricing_service import PricingService

VALUATION_DATE = date(2026, 3, 31)


def _tc1_params(case: dict, source: dict) -> dict:
    """Request params from the canonical case; lookback from the Bloomberg source."""
    trade = case["trade"]
    pay, receive = trade["pay_leg"], trade["receive_leg"]
    periods = [
        {
            "accrual_start": row["period_start"],
            "accrual_end": row["period_end"],
            "payment_date": payment_date,
            "notional": row["notional"],
        }
        for row, payment_date in zip(
            trade["amortization_source"]["period_notionals"],
            case["schedule_inputs"]["receive_leg"]["payment_dates"],
        )
    ]
    observation = receive["observation"]
    return {
        "trade_id": trade["trade_id"],
        "currency": trade["currency"],
        "valuation_date": trade["valuation_date"],
        "effective_date": trade["effective_date"],
        "maturity_date": trade["maturity_date"],
        "fixed_leg_side": "pay",
        "fixed_leg": {
            "day_count": pay["day_count"],
            "payment_frequency": pay["payment_frequency"].lower(),
            "fixed_rate": pay["fixed_coupon"]["value"] / 100.0,
            "periods": copy.deepcopy(periods),
        },
        "floating_leg": {
            "day_count": receive["day_count"],
            "payment_frequency": receive["payment_frequency"].lower(),
            "benchmark": "SOFRRATE",
            "benchmark_tenor": receive["benchmark_tenor"],
            "spread": receive["floating_spread"]["value"] / 10000.0,
            "leverage": receive["leverage"],
            "reset_frequency": receive["reset_frequency"].lower(),
            "observation": {
                "lookback_days": source["leg_2"]["days_before_accrual"],
                "cutoff_days": observation["cutoff_days"],
                "reset_timing": observation["reset_timing"],
                "compounding": observation["compounding"],
                "lookback_type": observation["lookback_type"],
            },
            "periods": copy.deepcopy(periods),
        },
    }


@pytest.fixture(scope="module")
def tc1_params(tc1_documents) -> dict:
    case, source, _ = tc1_documents
    return _tc1_params(case, source)


@pytest.fixture(scope="module")
def tc1_request(tc1_params) -> PricingRequest:
    return PricingRequest(
        instrument=InstrumentRequest(type="ois", params=tc1_params),
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


@pytest.fixture
def preserve_evaluation_date():
    previous = ql.Settings.instance().evaluationDate
    yield
    ql.Settings.instance().evaluationDate = previous


@pytest.fixture(scope="module")
def service_run(tc1_request, usd_sofr_environment):
    """Price once through the service, capturing the exact swap object it priced."""
    previous = ql.Settings.instance().evaluationDate
    try:
        instrument = build_instrument_from_request(tc1_request.instrument)
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
            model_type=tc1_request.model,
            engine_type=tc1_request.engine,
        )
        legs = instrument.leg_npvs()
        captured_npv = built_swaps[-1].NPV() if built_swaps else None
        return {
            "instrument": instrument,
            "result": result,
            "legs": legs,
            "built_swaps": built_swaps,
            "captured_npv": captured_npv,
        }
    finally:
        ql.Settings.instance().evaluationDate = previous


# --- wiring ------------------------------------------------------------------


def test_registry_resolves_fresh_classes_and_keeps_legacy_irs():
    from engines.analytic.rates_engines import DiscountingSwapEngine as LegacyEngine
    from instruments.rates.interest_rate_swap import InterestRateSwap

    assert instrument_registry.get("ois") is FreshOISInstrument
    assert engine_registry.get(("ois", "discounting")) is FreshIRSDiscountingEngine
    assert instrument_registry.get("irs") is InterestRateSwap
    assert engine_registry.get(("irs", "analytic")) is LegacyEngine
    assert engine_registry.get(("irs", "discounting")) is LegacyEngine


def test_request_builds_the_fresh_instrument(service_run):
    instrument = service_run["instrument"]
    assert type(instrument) is FreshOISInstrument
    assert instrument.trade.floating_terms.observation.lookback_days == 0  # OI-3
    assert instrument.trade.floating_terms.observation.cutoff_days == 1


def test_leg_npvs_come_from_the_swap_the_engine_priced(service_run):
    instrument, result = service_run["instrument"], service_run["result"]
    assert len(service_run["built_swaps"]) == 1
    assert instrument.last_built.quantlib_instrument is service_run["built_swaps"][0]
    assert service_run["captured_npv"] == result.npv
    legs = service_run["legs"]
    assert legs["fixed"] + legs["floating"] == pytest.approx(result.npv, abs=1e-9)
    assert result.engine_used == "discounting" and result.model_used == "analytical"
    assert result.currency == "USD"


# --- baseline and Bloomberg ----------------------------------------------------


def test_service_npvs_match_recorded_baseline(service_run):
    legs, result = service_run["legs"], service_run["result"]
    assert legs["fixed"] == pytest.approx(BASELINE["fixed_leg_npv"], abs=1e-6)
    assert legs["floating"] == pytest.approx(BASELINE["floating_leg_npv"], abs=1e-6)
    assert result.npv == pytest.approx(BASELINE["npv"], abs=1e-6)


def test_service_differences_vs_bloomberg_are_the_documented_ones(service_run, tc1_documents):
    _, _, reference = tc1_documents
    bloomberg = {item["name"]: item["value"] for item in reference["outputs"]}
    legs, result = service_run["legs"], service_run["result"]
    observed = {
        "fixed_leg_npv": legs["fixed"] - bloomberg["fixed_leg_npv"],
        "floating_leg_npv": legs["floating"] - bloomberg["floating_leg_npv"],
        "npv": result.npv - bloomberg["total_npv"],
    }
    for metric, difference in observed.items():
        expected, tolerance = KNOWN_DIFFERENCES[metric]
        assert difference == pytest.approx(expected, abs=tolerance), metric


# --- explicit failures, no fallback --------------------------------------------


def _price(instrument, environment):
    return PricingService().price(
        instrument=instrument, market_env=environment, model_type="analytical",
        engine_type="discounting",
    )


def test_missing_discount_curve_fails(tc1_params, usd_sofr_environment, preserve_evaluation_date):
    environment = MarketEnvironment(
        pricing_date=PricingDate(VALUATION_DATE),
        forecast_curves=dict(usd_sofr_environment.forecast_curves),
    )
    with pytest.raises(PricingError, match="no discount curve for USD"):
        _price(FreshOISInstrument.from_dict(tc1_params), environment)


def test_missing_forecast_curve_fails(tc1_params, usd_sofr_environment, preserve_evaluation_date):
    environment = MarketEnvironment(
        pricing_date=PricingDate(VALUATION_DATE),
        discount_curves=dict(usd_sofr_environment.discount_curves),
    )
    with pytest.raises(PricingError, match="no forecast curve for USD"):
        _price(FreshOISInstrument.from_dict(tc1_params), environment)


def test_no_fallback_to_another_currency(
    tc1_params, usd_sofr_environment, preserve_evaluation_date
):
    handle = usd_sofr_environment.discount_curves["USD"]
    environment = MarketEnvironment(
        pricing_date=PricingDate(VALUATION_DATE),
        discount_curves={"EUR": handle},
        forecast_curves={"EUR": handle},
    )
    with pytest.raises(PricingError, match="for USD"):
        _price(FreshOISInstrument.from_dict(tc1_params), environment)


def test_engine_requires_the_fresh_instrument(usd_sofr_environment):
    with pytest.raises(TypeError, match="FreshOISInstrument"):
        FreshIRSDiscountingEngine().build(None, usd_sofr_environment)


def test_leg_npvs_require_a_build(tc1_params):
    with pytest.raises(RuntimeError, match="not been built"):
        FreshOISInstrument.from_dict(tc1_params).leg_npvs()


def test_environment_helper_rejects_mismatched_pricing_date(
    usd_sofr_market_data, usd_sofr_curve_conventions
):
    curve = build_zero_curve(usd_sofr_market_data, usd_sofr_curve_conventions)
    with pytest.raises(ValueError, match="does not match pricing date"):
        build_single_curve_irs_environment(date(2026, 4, 1), curve)


# --- parameter validation --------------------------------------------------------


def _mutate(params, path, value=..., delete=False):
    params = copy.deepcopy(params)
    target = params
    for key in path[:-1]:
        target = target[key]
    if delete:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return params


@pytest.mark.parametrize(
    "path, value, delete, message",
    [
        (("currency",), None, True, "missing required keys"),
        (("floating_leg", "observation", "lookback_days"), None, True, "missing required keys"),
        (("fixed_leg", "periods", 0, "notional"), None, True, "missing required keys"),
        (("unexpected",), 1, False, "unknown keys"),
        (("fixed_leg", "fixed_rate"), 5.0, False, "percentage"),
        (("floating_leg", "spread"), 10, False, "percentage"),
        (("fixed_leg_side",), "both", False, "fixed_leg_side"),
        (("fixed_leg", "day_count"), "ACT/ACT", False, "day_count"),
        (("floating_leg", "reset_frequency"), "weekly", False, "reset_frequency"),
        (("floating_leg", "observation", "lookback_days"), 0.0, False, "integer"),
        (("floating_leg", "observation", "cutoff_days"), True, False, "integer"),
        (("effective_date",), "31-05-2026", False, "invalid ISO date"),
        (("fixed_leg", "periods"), [], False, "non-empty list"),
        (("fixed_leg", "periods", 1, "notional"), 0, False, "positive"),
        (("maturity_date",), "2027-12-01", False, "end on the maturity_date"),
    ],
)
def test_invalid_parameters_fail_explicitly(tc1_params, path, value, delete, message):
    params = _mutate(tc1_params, path, value, delete)
    with pytest.raises(InvalidIRSParameters, match=message):
        FreshOISInstrument.from_dict(params)


def test_constructor_requires_a_typed_trade():
    with pytest.raises(TypeError, match="FreshOISTrade"):
        FreshOISInstrument({"trade_id": "x"})  # type: ignore[arg-type]


def test_invalid_request_params_do_not_build_an_instrument(tc1_params):
    # build_instrument_from_request swallows from_dict errors and retries with the
    # constructor; FreshOISInstrument's constructor then refuses untyped input.
    bad = _mutate(tc1_params, ("fixed_leg", "fixed_rate"), 5.0)
    with pytest.raises(TypeError):
        build_instrument_from_request(InstrumentRequest(type="ois", params=bad))
