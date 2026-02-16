"""
Abstract base classes (interfaces) for the pricing platform.

These define the contracts that all instruments, engines, models,
and market data providers must satisfy. This is the backbone of
the plugin/registry architecture.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Type

import QuantLib as ql

from core.enums.definitions import (
    AssetClass,
    EngineType,
    InstrumentType,
    ModelType,
    RiskMeasure,
)
from core.types.value_objects import PricingDate, PricingResult, RiskResult, TradeId


# ---------------------------------------------------------------------------
# Instrument Interface
# ---------------------------------------------------------------------------

class BaseInstrument(ABC):
    """
    Abstract base for all tradeable instruments.

    Every instrument must be able to:
    1. Build a QuantLib instrument object
    2. Declare what asset class / instrument type it belongs to
    3. Provide trade metadata
    """

    @abstractmethod
    def build(self, market_env: MarketEnvironment) -> ql.Instrument:
        """Construct the QuantLib instrument given market data."""
        ...

    @abstractmethod
    def asset_class(self) -> AssetClass:
        ...

    @abstractmethod
    def instrument_type(self) -> InstrumentType:
        ...

    @abstractmethod
    def trade_id(self) -> TradeId:
        ...

    @abstractmethod
    def currency(self) -> str:
        ...

    @abstractmethod
    def maturity(self) -> date:
        ...

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for storage/API."""
        return {
            "trade_id": str(self.trade_id()),
            "asset_class": self.asset_class().value,
            "instrument_type": self.instrument_type().value,
            "currency": self.currency(),
            "maturity": self.maturity().isoformat(),
        }


# ---------------------------------------------------------------------------
# Model Interface
# ---------------------------------------------------------------------------

class BaseModel(ABC):
    """
    Abstract base for stochastic models.

    A model encapsulates:
    - The stochastic process (e.g., GBM, Heston, HW)
    - Its calibrated parameters
    - The ability to build a QuantLib process object
    """

    @abstractmethod
    def model_type(self) -> ModelType:
        ...

    @abstractmethod
    def build_process(self, market_env: MarketEnvironment) -> Any:
        """Build the QuantLib stochastic process."""
        ...

    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """Return current model parameters."""
        ...

    @abstractmethod
    def calibrate(self, market_env: MarketEnvironment, helpers: List[Any]) -> None:
        """Calibrate model to market instruments."""
        ...

    def validate(self) -> bool:
        """Validate model parameters are sensible."""
        return True


# ---------------------------------------------------------------------------
# Engine Interface
# ---------------------------------------------------------------------------

class BaseEngine(ABC):
    """
    Abstract base for pricing engines.

    An engine knows how to price instruments given a model and market data.
    The key method builds a QuantLib PricingEngine.
    """

    @abstractmethod
    def engine_type(self) -> EngineType:
        ...

    @abstractmethod
    def build(
        self,
        model: BaseModel,
        market_env: MarketEnvironment,
        **kwargs,
    ) -> ql.PricingEngine:
        """Construct the QuantLib PricingEngine."""
        ...

    @abstractmethod
    def supported_instruments(self) -> List[InstrumentType]:
        """Which instrument types this engine can price."""
        ...

    @abstractmethod
    def supported_models(self) -> List[ModelType]:
        """Which models this engine can work with."""
        ...


# ---------------------------------------------------------------------------
# Market Data Interfaces
# ---------------------------------------------------------------------------

class BaseCurve(ABC):
    """Abstract base for yield/discount/forward curves."""

    @abstractmethod
    def build(self, as_of: PricingDate) -> ql.YieldTermStructureHandle:
        ...

    @abstractmethod
    def currency(self) -> str:
        ...

    @abstractmethod
    def curve_type(self) -> str:
        ...

    @abstractmethod
    def pillar_dates(self) -> List[date]:
        ...


class BaseVolSurface(ABC):
    """Abstract base for volatility surfaces."""

    @abstractmethod
    def build(self, as_of: PricingDate) -> ql.BlackVolTermStructureHandle:
        ...

    @abstractmethod
    def strikes(self) -> List[float]:
        ...

    @abstractmethod
    def expiries(self) -> List[date]:
        ...


# ---------------------------------------------------------------------------
# Market Environment
# ---------------------------------------------------------------------------

@dataclass
class MarketEnvironment:
    """
    Container for all market data needed for pricing.

    This is the single object passed around during pricing that
    holds curves, surfaces, fixings, and conventions.
    """
    pricing_date: PricingDate
    discount_curves: Dict[str, ql.YieldTermStructureHandle] = field(default_factory=dict)
    forecast_curves: Dict[str, ql.YieldTermStructureHandle] = field(default_factory=dict)
    vol_surfaces: Dict[str, ql.BlackVolTermStructureHandle] = field(default_factory=dict)
    spot_prices: Dict[str, float] = field(default_factory=dict)
    fixings: Dict[str, Dict[date, float]] = field(default_factory=dict)
    correlation_matrix: Optional[Any] = None
    hazard_curves: Dict[str, Any] = field(default_factory=dict)
    dividend_curves: Dict[str, Any] = field(default_factory=dict)

    def set_evaluation_date(self):
        """Set the global QuantLib evaluation date."""
        ql.Settings.instance().evaluationDate = self.pricing_date.to_ql()

    def get_discount_curve(self, currency: str) -> ql.YieldTermStructureHandle:
        if currency not in self.discount_curves:
            raise KeyError(f"No discount curve for {currency}")
        return self.discount_curves[currency]

    def get_vol_surface(self, key: str) -> ql.BlackVolTermStructureHandle:
        if key not in self.vol_surfaces:
            raise KeyError(f"No vol surface for {key}")
        return self.vol_surfaces[key]


# ---------------------------------------------------------------------------
# Pricer Interface
# ---------------------------------------------------------------------------

class BasePricer(ABC):
    """
    A pricer wires together Instrument + Engine + Model + MarketData.
    This is the top-level abstraction for pricing a trade.
    """

    @abstractmethod
    def price(
        self,
        instrument: BaseInstrument,
        market_env: MarketEnvironment,
        model: Optional[BaseModel] = None,
        engine: Optional[BaseEngine] = None,
    ) -> PricingResult:
        """Price a single instrument."""
        ...

    @abstractmethod
    def compute_greeks(
        self,
        instrument: BaseInstrument,
        market_env: MarketEnvironment,
        measures: List[RiskMeasure],
    ) -> RiskResult:
        """Compute risk sensitivities."""
        ...


# ---------------------------------------------------------------------------
# Data Repository Interface
# ---------------------------------------------------------------------------

class BaseRepository(ABC):
    """Generic repository interface for data access."""

    @abstractmethod
    def get(self, id: str) -> Optional[Any]:
        ...

    @abstractmethod
    def save(self, entity: Any) -> None:
        ...

    @abstractmethod
    def delete(self, id: str) -> bool:
        ...

    @abstractmethod
    def list_all(self, **filters) -> List[Any]:
        ...


# ---------------------------------------------------------------------------
# Calibration Interface
# ---------------------------------------------------------------------------

class BaseCalibrator(ABC):
    """Abstract base for model calibrators."""

    @abstractmethod
    def calibrate(
        self,
        model: BaseModel,
        market_env: MarketEnvironment,
        instruments: List[Any],
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Calibrate model to market instruments.
        Returns calibration report (parameters, errors, convergence info).
        """
        ...
