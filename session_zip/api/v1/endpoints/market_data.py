"""
Market data endpoints — build and query market environments.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.v1.schemas import MarketDataRequest
from api.v1.helpers import build_market_env_from_request

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class VolQueryRequest(BaseModel):
    """Query vol surface at specific points."""
    market_data: MarketDataRequest
    underlying: str
    queries: List[Dict[str, float]] = Field(
        ..., description="List of {T: float, strike: float} to query"
    )


class VolQueryResponse(BaseModel):
    results: List[Dict[str, float]]


class YieldCurveQueryRequest(BaseModel):
    """Query yield curve at specific tenors."""
    market_data: MarketDataRequest
    tenors: List[float] = Field(..., description="Tenors in years, e.g. [0.25, 0.5, 1, 2, 5, 10]")


class YieldCurveQueryResponse(BaseModel):
    results: List[Dict[str, float]]


class VolSurfaceBuildRequest(BaseModel):
    """Build and calibrate a vol surface."""
    pricing_date: str
    underlying: str
    spot: float
    rate: float = 0.05
    div_yield: float = 0.0
    strikes: List[float]
    expiry_dates: List[str]
    vol_matrix: List[List[float]]
    method: str = Field("svi", description="'svi', 'grid', or 'flat'")


class VolSurfaceBuildResponse(BaseModel):
    method: str
    num_expiries: int
    num_strikes: int
    fit_report: Optional[List[Dict[str, Any]]] = None
    sample_vols: Optional[List[Dict[str, float]]] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/vol-surface/query", response_model=VolQueryResponse)
def query_vol_surface(req: VolQueryRequest):
    """Query implied vol at specific (T, strike) points."""
    try:
        market_env = build_market_env_from_request(req.market_data, underlying=req.underlying)
        vol_handle = market_env.vol_surfaces.get(req.underlying)

        if vol_handle is None:
            raise ValueError(f"No vol surface for '{req.underlying}'")

        results = []
        for q in req.queries:
            T = q["T"]
            strike = q["strike"]
            vol = vol_handle.blackVol(T, strike)
            results.append({"T": T, "strike": strike, "vol": round(vol, 6)})

        return VolQueryResponse(results=results)

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/vol-surface/build", response_model=VolSurfaceBuildResponse)
def build_vol_surface(req: VolSurfaceBuildRequest):
    """Build and calibrate a vol surface from market quotes."""
    try:
        from core.types.value_objects import PricingDate

        pricing_date = PricingDate(date.fromisoformat(req.pricing_date))
        expiry_dates = [date.fromisoformat(d) for d in req.expiry_dates]

        if req.method == "svi":
            from market.volatility.vol_surface_ext import SVIVolSurface

            surface = SVIVolSurface.from_market_quotes(
                pricing_date=pricing_date,
                strikes=req.strikes,
                expiry_dates=expiry_dates,
                vol_matrix=req.vol_matrix,
                spot=req.spot,
                rate=req.rate,
                div_yield=req.div_yield,
            )

            # Sample vols at ATM across expiries
            sample_vols = []
            for s in surface.slices:
                vol = s.implied_vol(req.spot)
                sample_vols.append({"T": round(s.T, 4), "atm_vol": round(vol, 6)})

            return VolSurfaceBuildResponse(
                method="svi",
                num_expiries=len(surface.slices),
                num_strikes=len(req.strikes),
                fit_report=surface.fit_report(),
                sample_vols=sample_vols,
            )

        elif req.method == "grid":
            return VolSurfaceBuildResponse(
                method="grid",
                num_expiries=len(expiry_dates),
                num_strikes=len(req.strikes),
            )

        else:
            raise ValueError(f"Unknown method: '{req.method}'. Supported: svi, grid")

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/yield-curve/query", response_model=YieldCurveQueryResponse)
def query_yield_curve(req: YieldCurveQueryRequest):
    """Query yield curve at specific tenors."""
    try:
        import QuantLib as ql
        market_env = build_market_env_from_request(req.market_data)

        # Get the first discount curve
        curve_key = list(market_env.discount_curves.keys())[0]
        curve = market_env.discount_curves[curve_key]

        results = []
        for T in req.tenors:
            zero_rate = curve.zeroRate(T, ql.Continuous, ql.Annual).rate()
            discount = curve.discount(T)
            results.append({
                "T": T,
                "zero_rate": round(zero_rate, 6),
                "discount_factor": round(discount, 6),
            })

        return YieldCurveQueryResponse(results=results)

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))