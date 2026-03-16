"""
Integration tests for POST /api/v1/pricing/single — FX Forward.

Uses FastAPI TestClient — no running server needed.
"""

from __future__ import annotations

import math
import pytest
from fastapi.testclient import TestClient

from api.app import app

client = TestClient(app)

PRICING_DATE  = "2025-03-15"
DELIVERY_DATE = "2026-03-15"
SPOT     = 85.47
STRIKE   = 86.0
NOTIONAL = 1_000_000.0
CCY_PAIR = "USDINR"
R_D = 0.065
R_F = 0.045
URL = "/api/v1/pricing/single"


def _payload(
    direction: str = "buy",
    strike: float = STRIKE,
    notional: float = NOTIONAL,
    spot: float = SPOT,
    r_d: float = R_D,
    r_f: float = R_F,
    vol: float = 0.0,
    delivery_date: str = DELIVERY_DATE,
    pricing_date: str = PRICING_DATE,
):
    return {
        "instrument": {
            "type": "fx_forward",
            "params": {
                "ccy_pair": CCY_PAIR,
                "strike": strike,
                "delivery_date": delivery_date,
                "notional": notional,
                "direction": direction,
            },
        },
        "market_data": {
            "pricing_date": pricing_date,
            "underlyings": {CCY_PAIR: {"spot": spot, "vol": vol}},
            "rate_curve": [{"tenor": "1Y", "rate": r_d}],
            "foreign_rate": r_f,
        },
        "model": "black_scholes",
        "engine": "analytic",
    }


# ---------------------------------------------------------------------------
# NPV formula correctness
# ---------------------------------------------------------------------------

class TestNPVFormulaAPI:

    def test_200_response(self):
        resp = client.post(URL, json=_payload())
        assert resp.status_code == 200

    def test_response_has_npv(self):
        assert "npv" in client.post(URL, json=_payload()).json()

    def test_npv_matches_formula(self):
        resp = client.post(URL, json=_payload(direction="buy"))
        T = 1.0
        F  = SPOT * math.exp((R_D - R_F) * T)
        DF = math.exp(-R_D * T)
        expected = NOTIONAL * (F - STRIKE) * DF
        assert abs(resp.json()["npv"] - expected) < 1.0

    def test_buy_sell_sum_to_zero(self):
        npv_buy  = client.post(URL, json=_payload(direction="buy")).json()["npv"]
        npv_sell = client.post(URL, json=_payload(direction="sell")).json()["npv"]
        assert abs(npv_buy + npv_sell) < 1e-6


# ---------------------------------------------------------------------------
# Zero rates
# ---------------------------------------------------------------------------

class TestZeroRatesAPI:

    def test_zero_rates_npv_constant_across_maturities(self):
        npv_1y = client.post(URL, json=_payload(r_d=0.0, r_f=0.0, delivery_date="2026-03-15")).json()["npv"]
        npv_2y = client.post(URL, json=_payload(r_d=0.0, r_f=0.0, delivery_date="2027-03-15")).json()["npv"]
        assert abs(npv_1y - npv_2y) < 1.0

    def test_zero_rates_forward_equals_spot(self):
        """r_d = r_f = 0 → F = S, DF = 1 → NPV = N × (S - K)."""
        resp = client.post(URL, json=_payload(r_d=0.0, r_f=0.0, direction="buy"))
        expected = NOTIONAL * (SPOT - STRIKE) * 1.0
        assert abs(resp.json()["npv"] - expected) < 1.0


# ---------------------------------------------------------------------------
# Sign convention
# ---------------------------------------------------------------------------

class TestSignConventionAPI:

    def test_buy_itm_positive(self):
        T = 1.0
        F = SPOT * math.exp((R_D - R_F) * T)
        assert client.post(URL, json=_payload(direction="buy", strike=F - 2.0)).json()["npv"] > 0

    def test_sell_above_forward_positive(self):
        T = 1.0
        F = SPOT * math.exp((R_D - R_F) * T)
        assert client.post(URL, json=_payload(direction="sell", strike=F + 2.0)).json()["npv"] > 0

    def test_buy_otm_negative(self):
        T = 1.0
        F = SPOT * math.exp((R_D - R_F) * T)
        assert client.post(URL, json=_payload(direction="buy", strike=F + 2.0)).json()["npv"] < 0


# ---------------------------------------------------------------------------
# Vol ignored
# ---------------------------------------------------------------------------

class TestVolIgnoredAPI:

    def test_vol_zero_and_high_same_npv(self):
        npv_zero = client.post(URL, json=_payload(vol=0.0)).json()["npv"]
        npv_high = client.post(URL, json=_payload(vol=0.5)).json()["npv"]
        assert abs(npv_zero - npv_high) < 1e-6

    def test_default_vol_ignored(self):
        npv_default = client.post(URL, json=_payload(vol=0.20)).json()["npv"]
        npv_zero    = client.post(URL, json=_payload(vol=0.0)).json()["npv"]
        assert abs(npv_default - npv_zero) < 1e-6


# ---------------------------------------------------------------------------
# Expired deal
# ---------------------------------------------------------------------------

class TestExpiredDealAPI:

    def test_expired_returns_zero_npv(self):
        resp = client.post(URL, json=_payload(delivery_date="2024-01-01"))
        assert resp.status_code == 200
        assert resp.json()["npv"] == 0.0

    def test_same_day_delivery_zero_npv(self):
        resp = client.post(URL, json=_payload(delivery_date=PRICING_DATE))
        assert resp.status_code == 200
        assert resp.json()["npv"] == 0.0

    def test_invalid_date_returns_error(self):
        resp = client.post(URL, json=_payload(delivery_date="not-a-date"))
        assert resp.status_code in (400, 422)