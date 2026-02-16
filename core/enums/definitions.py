"""
Domain enumerations shared across the pricing platform.
"""

from enum import Enum, auto


class AssetClass(str, Enum):
    EQUITY = "equity"
    FX = "fx"
    RATES = "rates"
    CREDIT = "credit"
    INFLATION = "inflation"
    COMMODITY = "commodity"


class Currency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"
    CHF = "CHF"
    AUD = "AUD"
    CAD = "CAD"
    NZD = "NZD"
    SEK = "SEK"
    NOK = "NOK"
    SGD = "SGD"
    HKD = "HKD"
    INR = "INR"
    CNY = "CNY"


class InstrumentType(str, Enum):
    # Equity
    VANILLA_OPTION = "vanilla_option"
    BARRIER_OPTION = "barrier_option"
 
    DIGITAL_OPTION = "digital_option"
    LOOKBACK_OPTION = "lookback_option"
    ASIAN_OPTION = "asian_option"


    # FX
    FX_FORWARD = "fx_forward"
    FX_OPTION = "fx_option"
    FX_SWAP = "fx_swap"
    FX_BARRIER = "fx_barrier"

    # Rates
    IRS = "irs"
    OIS = "ois"
    CCS = "ccs"
    FRA = "fra"
    SWAPTION = "swaption"
    CAP_FLOOR = "cap_floor"
    BOND = "bond"
    BOND_OPTION = "bond_option"

    # Credit
    CDS = "cds"
    CDO = "cdo"

    # Inflation
    INFLATION_SWAP = "inflation_swap"
    ZC_INFLATION_SWAP = "zc_inflation_swap"
    YOY_SWAP = "yoy_swap"

    # Commodity
    COMMODITY_FORWARD = "commodity_forward"
    COMMODITY_OPTION = "commodity_option"


class EngineType(str, Enum):
    ANALYTIC = "analytic"
    BINOMIAL = "binomial"
    TRINOMIAL = "trinomial"
    FINITE_DIFFERENCE = "finite_difference"
    MONTE_CARLO = "monte_carlo"
    INTEGRAL = "integral"


class ModelType(str, Enum):
    # Equity
    BLACK_SCHOLES = "black_scholes"
    HESTON = "heston"
    LOCAL_VOL = "local_vol"
    SABR = "sabr"
    STOCHASTIC_LOCAL_VOL = "slv"

    # Rates
    HULL_WHITE_1F = "hull_white_1f"
    HULL_WHITE_2F = "hull_white_2f"
    G2PP = "g2pp"
    LGM = "lgm"
    LIBOR_MARKET_MODEL = "lmm"

    # Credit
    HAZARD_RATE = "hazard_rate"
    STRUCTURAL = "structural"


class OptionType(str, Enum):
    CALL = "call"
    PUT = "put"


class ExerciseType(str, Enum):
    EUROPEAN = "european"
    AMERICAN = "american"
    BERMUDAN = "bermudan"


class BarrierType(str, Enum):
    UP_IN = "up_in"
    UP_OUT = "up_out"
    DOWN_IN = "down_in"
    DOWN_OUT = "down_out"


class DayCountConvention(str, Enum):
    ACT_360 = "ACT/360"
    ACT_365 = "ACT/365"
    ACT_ACT = "ACT/ACT"
    THIRTY_360 = "30/360"


class BusinessDayConvention(str, Enum):
    FOLLOWING = "following"
    MODIFIED_FOLLOWING = "modified_following"
    PRECEDING = "preceding"
    MODIFIED_PRECEDING = "modified_preceding"
    UNADJUSTED = "unadjusted"


class CompoundingType(str, Enum):
    SIMPLE = "simple"
    CONTINUOUS = "continuous"
    COMPOUNDED = "compounded"


class Frequency(str, Enum):
    ANNUAL = "annual"
    SEMIANNUAL = "semiannual"
    QUARTERLY = "quarterly"
    MONTHLY = "monthly"
    WEEKLY = "weekly"
    DAILY = "daily"
    ONCE = "once"


class TradeDirection(str, Enum):
    BUY = "buy"
    SELL = "sell"
    PAY = "pay"
    RECEIVE = "receive"


class CurveType(str, Enum):
    DISCOUNT = "discount"
    FORWARD = "forward"
    BASIS = "basis"
    OIS = "ois"
    HAZARD = "hazard"
    INFLATION = "inflation"


class VolSurfaceType(str, Enum):
    BLACK = "black"
    NORMAL = "normal"
    SHIFTED_LOGNORMAL = "shifted_lognormal"
    LOCAL = "local"
    STOCHASTIC = "stochastic"


class RiskMeasure(str, Enum):
    DELTA = "delta"
    GAMMA = "gamma"
    VEGA = "vega"
    THETA = "theta"
    RHO = "rho"
    DV01 = "dv01"
    CS01 = "cs01"
    VAR = "var"
    CVAR = "cvar"
    PFE = "pfe"
    EE = "expected_exposure"


class ScenarioType(str, Enum):
    PARALLEL_SHIFT = "parallel_shift"
    TWIST = "twist"
    BUTTERFLY = "butterfly"
    VOL_BUMP = "vol_bump"
    SPOT_BUMP = "spot_bump"
    CREDIT_SPREAD_BUMP = "credit_spread_bump"
    HISTORICAL = "historical"
    CUSTOM = "custom"
