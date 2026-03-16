"""
Unit tests for FX Forward pricing via PricingService.

Tests the full service stack:
    PricingService.price(instrument, market_env) → PricingResult

Builds instrument and market_env via helpers (same path as production)
to ensure the integration between FXForward and PricingService is correct.
"""

from __future__ import annotations

import math
import pytest
from datetime import date

from core.types.value_objects import PricingDate
from api.v1.helpers import build_instrument_from_request, build_market_env_from_request
from api.v1.schemas import InstrumentRequest, MarketDataRequest, UnderlyingData
from services.pricers.pricing_service import PricingService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PRICING_DATE = "2025-03-15"
DELIVERY_DATE = "2026-03-15"
SPOT = 85.47
STRIKE = 86.0
NOTIONAL = 1_000_000.0
CCY_PAIR = "USDINR"
R_D = 0.065
R_F = 0.045


def _make_requests(
    direction: str = "buy",
    strike: float = STRIKE,
    notional: float = NOTIONAL,
    spot: float = SPOT,
    r_d: float = R_D,
    r_f: float = R_F,
    vol: float = 0.0,
    pricing_date: str = PRICING_DATE,
    delivery_date: str = DELIVERY_DATE,
):
    inst_req = InstrumentRequest(
        type="fx_forward",
        params={
            "ccy_pair": CCY_PAIR,
            "strike": strike,
            "delivery_date": delivery_date,
            "notional": notional,
            "direction": direction,
        },
    )
    md_req = MarketDataRequest(
        pricing_date=pricing_date,
        underlyings={CCY_PAIR: UnderlyingData(spot=spot, vol=vol)},
        rate_curve=[{"tenor": "1Y", "rate": r_d}],
        foreign_rate=r_f,
    )
    return inst_req, md_req


def _price(inst_req, md_req):
    ps = PricingService()
    instrument  = build_instrument_from_request(inst_req)
    market_env  = build_market_env_from_request(md_req, underlying=CCY_PAIR)
    return ps.price(instrument, market_env, model_type="black_scholes", engine_type="analytic")


# ---------------------------------------------------------------------------
# NPV formula correctness
# ---------------------------------------------------------------------------

class TestNPVFormulaService:

    def test_npv_matches_formula(self):
        """Service NPV must match closed-form formula."""
        inst_req, md_req = _make_requests(direction="buy")
        result = _price(inst_req, md_req)

        T = 1.0
        F  = SPOT * math.exp((R_D - R_F) * T)
        DF = math.exp(-R_D * T)
        expected = NOTIONAL * (F - STRIKE) * DF

        assert abs(result.npv - expected) < 1.0

    def test_buy_sell_sum_to_zero(self):
        buy_req,  md = _make_requests(direction="buy")
        sell_req, _  = _make_requests(direction="sell")

        npv_buy  = _price(buy_req,  md).npv
        npv_sell = _price(sell_req, md).npv

        assert abs(npv_buy + npv_sell) < 1e-6

    def test_result_has_trade_id(self):
        inst_req, md_req = _make_requests()
        result = _price(inst_req, md_req)
        assert result.trade_id is not None and result.trade_id != ""


# ---------------------------------------------------------------------------
# Zero rates
# ---------------------------------------------------------------------------

class TestZeroRatesService:

    def test_zero_rates_npv_independent_of_maturity(self):
        """r_d = r_f = 0 → NPV constant regardless of delivery date."""
        _, md_base = _make_requests(r_d=0.0, r_f=0.0)

        inst_1y, _ = _make_requests(r_d=0.0, r_f=0.0, delivery_date="2026-03-15")
        inst_2y, _ = _make_requests(r_d=0.0, r_f=0.0, delivery_date="2027-03-15")

        npv_1y = _price(inst_1y, md_base).npv
        npv_2y = _price(inst_2y, md_base).npv

        assert abs(npv_1y - npv_2y) < 1.0

    def test_zero_domestic_rate_no_discounting(self):
        """r_d = 0 → DF = 1, NPV = N × (F - K)."""
        inst_req, md_req = _make_requests(r_d=0.0, r_f=0.0, direction="buy")
        result = _price(inst_req, md_req)

        # F = S (zero differential), DF = 1
        expected = NOTIONAL * (SPOT - STRIKE) * 1.0
        assert abs(result.npv - expected) < 1.0


# ---------------------------------------------------------------------------
# Sign convention
# ---------------------------------------------------------------------------

class TestSignConventionService:

    def test_buy_positive_when_itm(self):
        """Strike well below forward → buy NPV positive."""
        T = 1.0
        F = SPOT * math.exp((R_D - R_F) * T)
        inst_req, md_req = _make_requests(direction="buy", strike=F - 2.0)
        assert _price(inst_req, md_req).npv > 0

    def test_sell_positive_when_strike_above_forward(self):
        """Strike well above forward → sell NPV positive."""
        T = 1.0
        F = SPOT * math.exp((R_D - R_F) * T)
        inst_req, md_req = _make_requests(direction="sell", strike=F + 2.0)
        assert _price(inst_req, md_req).npv > 0

    def test_buy_negative_when_otm(self):
        T = 1.0
        F = SPOT * math.exp((R_D - R_F) * T)
        inst_req, md_req = _make_requests(direction="buy", strike=F + 2.0)
        assert _price(inst_req, md_req).npv < 0


# ---------------------------------------------------------------------------
# Vol ignored
# ---------------------------------------------------------------------------

class TestVolIgnoredService:

    def test_vol_zero_vs_high_same_npv(self):
        """vol=0.0 and vol=0.5 must produce identical NPV through service."""
        inst_req, md_zero = _make_requests(vol=0.0)
        _,        md_high = _make_requests(vol=0.5)

        npv_zero = _price(inst_req, md_zero).npv
        npv_high = _price(inst_req, md_high).npv

        assert abs(npv_zero - npv_high) < 1e-6

    def test_default_vol_schema_ignored(self):
        """UnderlyingData.vol defaults to 0.20 — must not affect FX forward."""
        inst_req, md_default = _make_requests(vol=0.20)
        _,        md_zero    = _make_requests(vol=0.0)

        assert abs(_price(inst_req, md_default).npv - _price(inst_req, md_zero).npv) < 1e-6


# ---------------------------------------------------------------------------
# Expired deal
# ---------------------------------------------------------------------------

class TestExpiredDealService:

    def test_expired_delivery_date_npv_zero(self):
        """Delivery date before pricing date → NPV = 0."""
        inst_req, md_req = _make_requests(delivery_date="2024-01-01")
        result = _price(inst_req, md_req)
        assert result.npv == 0.0

    def test_same_day_delivery_npv_zero(self):
        """Delivery date = pricing date → NPV = 0."""
        inst_req, md_req = _make_requests(delivery_date=PRICING_DATE)
        result = _price(inst_req, md_req)
        assert result.npv == 0.0