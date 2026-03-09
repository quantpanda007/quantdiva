"""
Historical market data API endpoints.

Endpoints:
    GET  /historical/status       — DB stats and scheduler status
    GET  /historical/equity       — Equity price history
    GET  /historical/fx           — FX rate history
    GET  /historical/yield-curve  — Historical yield curve
    POST /historical/refresh      — Trigger data refresh
    POST /historical/import       — Import external data
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/historical", tags=["Historical Data"])


# ── Response models ──────────────────────────────────────────

class EquityBarResponse(BaseModel):
    symbol: str
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: str


class FXRateResponse(BaseModel):
    pair: str
    date: str
    rate: float
    source: str


class YieldPointResponse(BaseModel):
    tenor: str
    tenor_years: float
    rate: float


class YieldCurveHistResponse(BaseModel):
    currency: str
    date: str
    points: List[YieldPointResponse]
    source: str


class RefreshResponse(BaseModel):
    results: List[Dict[str, Any]]


class StatsResponse(BaseModel):
    db_stats: Dict[str, Any]
    scheduler: Dict[str, Any]
    universe: Dict[str, Any]


class ImportRequest(BaseModel):
    table: str
    rows: List[Dict[str, Any]]
    source: str = "external"


# ── Endpoints ────────────────────────────────────────────────

@router.get("/status", response_model=StatsResponse)
def get_historical_status():
    """Database stats, scheduler status, and asset universe."""
    from market.historical.store import store
    from market.historical.scheduler import get_scheduler_status
    from market.historical.assets import universe

    return StatsResponse(
        db_stats=store.get_stats(),
        scheduler=get_scheduler_status(),
        universe={
            "equity": universe.equity,
            "fx": universe.fx,
            "yield_curves": universe.yield_curves,
            "option_chains": universe.option_chains,
            "cds_entities": universe.cds_entities,
        },
    )


@router.get("/equity", response_model=List[EquityBarResponse])
def get_equity_history(
    symbol: str = Query(..., description="Ticker symbol, e.g. AAPL"),
    start: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
):
    """Get stored equity price history."""
    from market.historical.store import store

    start_dt = date.fromisoformat(start) if start else None
    end_dt = date.fromisoformat(end) if end else None

    bars = store.get_equity_history(symbol.upper(), start_dt, end_dt)
    if not bars:
        raise HTTPException(404, f"No data for {symbol}. Run a refresh first.")

    return [
        EquityBarResponse(
            symbol=b.symbol, date=b.date.isoformat(),
            open=b.open, high=b.high, low=b.low,
            close=b.close, volume=b.volume, source=b.source,
        ) for b in bars
    ]


@router.get("/fx", response_model=List[FXRateResponse])
def get_fx_history(
    pair: str = Query(..., description="Currency pair, e.g. EURUSD"),
    start: Optional[str] = Query(None, description="Start date"),
    end: Optional[str] = Query(None, description="End date"),
):
    """Get stored FX rate history."""
    from market.historical.store import store

    start_dt = date.fromisoformat(start) if start else None
    end_dt = date.fromisoformat(end) if end else None

    rates = store.get_fx_history(pair.upper(), start_dt, end_dt)
    if not rates:
        raise HTTPException(404, f"No data for {pair}. Run a refresh first.")

    return [
        FXRateResponse(
            pair=r.pair, date=r.date.isoformat(),
            rate=r.rate, source=r.source,
        ) for r in rates
    ]


@router.get("/yield-curve", response_model=YieldCurveHistResponse)
def get_historical_yield_curve(
    currency: str = Query("USD", description="Currency"),
    date_str: Optional[str] = Query(None, alias="date", description="Curve date (YYYY-MM-DD)"),
):
    """Get stored yield curve for a specific date."""
    from market.historical.store import store

    curve_date = date.fromisoformat(date_str) if date_str else None
    points = store.get_yield_curve(currency.upper(), curve_date)

    if not points:
        raise HTTPException(404, f"No yield curve data for {currency}. Run a refresh first.")

    return YieldCurveHistResponse(
        currency=currency.upper(),
        date=points[0].date.isoformat(),
        points=[
            YieldPointResponse(
                tenor=p.tenor, tenor_years=p.tenor_years, rate=p.rate,
            ) for p in points
        ],
        source=points[0].source,
    )


@router.get("/yield-curve/dates", response_model=List[str])
def get_yield_curve_dates(
    currency: str = Query("USD"),
):
    """List all dates with stored yield curve data."""
    from market.historical.store import store
    dates = store.get_yield_curve_dates(currency.upper())
    return [d.isoformat() for d in dates]


@router.post("/refresh", response_model=RefreshResponse)
def trigger_refresh(
    equity: bool = Query(False),
    fx: bool = Query(False),
    yield_curves: bool = Query(False),
    options: bool = Query(False),
    all_assets: bool = Query(False, alias="all"),
    days: int = Query(365, description="Lookback days"),
):
    """Trigger a manual data refresh."""
    from market.historical.fetcher import fetcher

    results = []

    if all_assets or equity:
        r = fetcher.refresh_equity(lookback_days=days)
        results.append(_status_to_dict(r))
    if all_assets or fx:
        r = fetcher.refresh_fx(lookback_days=days)
        results.append(_status_to_dict(r))
    if all_assets or yield_curves:
        r = fetcher.refresh_yield_curves()
        results.append(_status_to_dict(r))
    if all_assets or options:
        r = fetcher.refresh_option_chains()
        results.append(_status_to_dict(r))

    if not results:
        raise HTTPException(400, "No asset class selected. Use ?all=true or ?equity=true etc.")

    return RefreshResponse(results=results)


@router.post("/import")
def import_external_data(req: ImportRequest):
    """Import external data into a table.

    Accepts arbitrary rows with column names matching the table schema.
    Useful for Bloomberg, Refinitiv, or CSV-sourced data.
    """
    from market.historical.store import store
    from market.historical import (
        HistoricalBar, HistoricalFXRate, HistoricalYieldPoint, HistoricalCDSSpread,
    )

    table = req.table
    source = req.source
    count = 0

    try:
        if table == "equity_prices":
            bars = [
                HistoricalBar(
                    symbol=r["symbol"], date=date.fromisoformat(str(r["date"])[:10]),
                    open=float(r.get("open", 0)), high=float(r.get("high", 0)),
                    low=float(r.get("low", 0)), close=float(r["close"]),
                    volume=int(r.get("volume", 0)), source=source,
                ) for r in req.rows
            ]
            count = store.insert_equity_bars(bars)

        elif table == "fx_rates":
            rates = [
                HistoricalFXRate(
                    pair=r["pair"], date=date.fromisoformat(str(r["date"])[:10]),
                    rate=float(r["rate"]), source=source,
                ) for r in req.rows
            ]
            count = store.insert_fx_rates(rates)

        elif table == "yield_curves":
            points = [
                HistoricalYieldPoint(
                    currency=r["currency"], date=date.fromisoformat(str(r["date"])[:10]),
                    tenor=r["tenor"], tenor_years=float(r["tenor_years"]),
                    rate=float(r["rate"]), source=source,
                ) for r in req.rows
            ]
            count = store.insert_yield_points(points)

        elif table == "cds_spreads":
            spreads = [
                HistoricalCDSSpread(
                    entity=r["entity"], date=date.fromisoformat(str(r["date"])[:10]),
                    tenor=r.get("tenor", "5Y"), spread=float(r["spread"]),
                    recovery=float(r.get("recovery", 0.40)), source=source,
                ) for r in req.rows
            ]
            count = store.insert_cds_spreads(spreads)

        else:
            raise HTTPException(400, f"Unknown table: {table}")

    except (KeyError, ValueError) as e:
        raise HTTPException(422, f"Data format error: {e}")

    return {"table": table, "rows_imported": count, "source": source}


# ── Helpers ──────────────────────────────────────────────────

def _status_to_dict(status) -> dict:
    return {
        "asset_class": status.asset_class,
        "symbols_refreshed": status.symbols_refreshed,
        "rows_inserted": status.rows_inserted,
        "rows_skipped": status.rows_skipped,
        "errors": status.errors,
        "duration_seconds": status.duration_seconds,
    }
