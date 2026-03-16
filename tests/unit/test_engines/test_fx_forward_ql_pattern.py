"""
Step 2 — Failing tests for the QL instrument/engine separation refactor.

These tests define the TARGET interface. They will all FAIL until Step 3–5
are complete. Do not modify these tests to make them pass — modify the
implementation instead.

Target design:
  FXForward.setupArguments(args)   — populates FXForwardArguments from trade data
  FXForwardArguments               — typed inputs the engine needs
  FXForwardResults                 — typed outputs from the engine
  FXForwardEngine.price()          — returns FXForwardResults (not PricingResult)
  PricingService.price()           — diagnostics include forward_rate + disc_factor
"""

from __future__ import annotations

import registry.bootstrap  # noqa: F401 — ensures registries are populated before tests run

import math
from datetime import date, timedelta

import pytest

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

PRICING_DATE  = date(2025, 3, 15)
DELIVERY_DATE = date(2026, 3, 15)
SPOT          = 85.47
R_D           = 0.065
R_F           = 0.045
STRIKE        = 86.0
NOTIONAL      = 1_000_000.0
CCY_PAIR      = "USDINR"

T_EXPECTED = 365 / 365  # Actual365Fixed, non-leap year


def _expected_forward(spot=SPOT, r_d=R_D, r_f=R_F, T=1.0):
    return spot * math.exp((r_d - r_f) * T)


def _expected_df(r_d=R_D, T=1.0):
    return math.exp(-r_d * T)


def _make_instrument():
    """Build an FXForward using the existing instrument factory."""
    from api.v1.helpers import build_instrument_from_request
    from api.v1.schemas import InstrumentRequest

    req = InstrumentRequest(
        type="fx_forward",
        params={
            "ccy_pair":       CCY_PAIR,
            "strike":         STRIKE,
            "delivery_date":  DELIVERY_DATE.isoformat(),
            "notional":       NOTIONAL,
            "direction":      "buy",
        },
    )
    return build_instrument_from_request(req)


def _make_market_env(r_d=R_D, r_f=R_F, spot=SPOT, pricing_date=PRICING_DATE):
    """Build a MarketEnvironment using the existing helper."""
    from api.v1.helpers import build_market_env_from_request
    from api.v1.schemas import MarketDataRequest, UnderlyingData

    md = MarketDataRequest(
        pricing_date=pricing_date.isoformat(),
        underlyings={CCY_PAIR: UnderlyingData(spot=spot, vol=0.0)},
        rate_curve=[{"tenor": "1Y", "rate": r_d}],
        foreign_rate=r_f,
    )
    return build_market_env_from_request(md, underlying=CCY_PAIR)


def _make_engine():
    from engines.analytic.fx_engines import FXForwardEngine
    return FXForwardEngine()


# ===========================================================================
# CLASS 1 — FXForwardArguments must exist and be a typed dataclass
# ===========================================================================

class TestFXForwardArguments:
    """FXForwardArguments is the typed input container for the engine."""

    def test_arguments_class_exists(self):
        """FXForwardArguments must be importable from fx_engines."""
        from engines.analytic.fx_engines import FXForwardArguments  # noqa: F401

    def test_arguments_has_strike(self):
        from engines.analytic.fx_engines import FXForwardArguments
        args = FXForwardArguments()
        assert hasattr(args, "strike")

    def test_arguments_has_notional(self):
        from engines.analytic.fx_engines import FXForwardArguments
        args = FXForwardArguments()
        assert hasattr(args, "notional")

    def test_arguments_has_delivery_date(self):
        from engines.analytic.fx_engines import FXForwardArguments
        args = FXForwardArguments()
        assert hasattr(args, "delivery_date")

    def test_arguments_has_direction(self):
        from engines.analytic.fx_engines import FXForwardArguments
        args = FXForwardArguments()
        assert hasattr(args, "direction")

    def test_arguments_has_ccy_pair(self):
        from engines.analytic.fx_engines import FXForwardArguments
        args = FXForwardArguments()
        assert hasattr(args, "ccy_pair")

    def test_arguments_fields_are_mutable(self):
        """Engine must be able to set fields after construction."""
        from engines.analytic.fx_engines import FXForwardArguments
        args = FXForwardArguments()
        args.strike        = STRIKE
        args.notional      = NOTIONAL
        args.delivery_date = DELIVERY_DATE
        args.direction     = "buy"
        args.ccy_pair      = CCY_PAIR
        assert args.strike    == STRIKE
        assert args.notional  == NOTIONAL
        assert args.direction == "buy"


# ===========================================================================
# CLASS 2 — FXForwardResults must exist and be a typed dataclass
# ===========================================================================

class TestFXForwardResults:
    """FXForwardResults is the typed output container from the engine."""

    def test_results_class_exists(self):
        from engines.analytic.fx_engines import FXForwardResults  # noqa: F401

    def test_results_has_npv(self):
        from engines.analytic.fx_engines import FXForwardResults
        r = FXForwardResults()
        assert hasattr(r, "npv")

    def test_results_has_forward_rate(self):
        from engines.analytic.fx_engines import FXForwardResults
        r = FXForwardResults()
        assert hasattr(r, "forward_rate")

    def test_results_has_disc_factor(self):
        from engines.analytic.fx_engines import FXForwardResults
        r = FXForwardResults()
        assert hasattr(r, "disc_factor")

    def test_results_has_error(self):
        """Results must carry an optional error message."""
        from engines.analytic.fx_engines import FXForwardResults
        r = FXForwardResults()
        assert hasattr(r, "error")

    def test_results_defaults_npv_to_none(self):
        """Unpriced results should have npv=None, not a stale value."""
        from engines.analytic.fx_engines import FXForwardResults
        r = FXForwardResults()
        assert r.npv is None

    def test_results_defaults_error_to_none(self):
        from engines.analytic.fx_engines import FXForwardResults
        r = FXForwardResults()
        assert r.error is None


# ===========================================================================
# CLASS 3 — FXForward.setupArguments() must populate FXForwardArguments
# ===========================================================================

class TestSetupArguments:
    """FXForward must expose setupArguments() to transfer trade data to args."""

    def test_setup_arguments_method_exists(self):
        instrument = _make_instrument()
        assert hasattr(instrument, "setupArguments"), (
            "FXForward must have a setupArguments() method"
        )

    def test_setup_arguments_is_callable(self):
        instrument = _make_instrument()
        assert callable(instrument.setupArguments)

    def test_setup_arguments_populates_strike(self):
        from engines.analytic.fx_engines import FXForwardArguments
        instrument = _make_instrument()
        args = FXForwardArguments()
        instrument.setupArguments(args)
        assert args.strike == STRIKE

    def test_setup_arguments_populates_notional(self):
        from engines.analytic.fx_engines import FXForwardArguments
        instrument = _make_instrument()
        args = FXForwardArguments()
        instrument.setupArguments(args)
        assert args.notional == NOTIONAL

    def test_setup_arguments_populates_delivery_date(self):
        from engines.analytic.fx_engines import FXForwardArguments
        instrument = _make_instrument()
        args = FXForwardArguments()
        instrument.setupArguments(args)
        assert args.delivery_date == DELIVERY_DATE

    def test_setup_arguments_populates_direction(self):
        from engines.analytic.fx_engines import FXForwardArguments
        instrument = _make_instrument()
        args = FXForwardArguments()
        instrument.setupArguments(args)
        assert args.direction == "buy"

    def test_setup_arguments_populates_ccy_pair(self):
        from engines.analytic.fx_engines import FXForwardArguments
        instrument = _make_instrument()
        args = FXForwardArguments()
        instrument.setupArguments(args)
        assert args.ccy_pair == CCY_PAIR

    def test_setup_arguments_sell_direction(self):
        """Sell direction must propagate correctly."""
        from api.v1.helpers import build_instrument_from_request
        from api.v1.schemas import InstrumentRequest
        from engines.analytic.fx_engines import FXForwardArguments

        req = InstrumentRequest(
            type="fx_forward",
            params={
                "ccy_pair": CCY_PAIR, "strike": STRIKE,
                "delivery_date": DELIVERY_DATE.isoformat(),
                "notional": NOTIONAL, "direction": "sell",
            },
        )
        instrument = build_instrument_from_request(req)
        args = FXForwardArguments()
        instrument.setupArguments(args)
        assert args.direction == "sell"


# ===========================================================================
# CLASS 4 — FXForwardEngine.price() must return FXForwardResults
# ===========================================================================

class TestEngineReturnsResults:
    """engine.price() must return a typed FXForwardResults, not PricingResult."""

    def test_price_returns_fx_forward_results_type(self):
        from engines.analytic.fx_engines import FXForwardResults
        engine      = _make_engine()
        instrument  = _make_instrument()
        market_env  = _make_market_env()
        result      = engine.price(instrument, market_env)
        assert isinstance(result, FXForwardResults), (
            f"engine.price() must return FXForwardResults, got {type(result)}"
        )

    def test_price_result_has_npv(self):
        from engines.analytic.fx_engines import FXForwardResults
        engine     = _make_engine()
        instrument = _make_instrument()
        market_env = _make_market_env()
        result     = engine.price(instrument, market_env)
        assert result.npv is not None

    def test_price_result_npv_matches_formula(self):
        engine     = _make_engine()
        instrument = _make_instrument()
        market_env = _make_market_env()
        result     = engine.price(instrument, market_env)

        F   = _expected_forward()
        DF  = _expected_df()
        expected = NOTIONAL * (F - STRIKE) * DF * 1.0  # buy
        assert abs(result.npv - expected) < 1.0, (
            f"NPV {result.npv:.2f} does not match formula {expected:.2f}"
        )

    def test_price_result_has_forward_rate(self):
        engine     = _make_engine()
        instrument = _make_instrument()
        market_env = _make_market_env()
        result     = engine.price(instrument, market_env)
        assert result.forward_rate is not None, "forward_rate must be populated in results"

    def test_price_result_forward_rate_matches_formula(self):
        engine     = _make_engine()
        instrument = _make_instrument()
        market_env = _make_market_env()
        result     = engine.price(instrument, market_env)
        expected_F = _expected_forward()
        assert abs(result.forward_rate - expected_F) < 0.01, (
            f"forward_rate {result.forward_rate:.4f} != formula {expected_F:.4f}"
        )

    def test_price_result_has_disc_factor(self):
        engine     = _make_engine()
        instrument = _make_instrument()
        market_env = _make_market_env()
        result     = engine.price(instrument, market_env)
        assert result.disc_factor is not None, "disc_factor must be populated in results"

    def test_price_result_disc_factor_matches_formula(self):
        engine     = _make_engine()
        instrument = _make_instrument()
        market_env = _make_market_env()
        result     = engine.price(instrument, market_env)
        expected_DF = _expected_df()
        assert abs(result.disc_factor - expected_DF) < 0.0001, (
            f"disc_factor {result.disc_factor:.6f} != formula {expected_DF:.6f}"
        )

    def test_price_expired_deal_returns_zero_npv(self):
        """Expired deals must return npv=0.0 via engine, not raise."""
        engine     = _make_engine()
        instrument = _make_instrument()
        market_env = _make_market_env(pricing_date=date(2027, 1, 1))
        result     = engine.price(instrument, market_env)
        assert result.npv == 0.0

    def test_price_sell_direction_npv_is_negative_of_buy(self):
        from api.v1.helpers import build_instrument_from_request
        from api.v1.schemas import InstrumentRequest

        def _make_sell():
            req = InstrumentRequest(
                type="fx_forward",
                params={
                    "ccy_pair": CCY_PAIR, "strike": STRIKE,
                    "delivery_date": DELIVERY_DATE.isoformat(),
                    "notional": NOTIONAL, "direction": "sell",
                },
            )
            return build_instrument_from_request(req)

        engine     = _make_engine()
        market_env = _make_market_env()
        buy_result  = engine.price(_make_instrument(), market_env)
        sell_result = engine.price(_make_sell(), market_env)
        assert abs(buy_result.npv + sell_result.npv) < 0.01, (
            "buy NPV + sell NPV must equal zero"
        )


# ===========================================================================
# CLASS 5 — PricingService must surface forward_rate + disc_factor
# ===========================================================================

class TestPricingServiceDiagnostics:
    """
    PricingService.price() must include forward_rate and disc_factor
    in its diagnostics dict so the API and bulk upload can surface them.
    """

    def _price_via_service(self, direction="buy"):
        from api.v1.helpers import build_instrument_from_request, build_market_env_from_request
        from api.v1.schemas import InstrumentRequest, MarketDataRequest, UnderlyingData
        from services.pricers.pricing_service import PricingService

        req = InstrumentRequest(
            type="fx_forward",
            params={
                "ccy_pair": CCY_PAIR, "strike": STRIKE,
                "delivery_date": DELIVERY_DATE.isoformat(),
                "notional": NOTIONAL, "direction": direction,
            },
        )
        md = MarketDataRequest(
            pricing_date=PRICING_DATE.isoformat(),
            underlyings={CCY_PAIR: UnderlyingData(spot=SPOT, vol=0.0)},
            rate_curve=[{"tenor": "1Y", "rate": R_D}],
            foreign_rate=R_F,
        )
        instrument = build_instrument_from_request(req)
        market_env = build_market_env_from_request(md, underlying=CCY_PAIR)
        return PricingService().price(
            instrument, market_env,
            model_type="black_scholes", engine_type="analytic",
        )

    def test_service_result_has_diagnostics(self):
        result = self._price_via_service()
        assert result.diagnostics is not None

    def test_service_diagnostics_has_forward_rate(self):
        result = self._price_via_service()
        assert "forward_rate" in result.diagnostics, (
            "PricingService diagnostics must include forward_rate"
        )

    def test_service_diagnostics_has_disc_factor(self):
        result = self._price_via_service()
        assert "disc_factor" in result.diagnostics, (
            "PricingService diagnostics must include disc_factor"
        )

    def test_service_diagnostics_forward_rate_matches_formula(self):
        result     = self._price_via_service()
        expected_F = _expected_forward()
        fwd        = result.diagnostics["forward_rate"]
        assert abs(fwd - expected_F) < 0.01, (
            f"diagnostics forward_rate {fwd:.4f} != formula {expected_F:.4f}"
        )

    def test_service_diagnostics_disc_factor_matches_formula(self):
        result      = self._price_via_service()
        expected_DF = _expected_df()
        df          = result.diagnostics["disc_factor"]
        assert abs(df - expected_DF) < 0.0001, (
            f"diagnostics disc_factor {df:.6f} != formula {expected_DF:.6f}"
        )