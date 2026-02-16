"""
FD → Analytic convergence regression test.

This validates numerical correctness of the FD engine by ensuring:

    FD price → Analytic Black-Scholes price
    as grid resolution increases.

This is a **quant-grade production validation test**.
"""

from datetime import date
import pytest

from core.types.value_objects import PricingDate
from services.pricers.pricing_service import PricingService
from core.enums.definitions import OptionType, ExerciseType
from instruments.equity.vanilla_option import VanillaOption
from market.curves.yield_curve import build_test_market_env


pytestmark = pytest.mark.regression


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------

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
    """
    Bank-style deterministic boot:
    only import registry bootstrap, never engines directly.
    """
    import registry.bootstrap  # triggers ALL canonical registrations

    from services.pricers.pricing_service import PricingService
    return PricingService()




# ---------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------

def make_european_call(strike: float = 100.0):
    return VanillaOption(
        _trade_id=f"FD-CONV-{strike}",
        underlying="TEST",
        strike=strike,
        expiry=date(2026, 1, 15),
        option_type=OptionType.CALL,
        exercise_type=ExerciseType.EUROPEAN,
        _currency="USD",
    )


# ---------------------------------------------------------------------
# Convergence Test
# ---------------------------------------------------------------------

def test_fd_converges_to_analytic(pricing_service, market_env):
    """
    Core quant validation:

        | FD_price - Analytic_price | ↓ as grid ↑

    We test multiple FD grid sizes and ensure:

        coarse error  > medium error > fine error
        fine error    < tolerance
    """

    option = make_european_call()

    # --- Analytic reference ---
    analytic_price = pricing_service.price(
        option,
        market_env,
        model_type="black_scholes",
        engine_type="analytic",
    ).npv

    # --- FD grid ladder (coarse → fine) ---
    grids = [
        (50, 100),
        (100, 200),
        (200, 400),
    ]

    errors = []

    for t_steps, s_steps in grids:
        fd_price = pricing_service.price(
            option,
            market_env,
            model_type="black_scholes",
            engine_type="finite_difference",
            engine_params={"time_steps": t_steps, "spot_steps": s_steps},
        ).npv
        print("FD params:", t_steps, s_steps, "price:", fd_price)

        errors.append(abs(fd_price - analytic_price))

    # -----------------------------------------------------------------
    # Quant assertions
    # -----------------------------------------------------------------

    coarse_err, mid_err, fine_err = errors

    # 1️⃣ Error must monotonically decrease
    assert coarse_err > mid_err > fine_err, (
        f"FD not converging: errors={errors}"
    )

    # 2️⃣ Final accuracy tolerance (quant-grade)
    assert fine_err < 0.25, (
        f"FD fine grid error too high: {fine_err:.6f}"
    )
