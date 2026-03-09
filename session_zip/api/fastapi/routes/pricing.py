"""
FastAPI routes for the pricing platform.

Provides REST endpoints for:
- Single trade pricing
- Batch pricing
- Greeks computation
- Market data queries
- Portfolio operations
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1", tags=["pricing"])


# ---------------------------------------------------------------------------
# Request / Response Schemas
# ---------------------------------------------------------------------------

class PriceRequest(BaseModel):
    """Single trade pricing request."""
    trade_id: str
    instrument_type: str
    asset_class: str
    currency: str = "USD"
    pricing_date: Optional[date] = None
    model_type: Optional[str] = None
    engine_type: Optional[str] = None
    engine_params: Optional[Dict[str, Any]] = None
    instrument_params: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        json_schema_extra = {
            "example": {
                "trade_id": "OPT-001",
                "instrument_type": "vanilla_option",
                "asset_class": "equity",
                "currency": "USD",
                "model_type": "black_scholes",
                "engine_type": "analytic",
                "instrument_params": {
                    "underlying": "AAPL",
                    "strike": 150.0,
                    "expiry": "2025-12-19",
                    "option_type": "call",
                    "exercise_type": "european",
                    "notional": 100,
                },
            }
        }


class PriceResponse(BaseModel):
    trade_id: str
    npv: float
    currency: str
    pricing_date: str
    engine_used: str = ""
    model_used: str = ""
    greeks: Dict[str, Optional[float]] = Field(default_factory=dict)
    diagnostics: Dict[str, Any] = Field(default_factory=dict)


class BatchPriceRequest(BaseModel):
    trades: List[PriceRequest]
    pricing_date: Optional[date] = None


class BatchPriceResponse(BaseModel):
    results: List[PriceResponse]
    total_trades: int
    successful: int
    failed: int
    elapsed_seconds: float


class GreeksRequest(BaseModel):
    trade_id: str
    instrument_type: str
    asset_class: str
    currency: str = "USD"
    instrument_params: Dict[str, Any] = Field(default_factory=dict)
    measures: List[str] = Field(default=["delta", "gamma", "vega", "theta"])
    bump_size: float = 0.01
    model_type: Optional[str] = None
    engine_type: Optional[str] = None


class GreeksResponse(BaseModel):
    trade_id: str
    greeks: Dict[str, Optional[float]]


class HealthResponse(BaseModel):
    status: str
    version: str
    registered_instruments: int
    registered_engines: int
    registered_models: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/health", response_model=HealthResponse)
async def health():
    """Health check with registry stats."""
    from registry import engine_registry, instrument_registry, model_registry
    return HealthResponse(
        status="ok",
        version="0.1.0",
        registered_instruments=len(instrument_registry),
        registered_engines=len(engine_registry),
        registered_models=len(model_registry),
    )


@router.post("/price", response_model=PriceResponse)
async def price_trade(request: PriceRequest):
    """Price a single trade."""
    try:
        from services.pricers.pricing_service import PricingService
        from _factory import build_instrument, build_market_env

        instrument = build_instrument(request)
        market_env = build_market_env(request.pricing_date)
        service = PricingService()
        result = service.price(
            instrument, market_env,
            model_type=request.model_type,
            engine_type=request.engine_type,
            engine_params=request.engine_params,
        )

        return PriceResponse(
            trade_id=str(result.trade_id),
            npv=result.npv,
            currency=result.currency,
            pricing_date=str(result.pricing_date.value),
            engine_used=result.engine_used,
            model_used=result.model_used,
            greeks=result.greeks,
            diagnostics=result.diagnostics,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/price/batch", response_model=BatchPriceResponse)
async def price_batch(request: BatchPriceRequest):
    """Price a batch of trades."""
    import time
    from services.pricers.pricing_service import PricingService
    from _factory import build_instrument, build_market_env

    t0 = time.perf_counter()
    market_env = build_market_env(request.pricing_date)
    service = PricingService()

    results = []
    successful = 0
    failed = 0

    for trade_req in request.trades:
        try:
            instrument = build_instrument(trade_req)
            result = service.price(instrument, market_env)
            results.append(PriceResponse(
                trade_id=str(result.trade_id),
                npv=result.npv,
                currency=result.currency,
                pricing_date=str(result.pricing_date.value),
                engine_used=result.engine_used,
                model_used=result.model_used,
                diagnostics=result.diagnostics,
            ))
            successful += 1
        except Exception as e:
            results.append(PriceResponse(
                trade_id=trade_req.trade_id,
                npv=float("nan"),
                currency=trade_req.currency,
                pricing_date=str(request.pricing_date or date.today()),
                diagnostics={"error": str(e)},
            ))
            failed += 1

    return BatchPriceResponse(
        results=results,
        total_trades=len(request.trades),
        successful=successful,
        failed=failed,
        elapsed_seconds=round(time.perf_counter() - t0, 4),
    )


@router.post("/greeks", response_model=GreeksResponse)
async def compute_greeks(request: GreeksRequest):
    """Compute Greeks for a single trade."""
    try:
        from core.enums.definitions import RiskMeasure
        from services.pricers.pricing_service import PricingService
        from _factory import build_instrument, build_market_env

        instrument = build_instrument(request)
        market_env = build_market_env()
        service = PricingService()

        measure_map = {m.value: m for m in RiskMeasure}
        measures = [measure_map[m] for m in request.measures if m in measure_map]

        result = service.compute_greeks(
            instrument, market_env, measures=measures,
            bump_size=request.bump_size,
            model_type=request.model_type,
            engine_type=request.engine_type,
        )

        return GreeksResponse(
            trade_id=str(result.trade_id),
            greeks=result.greeks,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/registry/instruments")
async def list_instruments():
    """List all registered instrument types."""
    from registry import instrument_registry
    return {"instruments": instrument_registry.keys()}


@router.get("/registry/engines")
async def list_engines():
    """List all registered engine configurations."""
    from registry import engine_registry
    return {"engines": [str(k) for k in engine_registry.keys()]}


@router.get("/registry/models")
async def list_models():
    """List all registered model types."""
    from registry import model_registry
    return {"models": model_registry.keys()}
