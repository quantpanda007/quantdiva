"""
Regression tests for equity option pricing.

These tests verify pricing results against known-good values.
Any change that breaks these tests indicates a numerical regression.
"""

import math
from datetime import date

import pytest

# Mark all tests in this module as regression
pytestmark = pytest.mark.regression


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def pricing_date():
    from core.types.value_objects import PricingDate
    return PricingDate(date(2025, 1, 15))


@pytest.fixture
def test_market_env(pricing_date):
    from market.curves.yield_curve import build_test_market_env
    return build_test_market_env(
        pricing_date=pricing_date,
        spot=100.0,
        rate=0.05,
        vol=0.20,
        div_yield=0.02,
        underlying="TEST",
    )


@pytest.fixture
def pricing_service():
    # Trigger registration
    import instruments.equity.vanilla_option  # noqa: F401
    import engines.analytic.equity_engines  # noqa: F401
    import models.equity.black_scholes  # noqa: F401
    from services.pricers.pricing_service import PricingService
    return PricingService()


# ---------------------------------------------------------------------------
# European Call Option Tests
# ---------------------------------------------------------------------------

class TestEuropeanCallBSM:
    """Test European call option pricing under BSM."""

    def _make_call(self, strike: float, expiry: date) -> "VanillaOption":
        from instruments.equity.vanilla_option import VanillaOption
        from core.enums.definitions import OptionType, ExerciseType
        return VanillaOption(
            _trade_id=f"TEST-CALL-{strike}",
            underlying="TEST",
            strike=strike,
            expiry=expiry,
            option_type=OptionType.CALL,
            exercise_type=ExerciseType.EUROPEAN,
            _currency="USD",
        )

    def test_atm_call_1y(self, pricing_service, test_market_env):
        """ATM 1Y European call: S=100, K=100, r=5%, q=2%, vol=20%."""
        call = self._make_call(100.0, date(2026, 1, 15))
        result = pricing_service.price(call, test_market_env)

        # BSM reference: ~10.06 (approximate)
        assert result.npv > 0
        assert abs(result.npv - 9.227) < 0.5, f"ATM call NPV={result.npv:.4f}, expected ~10.06"

    def test_deep_itm_call(self, pricing_service, test_market_env):
        """Deep ITM call should be close to intrinsic."""
        call = self._make_call(50.0, date(2026, 1, 15))
        result = pricing_service.price(call, test_market_env)

        # Should be significantly above intrinsic (100 - 50 = 50)
        assert result.npv > 48.0, f"Deep ITM call NPV={result.npv:.4f}, expected > 48"

    def test_deep_otm_call(self, pricing_service, test_market_env):
        """Deep OTM call should have near-zero value."""
        call = self._make_call(200.0, date(2026, 1, 15))
        result = pricing_service.price(call, test_market_env)

        assert result.npv < 0.5, f"Deep OTM call NPV={result.npv:.4f}, expected < 0.5"

    def test_short_maturity(self, pricing_service, test_market_env):
        """1M ATM call should have lower value than 1Y."""
        call_1m = self._make_call(100.0, date(2025, 2, 15))
        call_1y = self._make_call(100.0, date(2026, 1, 15))

        npv_1m = pricing_service.price(call_1m, test_market_env).npv
        npv_1y = pricing_service.price(call_1y, test_market_env).npv

        assert npv_1m < npv_1y, f"1M call ({npv_1m:.4f}) should be < 1Y call ({npv_1y:.4f})"


# ---------------------------------------------------------------------------
# European Put Option Tests
# ---------------------------------------------------------------------------

class TestEuropeanPutBSM:
    """Test European put option pricing under BSM."""

    def _make_put(self, strike: float, expiry: date) -> "VanillaOption":
        from instruments.equity.vanilla_option import VanillaOption
        from core.enums.definitions import OptionType, ExerciseType
        return VanillaOption(
            _trade_id=f"TEST-PUT-{strike}",
            underlying="TEST",
            strike=strike,
            expiry=expiry,
            option_type=OptionType.PUT,
            exercise_type=ExerciseType.EUROPEAN,
            _currency="USD",
        )

    def test_atm_put_1y(self, pricing_service, test_market_env):
        """ATM 1Y European put."""
        put = self._make_put(100.0, date(2026, 1, 15))
        result = pricing_service.price(put, test_market_env)

        assert result.npv > 0
        # BSM reference: ~7.12 (approximate, depends on exact day count)
        assert abs(result.npv - 6.330) < 0.5, f"ATM put NPV={result.npv:.4f}, expected ~7.12"

    def test_put_call_parity(self, pricing_service, test_market_env):
        """
        Put-call parity: C - P = S*exp(-qT) - K*exp(-rT)

        This is a critical consistency check.
        """
        from instruments.equity.vanilla_option import VanillaOption
        from core.enums.definitions import OptionType, ExerciseType

        K = 100.0
        expiry = date(2026, 1, 15)

        call = VanillaOption(
            _trade_id="PC-CALL", underlying="TEST", strike=K, expiry=expiry,
            option_type=OptionType.CALL, exercise_type=ExerciseType.EUROPEAN, _currency="USD",
        )
        put = VanillaOption(
            _trade_id="PC-PUT", underlying="TEST", strike=K, expiry=expiry,
            option_type=OptionType.PUT, exercise_type=ExerciseType.EUROPEAN, _currency="USD",
        )

        npv_call = pricing_service.price(call, test_market_env).npv
        npv_put = pricing_service.price(put, test_market_env).npv

        S = 100.0
        r = 0.05
        q = 0.02
        T = 1.0  # approximately

        # C - P ≈ S*exp(-qT) - K*exp(-rT)
        expected_diff = S * math.exp(-q * T) - K * math.exp(-r * T)
        actual_diff = npv_call - npv_put

        assert abs(actual_diff - expected_diff) < 0.5, (
            f"Put-call parity violated: C-P={actual_diff:.4f}, "
            f"expected={expected_diff:.4f}"
        )


# ---------------------------------------------------------------------------
# Batch Pricing Tests
# ---------------------------------------------------------------------------

class TestBatchPricing:
    """Test batch pricing functionality."""

    def test_batch_returns_all_results(self, pricing_service, test_market_env):
        """Batch pricing should return one result per instrument."""
        from instruments.equity.vanilla_option import VanillaOption
        from core.enums.definitions import OptionType, ExerciseType

        instruments = []
        for i, strike in enumerate([80, 90, 100, 110, 120]):
            instruments.append(VanillaOption(
                _trade_id=f"BATCH-{i}",
                underlying="TEST",
                strike=float(strike),
                expiry=date(2026, 1, 15),
                option_type=OptionType.CALL,
                exercise_type=ExerciseType.EUROPEAN,
                _currency="USD",
            ))

        results = pricing_service.price_batch(instruments, test_market_env)

        assert len(results) == 5
        # NPVs should be monotonically decreasing with strike for calls
        npvs = [r.npv for r in results]
        for i in range(len(npvs) - 1):
            assert npvs[i] > npvs[i + 1], f"Call NPVs not decreasing: {npvs}"
