"""
Pydantic schemas for the API.

All schemas are instrument-agnostic — instruments are represented
as a type string + arbitrary parameters dict. The registry resolves
the actual class at runtime.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

class UnderlyingData(BaseModel):
    """Market data for a single underlying."""
    spot: float
    vol: float = 0.20
    div_yield: float = 0.0


class MarketDataRequest(BaseModel):
    """
    Market environment specification.

    Generic enough for any asset class:
    - underlyings: spot/vol/div for equities, or spot/vol for FX
    - rate: risk-free rate (flat for now)
    - Additional curves/surfaces can be added via extra_data
    """
    pricing_date: str = Field(..., description="ISO date string, e.g. '2025-01-15'")
    underlyings: Dict[str, UnderlyingData] = Field(
        ..., description="Map of underlying code → market data"
    )
    rate: float = Field(0.05, description="Risk-free rate")
    extra_data: Optional[Dict[str, Any]] = Field(
        None, description="Additional market data (yield curves, vol surfaces, etc.)"
    )


# ---------------------------------------------------------------------------
# Instrument
# ---------------------------------------------------------------------------

class InstrumentRequest(BaseModel):
    """
    Generic instrument specification.

    The 'type' field determines which registered class to use.
    All other fields go into 'params' and are passed to from_dict().

    This design means: adding a new product = registering it,
    zero API changes.
    """
    type: str = Field(..., description="Registered instrument type, e.g. 'vanilla_option', 'barrier_option', 'irs'")
    params: Dict[str, Any] = Field(
        ..., description="Instrument parameters (strike, expiry, etc.)"
    )

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "type": "vanilla_option",
                    "params": {
                        "trade_id": "VAN-001",
                        "underlying": "AAPL",
                        "strike": 150.0,
                        "expiry": "2026-01-15",
                        "option_type": "call",
                        "exercise_type": "european",
                        "currency": "USD",
                    },
                },
                {
                    "type": "barrier_option",
                    "params": {
                        "trade_id": "BAR-001",
                        "underlying": "SPX",
                        "strike": 5800.0,
                        "expiry": "2026-01-15",
                        "option_type": "call",
                        "barrier_type": "down_out",
                        "barrier_level": 5400.0,
                        "rebate": 0.0,
                        "currency": "USD",
                    },
                },
            ]
        }


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------

class PricingRequest(BaseModel):
    """Request to price a single instrument."""
    instrument: InstrumentRequest
    market_data: MarketDataRequest
    model: str = Field("black_scholes", description="Model type")
    engine: str = Field("analytic", description="Engine type")
    engine_params: Optional[Dict[str, Any]] = Field(None, description="Engine parameters")


class PricingResponse(BaseModel):
    """Response from pricing a single instrument."""
    trade_id: str
    npv: float
    currency: str = "USD"
    model: str = ""
    engine: str = ""
    elapsed_ms: float = 0.0
    diagnostics: Optional[Dict[str, Any]] = None


class BatchPricingRequest(BaseModel):
    """Request to price multiple instruments."""
    instruments: List[InstrumentRequest]
    market_data: MarketDataRequest
    model: str = "black_scholes"
    engine: str = "analytic"
    engine_params: Optional[Dict[str, Any]] = None


class BatchPricingResponse(BaseModel):
    """Response from batch pricing."""
    results: List[PricingResponse]
    total_elapsed_ms: float = 0.0


class CompareRequest(BaseModel):
    """Request to compare engines for an instrument."""
    instrument: InstrumentRequest
    market_data: MarketDataRequest
    model: str = "black_scholes"
    engines: Optional[List[str]] = Field(None, description="Engines to compare. None = auto-discover all.")
    engine_configs: Optional[Dict[str, Dict[str, Any]]] = None


class CompareResponse(BaseModel):
    """Engine comparison result."""
    trade_id: str
    reference_engine: str
    reference_npv: Optional[float]
    results: List[Dict[str, Any]]
    greeks_comparison: Optional[List[Dict[str, Any]]] = None


# ---------------------------------------------------------------------------
# Sensitivities
# ---------------------------------------------------------------------------

class GreeksRequest(BaseModel):
    """Request to compute Greeks."""
    instrument: InstrumentRequest
    market_data: MarketDataRequest
    model: str = "black_scholes"
    engine: str = "analytic"
    engine_params: Optional[Dict[str, Any]] = None
    measures: List[str] = Field(
        ["delta", "gamma", "vega", "theta", "rho"],
        description="Greeks to compute",
    )


class GreeksResponse(BaseModel):
    """Greeks result."""
    trade_id: str
    greeks: Dict[str, Optional[float]]
    base_npv: float = 0.0


class LadderRequest(BaseModel):
    """
    Risk factor ladder — works for ANY risk factor.

    risk_factor: "spot", "vol", "rate", "div", "credit_spread", "fx_rate", etc.
    bumps: list of bump values (absolute or relative)
    """
    instruments: List[InstrumentRequest]
    market_data: MarketDataRequest
    model: str = "black_scholes"
    engine: str = "analytic"
    risk_factor: str = Field(..., description="Risk factor to ladder: spot, vol, rate, div, ...")
    bump_type: str = Field("relative", description="'absolute' or 'relative'")
    bumps: List[float] = Field(..., description="List of bump values")


class LadderResponse(BaseModel):
    """Ladder result."""
    risk_factor: str
    bump_type: str
    results: List[Dict[str, Any]]


class MatrixRequest(BaseModel):
    """2D matrix on any two risk factors."""
    instruments: List[InstrumentRequest]
    market_data: MarketDataRequest
    model: str = "black_scholes"
    engine: str = "analytic"
    factor_1: str = Field(..., description="First risk factor")
    factor_1_bumps: List[float] = Field(...)
    factor_1_bump_type: str = "relative"
    factor_2: str = Field(..., description="Second risk factor")
    factor_2_bumps: List[float] = Field(...)
    factor_2_bump_type: str = "absolute"


class MatrixResponse(BaseModel):
    """Matrix result."""
    factor_1: str
    factor_2: str
    matrix: List[List[float]]
    factor_1_labels: List[str]
    factor_2_labels: List[str]


# ---------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------

class ShockSpecRequest(BaseModel):
    """Single shock specification."""
    risk_factor: str
    shock_type: str = "absolute"
    value: float = 0.0
    underlying: Optional[str] = None


class ScenarioRequest(BaseModel):
    """Run a custom scenario."""
    instruments: List[InstrumentRequest]
    market_data: MarketDataRequest
    model: str = "black_scholes"
    engine: str = "analytic"
    scenario_name: str = "custom"
    shocks: List[ShockSpecRequest] = Field(...)


class ScenarioResponse(BaseModel):
    """Scenario result."""
    scenario_name: str
    total_base: float
    total_shocked: float
    total_impact: float
    per_trade: Dict[str, float]
    elapsed_ms: float = 0.0


class StressTestRequest(BaseModel):
    """Run predefined or custom stress scenarios."""
    instruments: List[InstrumentRequest]
    market_data: MarketDataRequest
    model: str = "black_scholes"
    engine: str = "analytic"
    scenarios: Optional[List[str]] = Field(
        None, description="Named scenarios. None = all predefined."
    )


class StressTestResponse(BaseModel):
    """Stress test result."""
    results: List[ScenarioResponse]
    worst_scenario: Optional[str] = None
    best_scenario: Optional[str] = None


class PnLExplainRequest(BaseModel):
    """P&L explain between two market environments."""
    instruments: List[InstrumentRequest]
    base_market: MarketDataRequest
    current_market: MarketDataRequest
    model: str = "black_scholes"
    engine: str = "analytic"


class PnLExplainResponse(BaseModel):
    """P&L explain result."""
    total_actual_pnl: float
    total_explained: float
    total_unexplained: float
    delta_pnl: float
    gamma_pnl: float
    vega_pnl: float
    theta_pnl: float
    rho_pnl: float
    per_trade: List[Dict[str, Any]]


class VaRRequest(BaseModel):
    """VaR computation request."""
    instruments: List[InstrumentRequest]
    market_data: MarketDataRequest
    model: str = "black_scholes"
    engine: str = "analytic"
    method: str = Field("parametric", description="'parametric', 'historical', or 'monte_carlo'")
    confidence: float = 0.99
    horizon_days: int = 1
    annual_vol: float = 0.20
    historical_returns: Optional[List[float]] = Field(
        None, description="Historical returns for historical VaR"
    )
    num_simulations: int = 10000


class VaRResponse(BaseModel):
    """VaR result."""
    var: float
    cvar: float
    confidence: float
    horizon_days: int
    method: str
    portfolio_value: float
    trade_contributions: Optional[Dict[str, float]] = None


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

class ModelCalibrationRequest(BaseModel):
    """
    Calibrate any model to market data.

    model_type determines which calibrator to use.
    calibration_data contains the market quotes.
    """
    model_type: str = Field(..., description="Model to calibrate: 'heston', 'sabr', etc.")
    market_data: MarketDataRequest
    underlying: str
    calibration_data: Dict[str, Any] = Field(
        ..., description="Strikes, expiries, vols, or prices to calibrate to"
    )
    initial_params: Optional[Dict[str, float]] = None
    optimizer: str = "levenberg_marquardt"


class ModelCalibrationResponse(BaseModel):
    """Calibration result."""
    model_type: str
    parameters: Dict[str, float]
    fit_rmse: float
    fit_report: Optional[List[Dict[str, Any]]] = None
    elapsed_ms: float = 0.0


class ImpliedVolRequest(BaseModel):
    """Implied vol computation."""
    market_price: float
    spot: float
    strike: float
    T: float
    rate: float
    div_yield: float = 0.0
    is_call: bool = True
    method: str = "newton"


class ImpliedVolResponse(BaseModel):
    """Implied vol result."""
    implied_vol: float
    converged: bool
    method: str


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class RegistryEntry(BaseModel):
    key: str
    description: Optional[str] = None


class EngineCompatibility(BaseModel):
    instrument_type: str
    engine_type: str