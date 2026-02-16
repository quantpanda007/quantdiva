from datetime import date
import QuantLib as ql

from services.pricers.pricing_service import PricingService
from instruments.equity.vanilla_option import VanillaOption
from core.types.value_objects import PricingDate
from core.interfaces.base import MarketEnvironment
from core.enums.definitions import OptionType, ExerciseType



def build_market():
    pricing_date = PricingDate(date.today())
    day_count = ql.Actual365Fixed()
    calendar = ql.NullCalendar()

    r_curve = ql.YieldTermStructureHandle(
        ql.FlatForward(pricing_date.to_ql(), 0.05, day_count)
    )
    q_curve = ql.YieldTermStructureHandle(
        ql.FlatForward(pricing_date.to_ql(), 0.02, day_count)
    )
    vol = ql.BlackVolTermStructureHandle(
        ql.BlackConstantVol(pricing_date.to_ql(), calendar, 0.20, day_count)
    )

    return MarketEnvironment(
        pricing_date=pricing_date,
        spot_prices={"AAPL": 100.0},
        discount_curves={"USD": r_curve, "AAPL": r_curve},
        dividend_curves={"AAPL_div": q_curve},
        vol_surfaces={"AAPL": vol},
    )

def build_option(exercise: str):
    maturity = date.today().replace(year=date.today().year + 1)

    if exercise == "bermudan":
        return VanillaOption(
            _trade_id="bermudan_test",
            underlying="AAPL",
            strike=100.0,
            expiry=maturity,
            option_type=OptionType.CALL,
            exercise_type=ExerciseType.BERMUDAN,
            exercise_start=date.today(),          # required
            bermudan_frequency="quarterly",       # required
        )

    return VanillaOption(
        _trade_id=f"{exercise}_test",
        underlying="AAPL",
        strike=100.0,
        expiry=maturity,
        option_type=OptionType.CALL,
        exercise_type=ExerciseType(exercise),
    )




def test_european_pricing_smoke():
    service = PricingService()
    result = service.price(build_option("european"), build_market(),
                           model_type="black_scholes", engine_type="analytic")

    assert result.npv > 0


def test_american_pricing_smoke():
    service = PricingService()
    result = service.price(build_option("american"), build_market(),
                           model_type="black_scholes", engine_type="finite_difference")

    assert result.npv > 0


def test_bermudan_pricing_smoke():
    service = PricingService()
    result = service.price(build_option("bermudan"), build_market(),
                           model_type="black_scholes", engine_type="finite_difference")

    assert result.npv > 0
