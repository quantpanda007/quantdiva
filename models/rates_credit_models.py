"""
Rates and Credit model registrations.

These are lightweight model stubs that register the model keys
(hull_white_1f, hazard_rate) in the model registry. The actual
model construction happens inside the engines (HullWhiteSwaptionEngine,
BootstrappedCdsEngine, etc.) since rates/credit engines manage their
own processes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import QuantLib as ql

from core.enums.definitions import ModelType
from core.interfaces.base import BaseModel, MarketEnvironment
from registry import model_registry


@model_registry.register_decorator(ModelType.HULL_WHITE_1F.value)
@dataclass
class HullWhiteModel(BaseModel):
    """Hull-White 1-factor short rate model.

    Parameters:
        a (mean reversion): typically 0.01 - 0.10
        sigma (short rate vol): typically 0.005 - 0.02

    The actual ql.HullWhite model is built inside the engine,
    since it needs the discount curve from the market environment.
    """

    underlying: str = ""
    a: float = 0.05
    sigma: float = 0.01
    _calibrated_params: Dict[str, Any] = field(default_factory=dict)

    def model_type(self) -> ModelType:
        return ModelType.HULL_WHITE_1F

    def build_process(self, market_env: MarketEnvironment) -> Any:
        """Return parameters — engine builds the actual QL model."""
        return {"a": self.a, "sigma": self.sigma}

    def parameters(self) -> Dict[str, Any]:
        return {"a": self.a, "sigma": self.sigma}

    def calibrate(self, market_env: MarketEnvironment, helpers: List[Any] = None) -> None:
        pass


@model_registry.register_decorator("hazard_rate")
@dataclass
class HazardRateModel(BaseModel):
    """Hazard rate model for credit instruments.

    Supports both flat hazard rate and bootstrapped piecewise
    hazard curve. The engine handles the actual curve construction.
    """

    underlying: str = ""
    hazard_rate: float = 0.02
    recovery_rate: float = 0.40
    _calibrated_params: Dict[str, Any] = field(default_factory=dict)

    def model_type(self) -> ModelType:
        return ModelType.HAZARD_RATE

    def build_process(self, market_env: MarketEnvironment) -> Any:
        return {
            "hazard_rate": self.hazard_rate,
            "recovery_rate": self.recovery_rate,
        }

    def parameters(self) -> Dict[str, Any]:
        return {
            "hazard_rate": self.hazard_rate,
            "recovery_rate": self.recovery_rate,
        }

    def calibrate(self, market_env: MarketEnvironment, helpers: List[Any] = None) -> None:
        pass