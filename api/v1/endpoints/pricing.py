"""
Pricing endpoints — instrument-agnostic.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException

from api.v1.schemas import (
    PricingRequest,
    PricingResponse,
    BatchPricingRequest,
    BatchPricingResponse,
    CompareRequest,
    CompareResponse,
)
from api.v1.helpers import (
    build_instrument_from_request,
    build_instruments_from_request,
    build_market_env_from_request,
)
from services.pricers.pricing_service import PricingService
from services.comparison.engine_comparator import EngineComparator

router = APIRouter()
ps = PricingService()


@router.post("/single", response_model=PricingResponse)
def price_single(req: PricingRequest):
    """Price a single instrument of any type."""
    t0 = time.perf_counter()
    try:
        instrument = build_instrument_from_request(req.instrument)
        underlying = getattr(instrument, "underlying", "")
        market_env = build_market_env_from_request(req.market_data, underlying=underlying)

        result = ps.price(
            instrument=instrument,
            market_env=market_env,
            model_type=req.model,
            engine_type=req.engine,
            engine_params=req.engine_params,
        )

        elapsed_ms = (time.perf_counter() - t0) * 1000

        # Clean diagnostics for JSON serialization
        diag = {}
        for k, v in (result.diagnostics or {}).items():
            if k.endswith("_ref"):
                continue
            if isinstance(v, (int, float, str, bool, list, dict, type(None))):
                diag[k] = v
            elif isinstance(v, tuple):
                diag[k] = list(v)

        return PricingResponse(
            trade_id=str(result.trade_id),
            npv=result.npv,
            currency=result.currency or "USD",
            model=req.model,
            engine=req.engine,
            elapsed_ms=round(elapsed_ms, 2),
            diagnostics=diag,
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/batch", response_model=BatchPricingResponse)
def price_batch(req: BatchPricingRequest):
    """Price multiple instruments in one call."""
    t0 = time.perf_counter()
    results = []

    for inst_req in req.instruments:
        try:
            instrument = build_instrument_from_request(inst_req)
            underlying = getattr(instrument, "underlying", "")
            market_env = build_market_env_from_request(req.market_data, underlying=underlying)

            result = ps.price(
                instrument=instrument,
                market_env=market_env,
                model_type=req.model,
                engine_type=req.engine,
                engine_params=req.engine_params,
            )

            results.append(PricingResponse(
                trade_id=str(result.trade_id),
                npv=result.npv,
                currency=result.currency or "USD",
                model=req.model,
                engine=req.engine,
            ))
        except Exception as e:
            results.append(PricingResponse(
                trade_id=inst_req.params.get("trade_id", "unknown"),
                npv=float("nan"),
                diagnostics={"error": str(e)},
            ))

    total_ms = (time.perf_counter() - t0) * 1000
    return BatchPricingResponse(results=results, total_elapsed_ms=round(total_ms, 2))


@router.post("/compare", response_model=CompareResponse)
def compare_engines(req: CompareRequest):
    """Compare pricing across multiple engines for the same instrument."""
    try:
        instrument = build_instrument_from_request(req.instrument)
        underlying = getattr(instrument, "underlying", "")
        market_env = build_market_env_from_request(req.market_data, underlying=underlying)

        comparator = EngineComparator()
        report = comparator.compare(
            instrument=instrument,
            market_env=market_env,
            model_type=req.model,
            engine_types=req.engines,
            engine_configs=req.engine_configs,
        )

        return CompareResponse(
            trade_id=report.trade_id,
            reference_engine=report.reference_engine,
            reference_npv=report.reference_npv,
            results=report.differences(),
            greeks_comparison=report.greeks_comparison() or None,
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))