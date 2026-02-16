"""
Pricing engines for Asian options.

Analytic (Geometric only):
    Uses QuantLib's AnalyticDiscreteGeometricAveragePriceAsianEngine
    for the Kemna-Vorst closed-form solution. Geometric average has
    a lognormal distribution under GBM, making analytic pricing possible.

    Arithmetic Asians have NO closed form — must use MC.

Monte Carlo (Arithmetic + Geometric):
    MCAsianEngine simulates paths and computes the discrete average
    along each path. Optionally uses the geometric Asian price as
    a control variate for arithmetic — this is a classic and highly
    effective variance reduction technique because:
    - Geometric has a known analytic price
    - Arithmetic and geometric averages are highly correlated

Usage:
    from engines.analytic.asian_engine import AnalyticGeometricAsianEngine
    from engines.monte_carlo.mc_asian_engine import MCAsianEngine

    # Geometric (analytic)
    engine = AnalyticGeometricAsianEngine()

    # Arithmetic (MC with geometric control variate)
    engine = MCAsianEngine(
        num_paths=200_000,
        use_geometric_cv=True,  # geometric Asian as control variate
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import QuantLib as ql

from core.enums.definitions import EngineType, InstrumentType, ModelType
from core.exceptions.errors import IncompatibleEngineError
from core.interfaces.base import BaseEngine, BaseInstrument, BaseModel, MarketEnvironment
from registry import engine_registry


# ---------------------------------------------------------------------------
# Analytic Geometric Asian Engine
# ---------------------------------------------------------------------------

@engine_registry.register_decorator(
    ("asian_option", EngineType.ANALYTIC.value), overwrite=True
)
@dataclass
class AnalyticGeometricAsianEngine(BaseEngine):
    """
    Closed-form engine for geometric average price Asian options.

    Based on the Kemna-Vorst result: under GBM, the geometric average
    of lognormals is itself lognormal, allowing BSM-style pricing.

    Only valid for:
    - Geometric average (NOT arithmetic)
    - Fixed strike
    - European exercise
    - BSM model

    For arithmetic Asians, use MCAsianEngine.
    """

    def engine_type(self) -> EngineType:
        return EngineType.ANALYTIC

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.ASIAN_OPTION]

    def supported_models(self) -> List[ModelType]:
        return [ModelType.BLACK_SCHOLES]

    def build(
        self,
        model: BaseModel,
        market_env: MarketEnvironment,
        instrument: BaseInstrument = None,
        **kwargs,
    ) -> ql.PricingEngine:
        if model.model_type() != ModelType.BLACK_SCHOLES:
            raise IncompatibleEngineError(
                f"AnalyticGeometricAsianEngine requires BLACK_SCHOLES, "
                f"got {model.model_type()}"
            )

        # Check instrument is geometric
        if instrument is not None:
            from instruments.equity.asian_option import AverageType
            avg_type = getattr(instrument, "average_type", None)
            if avg_type is not None and avg_type != AverageType.GEOMETRIC:
                raise IncompatibleEngineError(
                    f"AnalyticGeometricAsianEngine only supports GEOMETRIC average, "
                    f"got {avg_type.value}. Use MCAsianEngine for arithmetic."
                )

        process = model.build_process(market_env)
        return ql.AnalyticDiscreteGeometricAveragePriceAsianEngine(process)