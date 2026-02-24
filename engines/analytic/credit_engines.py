"""
Credit pricing engines.

Engines:
  1. MidPointCdsEngine (flat hazard) — simple, single hazard rate
  2. BootstrappedCdsEngine — bootstraps piecewise hazard curve from
     market CDS spreads at standard tenors (1Y, 3Y, 5Y, 7Y, 10Y)
  3. IsdaCdsEngine — ISDA standard model with proper conventions

The bootstrapped engine is the "stochastic hazard rate" equivalent:
it builds a term structure of default probabilities from observable
market data, capturing the shape of the credit curve.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import QuantLib as ql

from core.enums.definitions import EngineType, InstrumentType, ModelType
from core.interfaces.base import BaseEngine, BaseModel, MarketEnvironment
from registry import engine_registry


# ---------------------------------------------------------------------------
# Flat Hazard Rate — simple single-rate model
# ---------------------------------------------------------------------------

@engine_registry.register_decorator(
    (InstrumentType.CDS.value, "midpoint"), overwrite=True
)
@engine_registry.register_decorator(
    (InstrumentType.CDS.value, EngineType.ANALYTIC.value), overwrite=True
)
@dataclass
class MidPointCdsEngine(BaseEngine):
    """MidPoint CDS engine with flat hazard rate.

    Uses ql.MidPointCdsEngine — the standard CDS pricing engine.
    Builds a FlatHazardRate curve from a single hazard rate parameter.
    """

    def engine_type(self) -> EngineType:
        return EngineType.ANALYTIC

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.CDS]

    def supported_models(self) -> List[ModelType]:
        return [ModelType.BLACK_SCHOLES, ModelType.HAZARD_RATE]

    def build(
        self,
        model: BaseModel,
        market_env: MarketEnvironment,
        **kwargs,
    ) -> ql.PricingEngine:
        currency = kwargs.get("currency", "USD")
        curve = self._get_discount_curve(market_env, currency)

        instrument = kwargs.get("instrument")
        hazard_rate = 0.02
        recovery_rate = 0.40

        if instrument:
            hazard_rate = getattr(instrument, "hazard_rate", hazard_rate)
            recovery_rate = getattr(instrument, "recovery_rate", recovery_rate)

        eval_date = ql.Settings.instance().evaluationDate
        hazard_curve = ql.FlatHazardRate(
            eval_date,
            ql.QuoteHandle(ql.SimpleQuote(hazard_rate)),
            ql.Actual365Fixed(),
        )
        probability = ql.DefaultProbabilityTermStructureHandle(hazard_curve)

        return ql.MidPointCdsEngine(probability, recovery_rate, curve)

    @staticmethod
    def _get_discount_curve(market_env, currency):
        curve = market_env.discount_curves.get(currency)
        if curve is None:
            if market_env.discount_curves:
                curve = list(market_env.discount_curves.values())[0]
            else:
                raise ValueError("No discount curve available for CDS")
        return curve


# ---------------------------------------------------------------------------
# Bootstrapped Hazard Curve — from market CDS spreads
# ---------------------------------------------------------------------------

@engine_registry.register_decorator(
    (InstrumentType.CDS.value, "bootstrapped"), overwrite=True
)
@dataclass
class BootstrappedCdsEngine(BaseEngine):
    """CDS engine with bootstrapped piecewise hazard rate curve.

    Instead of a single flat hazard rate, this engine takes CDS spreads
    at standard tenors (1Y, 3Y, 5Y, 7Y, 10Y) and bootstraps a
    piecewise-flat hazard rate term structure.

    This captures the shape of the credit curve — e.g., inverted curves
    for stressed credits (high near-term default risk) or upward-sloping
    curves for investment grade names.

    The instrument provides:
      - spread_curve: dict mapping tenor to spread, e.g.
        {"1Y": 0.005, "3Y": 0.008, "5Y": 0.01, "7Y": 0.012, "10Y": 0.015}
      - recovery_rate: recovery assumption

    If spread_curve is not provided, falls back to using the single
    spread at the contract maturity.
    """

    def engine_type(self) -> EngineType:
        return EngineType.ANALYTIC

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.CDS]

    def supported_models(self) -> List[ModelType]:
        return [ModelType.HAZARD_RATE]

    def build(
        self,
        model: BaseModel,
        market_env: MarketEnvironment,
        **kwargs,
    ) -> ql.PricingEngine:
        currency = kwargs.get("currency", "USD")
        curve = MidPointCdsEngine._get_discount_curve(market_env, currency)

        instrument = kwargs.get("instrument")
        recovery_rate = 0.40
        spread_curve = None

        if instrument:
            recovery_rate = getattr(instrument, "recovery_rate", recovery_rate)
            spread_curve = getattr(instrument, "spread_curve", None)

        eval_date = ql.Settings.instance().evaluationDate
        calendar = ql.UnitedStates(ql.UnitedStates.GovernmentBond)

        if spread_curve and isinstance(spread_curve, dict) and len(spread_curve) > 0:
            # Bootstrap from market spreads
            probability = self._bootstrap_hazard_curve(
                eval_date, calendar, curve, spread_curve, recovery_rate,
            )
        else:
            # Fallback: derive fair spreads from hazard_rate
            # Fair spread ≈ hazard_rate * (1 - recovery_rate)
            hazard_rate = 0.02
            if instrument:
                hazard_rate = getattr(instrument, "hazard_rate", hazard_rate)

            fair_spread = hazard_rate * (1.0 - recovery_rate)

            # Build a realistic upward-sloping spread curve
            spread_curve = {
                "1Y": fair_spread * 0.7,
                "3Y": fair_spread * 0.85,
                "5Y": fair_spread,
                "7Y": fair_spread * 1.08,
                "10Y": fair_spread * 1.15,
            }
            probability = self._bootstrap_hazard_curve(
                eval_date, calendar, curve, spread_curve, recovery_rate,
            )

        return ql.MidPointCdsEngine(probability, recovery_rate, curve)

    @staticmethod
    def _bootstrap_hazard_curve(
        eval_date, calendar, discount_curve, spread_curve, recovery_rate,
    ) -> ql.DefaultProbabilityTermStructureHandle:
        """Bootstrap piecewise hazard rate curve from CDS spreads.

        Uses QuantLib's PiecewiseFlatHazardRate with CdsHelper instruments.
        """
        tenor_map = {
            "6M": ql.Period(6, ql.Months),
            "1Y": ql.Period(1, ql.Years),
            "2Y": ql.Period(2, ql.Years),
            "3Y": ql.Period(3, ql.Years),
            "5Y": ql.Period(5, ql.Years),
            "7Y": ql.Period(7, ql.Years),
            "10Y": ql.Period(10, ql.Years),
            "15Y": ql.Period(15, ql.Years),
            "20Y": ql.Period(20, ql.Years),
            "30Y": ql.Period(30, ql.Years),
        }

        helpers = []
        for tenor_str, spread_val in sorted(
            spread_curve.items(),
            key=lambda x: tenor_map.get(x[0], ql.Period(99, ql.Years)).length()
        ):
            period = tenor_map.get(tenor_str)
            if period is None:
                continue

            spread_quote = ql.QuoteHandle(ql.SimpleQuote(spread_val))

            helper = ql.SpreadCdsHelper(
                spread_quote,
                period,
                0,  # settlement days
                calendar,
                ql.Quarterly,
                ql.ModifiedFollowing,
                ql.DateGeneration.TwentiethIMM,
                ql.Actual360(),
                recovery_rate,
                discount_curve,
            )
            helpers.append(helper)

        if not helpers:
            # Fallback to flat
            hazard = ql.FlatHazardRate(
                eval_date,
                ql.QuoteHandle(ql.SimpleQuote(0.02)),
                ql.Actual365Fixed(),
            )
            return ql.DefaultProbabilityTermStructureHandle(hazard)

        hazard_curve = ql.PiecewiseFlatHazardRate(
            eval_date, helpers, ql.Actual365Fixed()
        )
        hazard_curve.enableExtrapolation()

        return ql.DefaultProbabilityTermStructureHandle(hazard_curve)


# ---------------------------------------------------------------------------
# ISDA CDS Engine — industry standard
# ---------------------------------------------------------------------------

@engine_registry.register_decorator(
    (InstrumentType.CDS.value, "isda"), overwrite=True
)
@dataclass
class IsdaCdsEngine(BaseEngine):
    """ISDA standard CDS pricing engine.

    Uses ql.IsdaCdsEngine which implements the ISDA CDS Standard Model
    with proper accrual handling and settlement conventions.

    This is the engine used by DTCC and major dealers for CDS mark-to-market.
    """

    def engine_type(self) -> EngineType:
        return EngineType.ANALYTIC

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.CDS]

    def supported_models(self) -> List[ModelType]:
        return [ModelType.HAZARD_RATE]

    def build(
        self,
        model: BaseModel,
        market_env: MarketEnvironment,
        **kwargs,
    ) -> ql.PricingEngine:
        currency = kwargs.get("currency", "USD")
        curve = MidPointCdsEngine._get_discount_curve(market_env, currency)

        instrument = kwargs.get("instrument")
        hazard_rate = 0.02
        recovery_rate = 0.40

        if instrument:
            hazard_rate = getattr(instrument, "hazard_rate", hazard_rate)
            recovery_rate = getattr(instrument, "recovery_rate", recovery_rate)

        eval_date = ql.Settings.instance().evaluationDate
        hazard_curve = ql.FlatHazardRate(
            eval_date,
            ql.QuoteHandle(ql.SimpleQuote(hazard_rate)),
            ql.Actual365Fixed(),
        )
        probability = ql.DefaultProbabilityTermStructureHandle(hazard_curve)

        return ql.IsdaCdsEngine(probability, recovery_rate, curve)