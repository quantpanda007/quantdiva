"""Generic HTTP pricing endpoints must not price "ois" on flat test curves.

POST /api/v1/pricing/{single,batch,compare} build the market environment with
api.v1.helpers.build_market_env_from_request, which only creates flat test
curves. Before the guard, the TC1 request priced there at about +903.23 instead
of the fresh-IRS baseline of about -7,955.73. These tests check that:

* the real TC1 "ois" request is rejected with an actionable message on all three
  endpoints (batch reports it as that row's error);
* supported instrument requests (FX forward, vanilla option) are unaffected and
  still equal the same pricing done directly through the helpers;
* the library path (PricingService with a configured IRS environment) still
  prices TC1 at the recorded baseline.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from test_tc1_bloomberg_reconciliation import BASELINE as TC1_BASELINE
from test_tc1_pricing_service_e2e import _tc1_params

from api.app import app
from api.v1.helpers import (
    ConfiguredMarketEnvironmentRequired,
    build_instrument_from_request,
    build_market_env_from_request,
    ensure_flat_market_env_supported,
)
from api.v1.schemas import InstrumentRequest, MarketDataRequest
from instruments.rates.irs.pricing_instrument import FreshOISInstrument
from market.curves.irs_market_environment import build_single_curve_irs_environment
from services.pricers.pricing_service import PricingService

URL = "/api/v1/pricing"
GUARD_MESSAGE = "requires a configured IRS market environment"
OIS_MARKET_DATA = {"pricing_date": "2026-03-31", "underlyings": {"USD": {"spot": 1.0}}}

FX_FORWARD = {
    "instrument": {
        "type": "fx_forward",
        "params": {
            "ccy_pair": "USDINR",
            "strike": 86.0,
            "delivery_date": "2026-03-15",
            "notional": 1_000_000.0,
            "direction": "buy",
        },
    },
    "market_data": {
        "pricing_date": "2025-03-15",
        "underlyings": {"USDINR": {"spot": 85.47, "vol": 0.0}},
        "rate_curve": [{"tenor": "1Y", "rate": 0.065}],
        "foreign_rate": 0.045,
    },
    "model": "black_scholes",
    "engine": "analytic",
}

VANILLA = {
    "instrument": {
        "type": "vanilla_option",
        "params": {
            "trade_id": "VAN-001",
            "underlying": "AAPL",
            "strike": 150.0,
            "expiry": "2026-01-15",
            "option_type": "call",
            "exercise_type": "european",
            "currency": "USD",
        },
    },
    "market_data": {
        "pricing_date": "2025-01-15",
        "underlyings": {"AAPL": {"spot": 155.0, "vol": 0.25}},
        "rate": 0.05,
    },
    "model": "black_scholes",
    "engine": "analytic",
}


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def ois_instrument(tc1_documents) -> dict:
    case, source, _ = tc1_documents
    return {"type": "ois", "params": _tc1_params(case, source)}


def _direct_npv(payload: dict) -> float:
    """Price exactly as the endpoint does, without HTTP, for comparison."""
    instrument = build_instrument_from_request(InstrumentRequest(**payload["instrument"]))
    market_data = MarketDataRequest(**payload["market_data"])
    underlying = getattr(instrument, "underlying", None) or next(iter(market_data.underlyings))
    environment = build_market_env_from_request(market_data, underlying=underlying)
    return PricingService().price(
        instrument=instrument,
        market_env=environment,
        model_type=payload["model"],
        engine_type=payload["engine"],
    ).npv


# --- the guard itself ----------------------------------------------------------------


def test_guard_rejects_ois_only():
    with pytest.raises(ConfiguredMarketEnvironmentRequired, match=GUARD_MESSAGE):
        ensure_flat_market_env_supported("ois")
    for supported in ("fx_forward", "vanilla_option", "irs"):
        ensure_flat_market_env_supported(supported)  # no exception


# --- unsafe OIS request is rejected -------------------------------------------------


def test_single_rejects_ois(client, ois_instrument):
    response = client.post(
        f"{URL}/single",
        json={
            "instrument": ois_instrument,
            "market_data": OIS_MARKET_DATA,
            "model": "analytical",
            "engine": "discounting",
        },
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "'ois'" in detail and GUARD_MESSAGE in detail
    assert "build_single_curve_irs_environment" in detail
    assert "npv" not in response.json()


def test_batch_reports_ois_as_a_row_error(client, ois_instrument):
    response = client.post(
        f"{URL}/batch",
        json={
            "instruments": [FX_FORWARD["instrument"], ois_instrument],
            "market_data": OIS_MARKET_DATA,
            "model": "analytical",
            "engine": "discounting",
        },
    )
    assert response.status_code == 200
    ois_row = response.json()["results"][1]
    assert ois_row["npv"] is None
    assert GUARD_MESSAGE in ois_row["diagnostics"]["error"]


def test_compare_rejects_ois(client, ois_instrument):
    response = client.post(
        f"{URL}/compare",
        json={
            "instrument": ois_instrument,
            "market_data": OIS_MARKET_DATA,
            "model": "analytical",
            "engines": ["discounting"],
        },
    )
    assert response.status_code == 400
    assert GUARD_MESSAGE in response.json()["detail"]


# --- supported requests are unaffected ----------------------------------------------


@pytest.mark.parametrize("payload", [FX_FORWARD, VANILLA], ids=["fx_forward", "vanilla_option"])
def test_supported_single_requests_unchanged(client, payload):
    response = client.post(f"{URL}/single", json=payload)
    assert response.status_code == 200
    assert response.json()["npv"] == pytest.approx(_direct_npv(payload), abs=1e-9)


def test_supported_batch_request_unchanged(client):
    response = client.post(
        f"{URL}/batch",
        json={
            "instruments": [FX_FORWARD["instrument"]],
            "market_data": FX_FORWARD["market_data"],
            "model": "black_scholes",
            "engine": "analytic",
        },
    )
    assert response.status_code == 200
    row = response.json()["results"][0]
    assert row["npv"] == pytest.approx(_direct_npv(FX_FORWARD), abs=1e-9)


# --- the library path is unaffected ---------------------------------------------------


def test_ois_still_prices_with_a_configured_environment(ois_instrument, usd_sofr_market_data,
                                                        usd_sofr_curve_conventions):
    from market.curves.irs_zero_curve import build_zero_curve

    curve = build_zero_curve(usd_sofr_market_data, usd_sofr_curve_conventions)
    environment = build_single_curve_irs_environment(date(2026, 3, 31), curve)
    instrument = build_instrument_from_request(InstrumentRequest(**ois_instrument))
    assert isinstance(instrument, FreshOISInstrument)
    result = PricingService().price(
        instrument=instrument,
        market_env=environment,
        model_type="analytical",
        engine_type="discounting",
    )
    assert result.npv == pytest.approx(TC1_BASELINE["npv"], abs=1e-6)
