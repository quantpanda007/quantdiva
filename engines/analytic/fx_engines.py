"""
FX pricing engines.

- GarmanKohlhagenEngine: BSM with foreign rate as dividend yield. For FX options.
- FXForwardEngine: Pure analytical forward pricer. Reads rates from market_env curves.
  NPV = Notional × (F - K) × DF × sign
  where F = S × exp((r_d - r_f) × T), DF = exp(-r_d × T)
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

import QuantLib as ql

from core.enums.definitions import EngineType, InstrumentType, ModelType
from core.interfaces.base import BaseEngine, BaseModel, MarketEnvironment, PricingResult
from registry import engine_registry


@engine_registry.register_decorator(
    (InstrumentType.FX_OPTION.value, "garman_kohlhagen"), overwrite=True
)
@engine_registry.register_decorator(
    (InstrumentType.FX_OPTION.value, EngineType.ANALYTIC.value), overwrite=True
)
@dataclass
class GarmanKohlhagenEngine(BaseEngine):
    """Garman-Kohlhagen engine for FX options."""

    def engine_type(self) -> EngineType:
        return EngineType.ANALYTIC

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.FX_OPTION]

    def supported_models(self) -> List[ModelType]:
        return [ModelType.BLACK_SCHOLES]

    def build(self, model: BaseModel, market_env: MarketEnvironment, **kwargs) -> ql.PricingEngine:
        instrument = kwargs.get("instrument")

        spot_rate = 1.08
        dom_rate  = 0.045
        for_rate  = 0.035
        fx_vol    = 0.08

        if instrument:
            ccy_pair  = getattr(instrument, "ccy_pair", "EURUSD")
            spot_rate = market_env.spot_prices.get(
                ccy_pair,
                market_env.spot_prices.get(
                    list(market_env.spot_prices.keys())[0], spot_rate
                ) if market_env.spot_prices else spot_rate
            )
            dom_rate = getattr(instrument, "domestic_rate", dom_rate)
            for_rate = getattr(instrument, "foreign_rate",  for_rate)
            fx_vol   = getattr(instrument, "vol",           fx_vol)

        eval_date  = market_env.pricing_date.to_ql()
        dc         = ql.Actual365Fixed()
        spot_handle = ql.QuoteHandle(ql.SimpleQuote(spot_rate))
        dom_curve   = ql.YieldTermStructureHandle(ql.FlatForward(eval_date, dom_rate, dc))
        for_curve   = ql.YieldTermStructureHandle(ql.FlatForward(eval_date, for_rate, dc))
        vol_handle  = ql.BlackVolTermStructureHandle(
            ql.BlackConstantVol(eval_date, ql.NullCalendar(), fx_vol, dc)
        )
        process = ql.BlackScholesMertonProcess(spot_handle, for_curve, dom_curve, vol_handle)
        return ql.AnalyticEuropeanEngine(process)


# ---------------------------------------------------------------------------
# FX Forward — Arguments / Results  (QL instrument/engine separation)
# ---------------------------------------------------------------------------

@dataclass
class FXForwardArguments:
    """
    Typed input container for FXForwardEngine.

    Populated by FXForward.setupArguments(args).
    Holds all trade economics the engine needs — nothing else.
    """
    ccy_pair:      str            = ""
    strike:        float          = 0.0
    notional:      float          = 0.0
    delivery_date: Optional[date] = None
    direction:     str            = "buy"


@dataclass
class FXForwardResults:
    """
    Typed output container from FXForwardEngine.

    npv          — NPV in domestic currency, scaled by notional
    forward_rate — computed forward rate F = S × exp((r_d - r_f) × T)
    disc_factor  — domestic discount factor DF = exp(-r_d × T)
    error        — populated if pricing failed; None on success
    """
    npv:          Optional[float] = None
    forward_rate: Optional[float] = None
    disc_factor:  Optional[float] = None
    error:        Optional[str]   = None


# ---------------------------------------------------------------------------
# FX Forward Engine
# ---------------------------------------------------------------------------

@engine_registry.register_decorator(
    (InstrumentType.FX_FORWARD.value, "garman_kohlhagen"), overwrite=True
)
@engine_registry.register_decorator(
    (InstrumentType.FX_FORWARD.value, EngineType.ANALYTIC.value), overwrite=True
)
@dataclass
class FXForwardEngine(BaseEngine):
    """
    Pure analytical FX forward pricer.

    Uses the QL instrument/engine separation pattern:
      1. instrument.setupArguments(args)  — trade data  → FXForwardArguments
      2. engine.price(instrument, env)    — formula     → FXForwardResults

    Formula:
        F   = S × exp((r_d - r_f) × T)
        DF  = exp(-r_d × T)
        NPV = Notional × (F - K) × DF × sign   (buy: sign=+1, sell: sign=-1)

    Vol is ignored. Rates read from market_env discount curves by CCY code.
    """

    def engine_type(self) -> EngineType:
        return EngineType.ANALYTIC

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.FX_FORWARD]

    def supported_models(self) -> List[ModelType]:
        return [ModelType.BLACK_SCHOLES]

    def build(self, model: BaseModel, market_env: MarketEnvironment, **kwargs):
        # FX forward uses price() directly — no QL engine object needed.
        return None

    def price(self, instrument, market_env: MarketEnvironment) -> FXForwardResults:
        """
        Price an FX forward and return typed FXForwardResults.

        Extracts trade economics via instrument.setupArguments(), reads
        market data from market_env, applies the forward formula.
        """
        results = FXForwardResults()

        # --- Populate arguments from instrument ---
        args = FXForwardArguments()
        instrument.setupArguments(args)

        # --- Expired deal guard ---
        pricing_date: date = market_env.pricing_date.value
        if args.delivery_date is None or args.delivery_date <= pricing_date:
            results.npv = 0.0
            return results

        # --- Time to delivery (Actual365Fixed, consistent with FXForward.build) ---
        day_count   = ql.Actual365Fixed()
        ql_pricing  = ql.Date(pricing_date.day, pricing_date.month, pricing_date.year)
        ql_delivery = ql.Date(
            args.delivery_date.day,
            args.delivery_date.month,
            args.delivery_date.year,
        )
        T = day_count.yearFraction(ql_pricing, ql_delivery)

        if T <= 0:
            results.npv = 0.0
            return results

        # --- Spot ---
        spot = market_env.spot_prices.get(args.ccy_pair)
        if spot is None:
            results.error = f"No spot price found for {args.ccy_pair}"
            return results

        # --- Domestic and foreign rates ---
        dom_ccy = args.ccy_pair[3:6] if len(args.ccy_pair) == 6 else args.ccy_pair
        for_ccy = args.ccy_pair[:3]  if len(args.ccy_pair) == 6 else args.ccy_pair

        r_d = self._zero_rate(market_env, dom_ccy, T)
        r_f = self._zero_rate(market_env, for_ccy, T)

        # --- Forward formula ---
        F    = spot * math.exp((r_d - r_f) * T)
        DF   = math.exp(-r_d * T)
        sign = 1.0 if args.direction.lower() in ("buy", "long") else -1.0

        results.npv          = args.notional * (F - args.strike) * DF * sign
        results.forward_rate = round(F, 6)
        results.disc_factor  = round(DF, 8)
        return results

    def _zero_rate(self, market_env: MarketEnvironment, ccy: str, T: float) -> float:
        """
        Extract continuously compounded zero rate from discount curve at time T.
        Returns 0.0 if the currency is not in discount_curves.
        """
        for key in (ccy, ccy.upper()):
            if key in market_env.discount_curves:
                handle = market_env.discount_curves[key]
                return handle.zeroRate(T, ql.Continuous, ql.Annual).rate()
        return 0.0

    def _rate_from_curve(self, market_env: MarketEnvironment, ccy_key: str) -> float:
        """
        Legacy helper — kept for backwards compatibility only.
        Known bug: always queries at 1Y regardless of deal maturity.
        Use _zero_rate(market_env, ccy, T) instead.
        """
        curve_handle = market_env.discount_curves.get(ccy_key)
        if curve_handle is None:
            return 0.0
        try:
            dc     = ql.Actual365Fixed()
            ref    = curve_handle.referenceDate()
            target = ref + ql.Period(1, ql.Years)
            return float(curve_handle.zeroRate(target, dc, ql.Continuous).rate())
        except Exception:
            return 0.0


# ---------------------------------------------------------------------------
# FX Option — Heston Stochastic Volatility engine
# ---------------------------------------------------------------------------

@engine_registry.register_decorator(
    (InstrumentType.FX_OPTION.value, "heston"), overwrite=True
)
@dataclass
class HestonFXEngine(BaseEngine):
    """Heston stochastic volatility engine for FX options."""

    def engine_type(self) -> EngineType:
        return EngineType.ANALYTIC

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.FX_OPTION]

    def supported_models(self) -> List[ModelType]:
        return [ModelType.BLACK_SCHOLES]

    def build(self, model: BaseModel, market_env: MarketEnvironment, **kwargs) -> ql.PricingEngine:
        instrument = kwargs.get("instrument")

        spot_rate = 1.08
        dom_rate  = 0.045
        for_rate  = 0.035

        if instrument:
            ccy_pair  = getattr(instrument, "ccy_pair", "EURUSD")
            spot_rate = market_env.spot_prices.get(
                ccy_pair,
                market_env.spot_prices.get(
                    list(market_env.spot_prices.keys())[0], spot_rate
                ) if market_env.spot_prices else spot_rate
            )
            dom_rate = getattr(instrument, "domestic_rate", dom_rate)
            for_rate = getattr(instrument, "foreign_rate",  for_rate)

        eval_date   = market_env.pricing_date.to_ql()
        dc          = ql.Actual365Fixed()
        spot_handle = ql.QuoteHandle(ql.SimpleQuote(spot_rate))
        dom_curve   = ql.YieldTermStructureHandle(ql.FlatForward(eval_date, dom_rate, dc))
        for_curve   = ql.YieldTermStructureHandle(ql.FlatForward(eval_date, for_rate, dc))

        v0    = getattr(instrument, "heston_v0",    0.04)  if instrument else 0.04
        kappa = getattr(instrument, "heston_kappa", 1.5)   if instrument else 1.5
        theta = getattr(instrument, "heston_theta", 0.04)  if instrument else 0.04
        sigma = getattr(instrument, "heston_sigma", 0.3)   if instrument else 0.3
        rho   = getattr(instrument, "heston_rho",  -0.3)   if instrument else -0.3

        process      = ql.HestonProcess(dom_curve, for_curve, spot_handle, v0, kappa, theta, sigma, rho)
        heston_model = ql.HestonModel(process)
        return ql.AnalyticHestonEngine(heston_model)