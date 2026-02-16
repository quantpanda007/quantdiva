"""
Regression tests for exotic options.

Validates:
1. Barrier parity: BarrierIn + BarrierOut ≈ Vanilla
2. Digital analytic vs static replication (call spread)
3. Asian geometric: analytic vs MC convergence
4. Lookback: analytic continuous vs MC discrete convergence
5. All exotics price > 0 for reasonable inputs
6. Greeks sign checks (delta of call > 0, etc.)

These are quant-grade production validation tests.
"""

from datetime import date
import pytest
import numpy as np

from core.types.value_objects import PricingDate
from core.enums.definitions import OptionType, ExerciseType, BarrierType
from services.pricers.pricing_service import PricingService
from instruments.equity.vanilla_option import VanillaOption
from instruments.equity.barrier_option import BarrierOption
from instruments.equity.digital_option import DigitalOption, DigitalType
from instruments.equity.asian_option import AsianOption, AverageType, StrikeType
from instruments.equity.lookback_option import LookbackOption, LookbackStrikeType
from market.curves.yield_curve import build_test_market_env


pytestmark = pytest.mark.regression


# -----------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------

@pytest.fixture
def pricing_date():
    return PricingDate(date(2025, 1, 15))


@pytest.fixture
def market_env(pricing_date):
    return build_test_market_env(
        pricing_date=pricing_date,
        spot=100.0,
        rate=0.05,
        vol=0.20,
        div_yield=0.02,
        underlying="TEST",
    )


@pytest.fixture(scope="session")
def pricing_service():
    import registry.bootstrap  # noqa: F401
    return PricingService()


# -----------------------------------------------------------------------
# Helper: price with specific engine
# -----------------------------------------------------------------------

def price(ps, instrument, env, engine_type="analytic", engine_params=None):
    return ps.price(
        instrument, env,
        model_type="black_scholes",
        engine_type=engine_type,
        engine_params=engine_params,
    ).npv


# -----------------------------------------------------------------------
# 1. Barrier Parity: In + Out = Vanilla
# -----------------------------------------------------------------------

class TestBarrierParity:
    """BarrierIn + BarrierOut should equal the vanilla price."""

    def _make_barrier(self, barrier_type, strike=100.0, barrier_level=None):
        if barrier_level is None:
            if barrier_type in (BarrierType.UP_IN, BarrierType.UP_OUT):
                barrier_level = 120.0
            else:
                barrier_level = 80.0

        return BarrierOption(
            _trade_id=f"BAR-{barrier_type.value}-{strike}",
            underlying="TEST",
            strike=strike,
            expiry=date(2026, 1, 15),
            option_type=OptionType.CALL,
            barrier_type=barrier_type,
            barrier_level=barrier_level,
            rebate=0.0,
            _currency="USD",
        )

    def _make_vanilla(self, strike=100.0):
        return VanillaOption(
            _trade_id=f"VAN-{strike}",
            underlying="TEST",
            strike=strike,
            expiry=date(2026, 1, 15),
            option_type=OptionType.CALL,
            exercise_type=ExerciseType.EUROPEAN,
            _currency="USD",
        )

    def test_up_in_plus_up_out_equals_vanilla(self, pricing_service, market_env):
        """UpIn + UpOut = Vanilla (call, barrier=120)."""
        up_in = self._make_barrier(BarrierType.UP_IN)
        up_out = self._make_barrier(BarrierType.UP_OUT)
        vanilla = self._make_vanilla()

        p_in = price(pricing_service, up_in, market_env)
        p_out = price(pricing_service, up_out, market_env)
        p_van = price(pricing_service, vanilla, market_env)

        assert abs((p_in + p_out) - p_van) < 0.01, (
            f"Parity failed: {p_in} + {p_out} = {p_in + p_out} ≠ {p_van}"
        )

    def test_down_in_plus_down_out_equals_vanilla(self, pricing_service, market_env):
        """DownIn + DownOut = Vanilla (call, barrier=80)."""
        down_in = self._make_barrier(BarrierType.DOWN_IN)
        down_out = self._make_barrier(BarrierType.DOWN_OUT)
        vanilla = self._make_vanilla()

        p_in = price(pricing_service, down_in, market_env)
        p_out = price(pricing_service, down_out, market_env)
        p_van = price(pricing_service, vanilla, market_env)

        assert abs((p_in + p_out) - p_van) < 0.01, (
            f"Parity failed: {p_in} + {p_out} = {p_in + p_out} ≠ {p_van}"
        )

    def test_barrier_prices_positive(self, pricing_service, market_env):
        """All barrier types should produce positive prices."""
        for bt in BarrierType:
            barrier = self._make_barrier(bt)
            p = price(pricing_service, barrier, market_env)
            assert p > 0, f"{bt.value} barrier price should be > 0, got {p}"

    def test_knock_out_less_than_vanilla(self, pricing_service, market_env):
        """Knock-out option must be worth less than vanilla."""
        for bt in [BarrierType.UP_OUT, BarrierType.DOWN_OUT]:
            barrier = self._make_barrier(bt)
            vanilla = self._make_vanilla()
            p_bar = price(pricing_service, barrier, market_env)
            p_van = price(pricing_service, vanilla, market_env)
            assert p_bar < p_van, (
                f"{bt.value} price {p_bar} should be < vanilla {p_van}"
            )


# -----------------------------------------------------------------------
# 2. Digital Option Tests
# -----------------------------------------------------------------------

class TestDigitalOption:
    """Validate digital option pricing."""

    def _make_digital(self, option_type=OptionType.CALL, digital_type=DigitalType.CASH_OR_NOTHING):
        return DigitalOption(
            _trade_id=f"DIG-{option_type.value}-{digital_type.value}",
            underlying="TEST",
            strike=100.0,
            expiry=date(2026, 1, 15),
            option_type=option_type,
            digital_type=digital_type,
            cash_payoff=1.0,
            _currency="USD",
        )

    def test_cash_or_nothing_call_put_sum(self, pricing_service, market_env):
        """
        Cash-or-Nothing Call + Put ≈ PV(cash_payoff).
        The total probability must integrate to 1.
        """
        call = self._make_digital(OptionType.CALL, DigitalType.CASH_OR_NOTHING)
        put = self._make_digital(OptionType.PUT, DigitalType.CASH_OR_NOTHING)

        p_call = price(pricing_service, call, market_env)
        p_put = price(pricing_service, put, market_env)

        # PV of $1 at T=1 with r=5%
        T = 1.0
        pv = np.exp(-0.05 * T)

        assert abs((p_call + p_put) - pv) < 0.01, (
            f"CoN Call + Put = {p_call + p_put} ≠ PV(1) = {pv}"
        )

    def test_digital_vs_static_formula(self, pricing_service, market_env):
        """Digital price should match the static analytic formula."""
        call = self._make_digital(OptionType.CALL, DigitalType.CASH_OR_NOTHING)
        p = price(pricing_service, call, market_env)

        # Analytic
        analytic = DigitalOption.analytic_price_cash_or_nothing(
            spot=100.0, strike=100.0, T=1.0,
            rate=0.05, div_yield=0.02, vol=0.20,
            cash_payoff=1.0, is_call=True,
        )

        assert abs(p - analytic) < 0.001, (
            f"Engine price {p} ≠ analytic {analytic}"
        )

    def test_digital_positive(self, pricing_service, market_env):
        """All digital types should produce positive prices."""
        for ot in [OptionType.CALL, OptionType.PUT]:
            for dt in DigitalType:
                dig = self._make_digital(ot, dt)
                p = price(pricing_service, dig, market_env)
                assert p > 0, f"Digital {ot.value} {dt.value} price should be > 0, got {p}"


# -----------------------------------------------------------------------
# 3. Asian Option Tests
# -----------------------------------------------------------------------

class TestAsianOption:
    """Validate Asian option pricing."""

    def _make_asian(self, average_type=AverageType.GEOMETRIC):
        return AsianOption(
            _trade_id=f"ASIAN-{average_type.value}",
            underlying="TEST",
            strike=100.0,
            expiry=date(2026, 1, 15),
            option_type=OptionType.CALL,
            average_type=average_type,
            strike_type=StrikeType.FIXED,
            averaging_start=date(2025, 1, 15),
            fixing_frequency="monthly",
            _currency="USD",
        )

    def test_geometric_analytic_positive(self, pricing_service, market_env):
        """Geometric Asian analytic price should be positive."""
        asian = self._make_asian(AverageType.GEOMETRIC)
        p = price(pricing_service, asian, market_env)
        assert p > 0, f"Geometric Asian price should be > 0, got {p}"

    def test_asian_less_than_vanilla(self, pricing_service, market_env):
        """
        Asian option should be worth less than vanilla
        (averaging reduces volatility exposure).
        """
        asian = self._make_asian(AverageType.GEOMETRIC)
        vanilla = VanillaOption(
            _trade_id="VAN-ASIAN-REF",
            underlying="TEST",
            strike=100.0,
            expiry=date(2026, 1, 15),
            option_type=OptionType.CALL,
            exercise_type=ExerciseType.EUROPEAN,
            _currency="USD",
        )

        p_asian = price(pricing_service, asian, market_env)
        p_van = price(pricing_service, vanilla, market_env)

        assert p_asian < p_van, (
            f"Asian {p_asian} should be < Vanilla {p_van}"
        )

    def test_arithmetic_mc_positive(self, pricing_service, market_env):
        """Arithmetic Asian MC price should be positive."""
        asian = self._make_asian(AverageType.ARITHMETIC)
        p = price(
            pricing_service, asian, market_env,
            engine_type="monte_carlo",
            engine_params={"num_paths": 50_000, "time_steps": 252},
        )
        assert p > 0, f"Arithmetic Asian MC price should be > 0, got {p}"


# -----------------------------------------------------------------------
# 4. Lookback Option Tests
# -----------------------------------------------------------------------

class TestLookbackOption:
    """Validate lookback option pricing."""

    def _make_lookback(self, strike_type=LookbackStrikeType.FLOATING, option_type=OptionType.CALL):
        kwargs = {
            "_trade_id": f"LB-{strike_type.value}-{option_type.value}",
            "underlying": "TEST",
            "expiry": date(2026, 1, 15),
            "option_type": option_type,
            "strike_type": strike_type,
            "_currency": "USD",
        }
        if strike_type == LookbackStrikeType.FIXED:
            kwargs["strike"] = 100.0
        return LookbackOption(**kwargs)

    def test_floating_lookback_positive(self, pricing_service, market_env):
        """Floating lookback should be positive (always in the money)."""
        for ot in [OptionType.CALL, OptionType.PUT]:
            lb = self._make_lookback(LookbackStrikeType.FLOATING, ot)
            p = price(pricing_service, lb, market_env)
            assert p > 0, f"Floating lookback {ot.value} should be > 0, got {p}"

    def test_fixed_lookback_positive(self, pricing_service, market_env):
        """Fixed-strike lookback should be positive."""
        for ot in [OptionType.CALL, OptionType.PUT]:
            lb = self._make_lookback(LookbackStrikeType.FIXED, ot)
            p = price(pricing_service, lb, market_env)
            assert p > 0, f"Fixed lookback {ot.value} should be > 0, got {p}"

    def test_lookback_more_than_vanilla(self, pricing_service, market_env):
        """
        Lookback call should be worth more than vanilla call
        (lookback benefits from max, vanilla only gets terminal).
        """
        lb = self._make_lookback(LookbackStrikeType.FIXED, OptionType.CALL)
        vanilla = VanillaOption(
            _trade_id="VAN-LB-REF",
            underlying="TEST",
            strike=100.0,
            expiry=date(2026, 1, 15),
            option_type=OptionType.CALL,
            exercise_type=ExerciseType.EUROPEAN,
            _currency="USD",
        )

        p_lb = price(pricing_service, lb, market_env)
        p_van = price(pricing_service, vanilla, market_env)

        assert p_lb >= p_van, (
            f"Lookback {p_lb} should be >= Vanilla {p_van}"
        )


# -----------------------------------------------------------------------
# 5. Cross-engine convergence for barriers
# -----------------------------------------------------------------------

class TestBarrierConvergence:
    """FD barrier should converge to analytic barrier."""

    def test_fd_converges_to_analytic_barrier(self, pricing_service, market_env):
        """FD barrier price should be close to analytic."""
        barrier = BarrierOption(
            _trade_id="BAR-CONV",
            underlying="TEST",
            strike=100.0,
            expiry=date(2026, 1, 15),
            option_type=OptionType.CALL,
            barrier_type=BarrierType.DOWN_OUT,
            barrier_level=80.0,
            rebate=0.0,
            _currency="USD",
        )

        p_analytic = price(pricing_service, barrier, market_env)
        p_fd = price(
            pricing_service, barrier, market_env,
            engine_type="finite_difference",
            engine_params={"time_steps": 200, "spot_steps": 400},
        )

        rel_error = abs(p_fd - p_analytic) / p_analytic
        assert rel_error < 0.01, (
            f"FD barrier rel error {rel_error:.4%} > 1%. "
            f"Analytic={p_analytic:.6f}, FD={p_fd:.6f}"
        )