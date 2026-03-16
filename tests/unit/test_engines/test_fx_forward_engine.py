"""
Unit tests for FXForward — engine level.

Tests the pure formula:
    F   = S × exp((r_d - r_f) × T)
    DF  = exp(-r_d × T)
    NPV = Notional × (F - K) × DF × sign   (sign: buy=+1, sell=-1)

Note: FXForward.build() returns a QL Instrument which requires a pricing engine
to call .NPV() directly. We go through PricingService to attach the engine —
this is the correct call path and does not affect what we're testing (the formula).
"""

from __future__ import annotations

import math
import pytest
from datetime import date

from api.v1.helpers import build_instrument_from_request, build_market_env_from_request
from api.v1.schemas import InstrumentRequest, MarketDataRequest, UnderlyingData
from services.pricers.pricing_service import PricingService


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PRICING_DATE  = "2025-03-15"
DELIVERY_DATE = "2026-03-15"
SPOT     = 85.47
STRIKE   = 86.0
NOTIONAL = 1_000_000.0
CCY_PAIR = "USDINR"
R_D = 0.065
R_F = 0.045


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _price(
    direction="buy",
    strike=STRIKE,
    notional=NOTIONAL,
    spot=SPOT,
    r_d=R_D,
    r_f=R_F,
    vol=0.0,
    delivery_date=DELIVERY_DATE,
    pricing_date=PRICING_DATE,
) -> float:
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
    ps = PricingService()
    instrument = build_instrument_from_request(inst_req)
    market_env = build_market_env_from_request(md_req, underlying=CCY_PAIR)
    return ps.price(instrument, market_env, model_type="black_scholes", engine_type="analytic").npv


def _formula_npv(spot, strike, notional, r_d, r_f, T, direction) -> float:
    """Closed-form expected NPV."""
    F  = spot * math.exp((r_d - r_f) * T)
    DF = math.exp(-r_d * T)
    sign = 1.0 if direction.lower() in ("buy", "long") else -1.0
    return notional * (F - strike) * DF * sign


# ---------------------------------------------------------------------------
# NPV formula correctness
# ---------------------------------------------------------------------------

class TestNPVFormula:

    def test_buy_npv_matches_formula(self):
        npv = _price(direction="buy")
        T = 1.0
        expected = _formula_npv(SPOT, STRIKE, NOTIONAL, R_D, R_F, T, "buy")
        assert abs(npv - expected) < 1.0   # within 1 INR on 1M notional

    def test_sell_npv_matches_formula(self):
        npv = _price(direction="sell")
        T = 1.0
        expected = _formula_npv(SPOT, STRIKE, NOTIONAL, R_D, R_F, T, "sell")
        assert abs(npv - expected) < 1.0

    def test_atm_forward_npv_near_zero(self):
        """Strike = forward rate → NPV ≈ 0."""
        T = 1.0
        atm_strike = SPOT * math.exp((R_D - R_F) * T)
        npv = _price(direction="buy", strike=atm_strike)
        assert abs(npv) < 1.0

    def test_higher_strike_reduces_buy_npv(self):
        npv_low  = _price(direction="buy", strike=85.0)
        npv_high = _price(direction="buy", strike=87.0)
        assert npv_low > npv_high

    def test_larger_notional_scales_npv_linearly(self):
        npv_1m = _price(notional=1_000_000)
        npv_2m = _price(notional=2_000_000)
        assert abs(npv_2m - 2 * npv_1m) < 1e-4


# ---------------------------------------------------------------------------
# Zero rates — F = S, DF = 1
# ---------------------------------------------------------------------------

class TestZeroRates:

    def test_zero_both_rates_npv_matches_formula(self):
        """r_d = r_f = 0 → F = S, DF = 1, NPV = N × (S - K)."""
        npv = _price(direction="buy", r_d=0.0, r_f=0.0)
        expected = NOTIONAL * (SPOT - STRIKE) * 1.0
        assert abs(npv - expected) < 1.0

    def test_zero_rates_npv_constant_across_maturities(self):
        """r_d = r_f = 0 → NPV must not change with maturity."""
        npv_1y = _price(r_d=0.0, r_f=0.0, delivery_date="2026-03-15")
        npv_2y = _price(r_d=0.0, r_f=0.0, delivery_date="2027-03-15")
        npv_5y = _price(r_d=0.0, r_f=0.0, delivery_date="2030-03-15")
        assert abs(npv_1y - npv_2y) < 1.0
        assert abs(npv_1y - npv_5y) < 1.0

    def test_equal_rates_forward_equals_spot(self):
        """r_d = r_f (any value) → F = S."""
        T = 1.0
        r = 0.05
        npv = _price(direction="buy", r_d=r, r_f=r)
        expected = NOTIONAL * (SPOT - STRIKE) * math.exp(-r * T)
        assert abs(npv - expected) < 1.0


# ---------------------------------------------------------------------------
# Sign convention
# ---------------------------------------------------------------------------

class TestSignConvention:

    def test_buy_positive_when_forward_above_strike(self):
        T = 1.0
        F = SPOT * math.exp((R_D - R_F) * T)
        assert _price(direction="buy", strike=F - 1.0) > 0

    def test_sell_positive_when_forward_below_strike(self):
        T = 1.0
        F = SPOT * math.exp((R_D - R_F) * T)
        assert _price(direction="sell", strike=F + 1.0) > 0

    def test_buy_negative_when_forward_below_strike(self):
        T = 1.0
        F = SPOT * math.exp((R_D - R_F) * T)
        assert _price(direction="buy", strike=F + 1.0) < 0

    def test_sell_negative_when_forward_above_strike(self):
        T = 1.0
        F = SPOT * math.exp((R_D - R_F) * T)
        assert _price(direction="sell", strike=F - 1.0) < 0

    def test_buy_sell_sum_to_zero(self):
        npv_buy  = _price(direction="buy")
        npv_sell = _price(direction="sell")
        assert abs(npv_buy + npv_sell) < 1e-6


# ---------------------------------------------------------------------------
# Vol ignored
# ---------------------------------------------------------------------------

class TestVolIgnored:

    def test_vol_zero_and_nonzero_give_same_npv(self):
        npv_0    = _price(vol=0.0)
        npv_low  = _price(vol=0.10)
        npv_high = _price(vol=0.50)
        assert abs(npv_0 - npv_low)  < 1e-6
        assert abs(npv_0 - npv_high) < 1e-6

    def test_default_schema_vol_does_not_affect_npv(self):
        """UnderlyingData.vol defaults to 0.20 — must not affect FX forward."""
        assert abs(_price(vol=0.20) - _price(vol=0.0)) < 1e-6


# ---------------------------------------------------------------------------
# Expired deal
# ---------------------------------------------------------------------------

class TestExpiredDeal:

    def test_past_delivery_date_npv_is_zero(self):
        assert _price(delivery_date="2024-01-01") == 0.0

    def test_same_day_delivery_npv_is_zero(self):
        assert _price(delivery_date=PRICING_DATE) == 0.0

    def test_future_delivery_date_npv_nonzero(self):
        """Deep ITM forward — must not be zero."""
        assert _price(direction="buy", strike=80.0) != 0.0