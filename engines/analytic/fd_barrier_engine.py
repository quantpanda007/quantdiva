"""
Finite Difference engine for barrier options.

Uses QuantLib's FdBlackScholesBarrierEngine which solves the BSM PDE
on a grid with barrier boundary conditions.

Key advantage over analytic:
- Handles American exercise (early exercise + barrier)
- More robust near barrier (analytic can have numerical issues)
- Configurable grid for accuracy control

Usage:
    from engines.finite_difference.fd_barrier_engine import FDBarrierEngine
    from engines.finite_difference.fd_config import FDGridConfig

    engine = FDBarrierEngine()
    engine = FDBarrierEngine(grid_config=FDGridConfig(time_steps=300, spot_steps=600))
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import QuantLib as ql

from core.enums.definitions import EngineType, InstrumentType, ModelType
from core.exceptions.errors import IncompatibleEngineError
from core.interfaces.base import BaseEngine, BaseInstrument, BaseModel, MarketEnvironment
from engines.finite_difference.fd_config import FDGridConfig
from engines.finite_difference.fd_result import FDResult
from registry import engine_registry

logger = logging.getLogger(__name__)


def _extract_greeks(option) -> Dict[str, Optional[float]]:
    """Extract Greeks from a priced barrier option."""
    greeks = {}
    for name, method in [
        ("delta", "delta"),
        ("gamma", "gamma"),
        ("theta", "theta"),
        ("vega", "vega"),
        ("rho", "rho"),
    ]:
        try:
            val = getattr(option, method)()
            if name == "theta":
                val = val / 365.0  # per-day
            elif name in ("vega", "rho"):
                val = val / 100.0  # per 1%
            greeks[name] = float(val)
        except Exception:
            greeks[name] = None
    return greeks


@engine_registry.register_decorator(
    (InstrumentType.BARRIER_OPTION.value, EngineType.FINITE_DIFFERENCE.value),
    overwrite=True,
)
@dataclass
class FDBarrierEngine(BaseEngine):
    """
    Finite Difference engine for barrier options under BSM.

    Handles all barrier types (UpIn, UpOut, DownIn, DownOut) and
    both European and American exercise.

    The FD grid naturally incorporates the barrier as a boundary
    condition, making it more accurate than analytic for:
    - American barriers
    - Barriers near the spot
    - Short maturities

    Attributes:
        grid_config:     FDGridConfig controlling grid and scheme
        extract_greeks:  Extract Greeks from FD solution
    """

    grid_config: FDGridConfig = field(default_factory=lambda: FDGridConfig())
    extract_greeks: bool = True

    last_result: Optional[FDResult] = field(default=None, repr=False)

    def engine_type(self) -> EngineType:
        return EngineType.FINITE_DIFFERENCE

    def supported_instruments(self) -> List[InstrumentType]:
        return [InstrumentType.BARRIER_OPTION]

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
                f"FDBarrierEngine requires BLACK_SCHOLES model, "
                f"got {model.model_type()}"
            )

        self.grid_config.validate(is_2d=False)
        process = model.build_process(market_env)

        engine = ql.FdBlackScholesBarrierEngine(
            process,
            self.grid_config.time_steps,
            self.grid_config.spot_steps,
            self.grid_config.damping_steps,
        )

        # Run diagnostics if instrument provided
        if instrument is not None:
            self._run_diagnostics(model, market_env, instrument, process)

        return engine

    def _run_diagnostics(
        self,
        model: BaseModel,
        market_env: MarketEnvironment,
        instrument: BaseInstrument,
        process,
    ) -> None:
        t0 = time.perf_counter()

        underlying = getattr(instrument, "underlying", "")
        strike = getattr(instrument, "strike", 100.0)
        barrier_level = getattr(instrument, "barrier_level", 0.0)
        spot = market_env.spot_prices.get(underlying, 100.0)
        spot_min, spot_max = self.grid_config.compute_spot_bounds(strike, spot)

        # Build and price for diagnostics
        ql_option = instrument.build(market_env)
        engine = ql.FdBlackScholesBarrierEngine(
            process,
            self.grid_config.time_steps,
            self.grid_config.spot_steps,
            self.grid_config.damping_steps,
        )
        ql_option.setPricingEngine(engine)
        npv = ql_option.NPV()

        greeks = {}
        if self.extract_greeks:
            greeks = _extract_greeks(ql_option)

        elapsed = time.perf_counter() - t0

        self.last_result = FDResult(
            metadata={
                "engine": "FDBarrierEngine",
                "model": model.model_type().value,
                "underlying": underlying,
                "strike": strike,
                "barrier_level": barrier_level,
                "spot": spot,
            },
            npv=npv,
            grid_spot_min=spot_min,
            grid_spot_max=spot_max,
            time_steps=self.grid_config.time_steps,
            spot_steps=self.grid_config.spot_steps,
            scheme=self.grid_config.scheme,
            greeks=greeks,
            elapsed_seconds=elapsed,
        )

        logger.info(
            f"FD Barrier diagnostics: NPV={npv:.6f}, "
            f"grid={self.grid_config.time_steps}×{self.grid_config.spot_steps}, "
            f"{elapsed:.3f}s"
        )

    def __repr__(self) -> str:
        return f"FDBarrierEngine({self.grid_config})"