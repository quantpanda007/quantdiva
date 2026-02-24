"""
Market Data API endpoints.

Provides live market data from OpenBB / yfinance to the frontend.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/market-data", tags=["Market Data (Live)"])


# ---------------------------------------------------------------
# Response models
# ---------------------------------------------------------------

class EquityQuoteResponse(BaseModel):
    symbol: str
    spot: float
    prev_close: float = 0
    change_pct: float = 0
    volume: int = 0
    source: str = ""


class FXRateResponse(BaseModel):
    pair: str
    rate: float
    source: str = ""


class YieldCurvePointResponse(BaseModel):
    maturity: str
    maturity_years: float
    rate: float


class YieldCurveResponse(BaseModel):
    currency: str
    curve_date: str
    points: list[YieldCurvePointResponse]
    source: str = ""


class ProviderStatusResponse(BaseModel):
    providers: list[dict]
    cache_size: int
    cache_ttl: float


class LiveMarketDataResponse(BaseModel):
    """Full market data response for pricing."""
    pricing_date: str
    rate: float
    underlyings: dict
    yield_curve: Optional[list] = None
    source: str = ""


# ---------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------

@router.get("/status", response_model=ProviderStatusResponse)
def get_provider_status():
    """Check which market data providers are available."""
    from market.providers.market_data_service import market_data_service
    return market_data_service.status()


@router.get("/equity/quote", response_model=EquityQuoteResponse)
def get_equity_quote(symbol: str = Query(..., description="Ticker symbol")):
    """Get live equity price quote."""
    from market.providers.market_data_service import market_data_service

    snap = market_data_service.get_equity_spot(symbol.upper())
    if not snap:
        raise HTTPException(404, f"No data found for {symbol}")

    return EquityQuoteResponse(
        symbol=snap.symbol,
        spot=snap.spot,
        prev_close=snap.prev_close,
        change_pct=snap.change_pct,
        volume=snap.volume,
        source=snap.source,
    )


@router.get("/fx/rate", response_model=FXRateResponse)
def get_fx_rate(pair: str = Query(..., description="Currency pair e.g. EURUSD")):
    """Get live FX rate."""
    from market.providers.market_data_service import market_data_service

    snap = market_data_service.get_fx_rate(pair.upper())
    if not snap:
        raise HTTPException(404, f"No FX data for {pair}")

    return FXRateResponse(
        pair=snap.pair,
        rate=snap.rate,
        source=snap.source,
    )


@router.get("/yield-curve", response_model=YieldCurveResponse)
def get_yield_curve(
    currency: str = Query("USD", description="Currency code"),
):
    """Get live Treasury yield curve."""
    from market.providers.market_data_service import market_data_service

    yc = market_data_service.get_yield_curve(currency.upper())
    if not yc:
        raise HTTPException(404, f"No yield curve data for {currency}")

    return YieldCurveResponse(
        currency=yc.currency,
        curve_date=yc.curve_date.isoformat(),
        points=[
            YieldCurvePointResponse(
                maturity=p.maturity,
                maturity_years=p.maturity_years,
                rate=p.rate,
            ) for p in yc.points
        ],
        source=yc.source,
    )


@router.get("/snapshot", response_model=LiveMarketDataResponse)
def get_market_snapshot(
    underlying: Optional[str] = Query(None, description="Equity ticker"),
    ccy_pair: Optional[str] = Query(None, description="FX pair e.g. EURUSD"),
    currency: str = Query("USD", description="Currency for yield curve"),
):
    """Get full market data snapshot for pricing.

    Returns a market data dict that can be fed directly to the pricing engine.
    """
    from market.providers.market_data_service import market_data_service

    data = market_data_service.build_market_env_data(
        underlying=underlying.upper() if underlying else None,
        ccy_pair=ccy_pair.upper() if ccy_pair else None,
        currency=currency.upper(),
    )

    return LiveMarketDataResponse(
        pricing_date=data["pricing_date"],
        rate=data["rate"],
        underlyings=data["underlyings"],
        yield_curve=data.get("yield_curve"),
        source=", ".join(market_data_service.available_providers),
    )


@router.post("/cache/clear")
def clear_cache():
    """Clear the market data cache."""
    from market.providers.market_data_service import market_data_service
    market_data_service.clear_cache()
    return {"status": "cache_cleared"}