"""
FX pricing engines.

- GarmanKohlhagenEngine: BSM with foreign rate as dividend yield.
  Works for both FX options and FX forwards.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import QuantLib as ql

from core.enums.definitions import EngineType, InstrumentType, ModelType
from core.interfaces.base import BaseEngine, BaseModel, MarketEnvironment
from registry import engine_registry


@engine_registry.register_decorator(
    (InstrumentType.FX_OPTION.value, "garman_kohlhagen"), overwrite=True
)
@engine_registry.register_decorator(
    (InstrumentType.FX_OPTION.value, EngineType.ANALYTIC.value), overwrite=True
)
@dataclass
class GarmanKohlhagenEngine(BaseEngine):
    """Garman-Kohlhagen engine for FX options.

    This is BSM where:
    - spot = FX spot rate
    - risk-free rate = domestic rate
    - dividend yield = foreign rate
    - vol = FX implied vol

    All FX-specific parameters (domestic_rate, foreign_rate, vol) are
    read from the instrument object since they're not in the standard
    MarketEnvironment.
    """

    def engine_type(self) -> EngineType:
        return EngineType.ANALYTIC

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.FX_OPTION]

    def supported_models(self) -> List[ModelType]:
        return [ModelType.BLACK_SCHOLES]

    def build(
        self,
        model: BaseModel,
        market_env: MarketEnvironment,
        **kwargs,
    ) -> ql.PricingEngine:
        instrument = kwargs.get("instrument")

        # Get FX-specific params from instrument
        spot_rate = 1.08  # default EURUSD
        dom_rate = 0.045
        for_rate = 0.035
        fx_vol = 0.08

        if instrument:
            # Get spot from market env using ccy_pair as key
            ccy_pair = getattr(instrument, "ccy_pair", "EURUSD")
            spot_rate = market_env.spot_prices.get(
                ccy_pair,
                market_env.spot_prices.get(
                    list(market_env.spot_prices.keys())[0],
                    spot_rate
                ) if market_env.spot_prices else spot_rate
            )

            dom_rate = getattr(instrument, "domestic_rate", dom_rate)
            for_rate = getattr(instrument, "foreign_rate", for_rate)
            fx_vol = getattr(instrument, "vol", fx_vol)

        eval_date = market_env.pricing_date.to_ql()
        dc = ql.Actual365Fixed()

        # Build BSM process with foreign rate as dividend
        spot_handle = ql.QuoteHandle(ql.SimpleQuote(spot_rate))
        dom_curve = ql.YieldTermStructureHandle(
            ql.FlatForward(eval_date, dom_rate, dc)
        )
        for_curve = ql.YieldTermStructureHandle(
            ql.FlatForward(eval_date, for_rate, dc)
        )
        vol_handle = ql.BlackVolTermStructureHandle(
            ql.BlackConstantVol(eval_date, ql.NullCalendar(), fx_vol, dc)
        )

        process = ql.BlackScholesMertonProcess(
            spot_handle, for_curve, dom_curve, vol_handle
        )

        return ql.AnalyticEuropeanEngine(process)


# FX Forward uses the same engine (forward = deep ITM option equivalent)
@engine_registry.register_decorator(
    (InstrumentType.FX_FORWARD.value, "garman_kohlhagen"), overwrite=True
)
@engine_registry.register_decorator(
    (InstrumentType.FX_FORWARD.value, EngineType.ANALYTIC.value), overwrite=True
)
@dataclass
class FXForwardEngine(GarmanKohlhagenEngine):
    """FX Forward engine — same as Garman-Kohlhagen.

    An FX forward is valued as a European option where the intrinsic
    value dominates (deep ITM call for buy, deep ITM put for sell).
    The BSM engine correctly prices both.
    """

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.FX_FORWARD]


# ---------------------------------------------------------------------------
# FX Option — Heston Stochastic Volatility engine
# ---------------------------------------------------------------------------

@engine_registry.register_decorator(
    (InstrumentType.FX_OPTION.value, "heston"), overwrite=True
)
@dataclass
class HestonFXEngine(BaseEngine):
    """Heston stochastic volatility engine for FX options.

    Captures the FX volatility smile/skew that Garman-Kohlhagen cannot.
    Uses ql.AnalyticHestonEngine with a HestonProcess where the
    foreign rate acts as the dividend yield.

    Heston parameters:
      - v0: initial variance (e.g. 0.04 = 20% vol)
      - kappa: mean reversion speed
      - theta: long-run variance
      - sigma: vol of vol
      - rho: correlation spot-vol
    """

    def engine_type(self) -> EngineType:
        return EngineType.ANALYTIC

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.FX_OPTION]

    def supported_models(self) -> List[ModelType]:
        return [ModelType.HESTON]

    def build(
        self,
        model: BaseModel,
        market_env: MarketEnvironment,
        **kwargs,
    ) -> ql.PricingEngine:
        instrument = kwargs.get("instrument")

        # FX params
        spot_rate = 1.08
        dom_rate = 0.045
        for_rate = 0.035

        if instrument:
            ccy_pair = getattr(instrument, "ccy_pair", "EURUSD")
            spot_rate = market_env.spot_prices.get(
                ccy_pair,
                market_env.spot_prices.get(
                    list(market_env.spot_prices.keys())[0], spot_rate
                ) if market_env.spot_prices else spot_rate
            )
            dom_rate = getattr(instrument, "domestic_rate", dom_rate)
            for_rate = getattr(instrument, "foreign_rate", for_rate)

        eval_date = market_env.pricing_date.to_ql()
        dc = ql.Actual365Fixed()

        spot_handle = ql.QuoteHandle(ql.SimpleQuote(spot_rate))
        dom_curve = ql.YieldTermStructureHandle(
            ql.FlatForward(eval_date, dom_rate, dc)
        )
        for_curve = ql.YieldTermStructureHandle(
            ql.FlatForward(eval_date, for_rate, dc)
        )

        # Heston parameters — from instrument or defaults
        v0 = 0.04       # initial variance (vol^2)
        kappa = 1.5      # mean reversion speed
        theta = 0.04     # long-run variance
        sigma = 0.3      # vol of vol
        rho = -0.3       # spot-vol correlation

        if instrument:
            v0 = getattr(instrument, "heston_v0", v0)
            kappa = getattr(instrument, "heston_kappa", kappa)
            theta = getattr(instrument, "heston_theta", theta)
            sigma = getattr(instrument, "heston_sigma", sigma)
            rho = getattr(instrument, "heston_rho", rho)

        process = ql.HestonProcess(
            dom_curve, for_curve, spot_handle,
            v0, kappa, theta, sigma, rho,
        )
        heston_model = ql.HestonModel(process)

        return ql.AnalyticHestonEngine(heston_model)
