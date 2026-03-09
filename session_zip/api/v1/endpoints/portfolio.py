"""
Portfolio endpoints — portfolio-level valuation, Greeks, risk.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.v1.schemas import InstrumentRequest, MarketDataRequest
from api.v1.helpers import build_instrument_from_request, build_market_env_from_request
from core.portfolio import Portfolio, PortfolioPosition
from services.pricers.pricing_service import PricingService

router = APIRouter()
ps = PricingService()

# In-memory portfolio store (production: database)
_portfolios: Dict[str, Portfolio] = {}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PositionRequest(BaseModel):
    instrument: InstrumentRequest
    quantity: float = 1.0
    direction: str = "buy"
    book: str = "default"
    tags: Dict[str, str] = Field(default_factory=dict)


class PortfolioCreateRequest(BaseModel):
    portfolio_id: str
    name: str = ""
    positions: List[PositionRequest] = Field(default_factory=list)


class PortfolioValueRequest(BaseModel):
    portfolio_id: str
    market_data: MarketDataRequest
    model: str = "black_scholes"
    engine: str = "analytic"
    engine_params: Optional[Dict[str, Any]] = None
    compute_greeks: bool = True


class PortfolioScenarioRequest(BaseModel):
    portfolio_id: str
    market_data: MarketDataRequest
    model: str = "black_scholes"
    engine: str = "analytic"
    scenario_name: str = "custom"
    shocks: List[Dict[str, Any]] = Field(...)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/create")
def create_portfolio(req: PortfolioCreateRequest):
    """Create a portfolio with positions."""
    try:
        portfolio = Portfolio(
            portfolio_id=req.portfolio_id,
            name=req.name,
        )

        for pos_req in req.positions:
            instrument = build_instrument_from_request(pos_req.instrument)
            portfolio.add_position(PortfolioPosition(
                instrument=instrument,
                quantity=pos_req.quantity,
                direction=pos_req.direction,
                book=pos_req.book,
                tags=pos_req.tags,
            ))

        _portfolios[req.portfolio_id] = portfolio

        return {
            "portfolio_id": portfolio.portfolio_id,
            "name": portfolio.name,
            "num_positions": len(portfolio.positions),
            "books": portfolio.books,
            "instrument_types": portfolio.instrument_types,
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/list")
def list_portfolios():
    """List all portfolios."""
    return [
        {
            "portfolio_id": p.portfolio_id,
            "name": p.name,
            "num_positions": len(p.positions),
        }
        for p in _portfolios.values()
    ]


@router.get("/{portfolio_id}")
def get_portfolio(portfolio_id: str):
    """Get portfolio details."""
    pf = _portfolios.get(portfolio_id)
    if pf is None:
        raise HTTPException(status_code=404, detail=f"Portfolio '{portfolio_id}' not found")

    return {
        "portfolio_id": pf.portfolio_id,
        "name": pf.name,
        "num_positions": len(pf.positions),
        "books": pf.books,
        "instrument_types": pf.instrument_types,
        "positions": [
            {
                "trade_id": p.trade_id,
                "instrument_type": p.instrument.instrument_type().value,
                "quantity": p.quantity,
                "direction": p.direction,
                "book": p.book,
            }
            for p in pf.positions
        ],
    }


@router.post("/{portfolio_id}/add-position")
def add_position(portfolio_id: str, req: PositionRequest):
    """Add a position to an existing portfolio."""
    pf = _portfolios.get(portfolio_id)
    if pf is None:
        raise HTTPException(status_code=404, detail=f"Portfolio '{portfolio_id}' not found")

    try:
        instrument = build_instrument_from_request(req.instrument)
        pf.add_position(PortfolioPosition(
            instrument=instrument,
            quantity=req.quantity,
            direction=req.direction,
            book=req.book,
            tags=req.tags,
        ))

        return {"status": "ok", "num_positions": len(pf.positions)}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/value")
def value_portfolio(req: PortfolioValueRequest):
    """Full portfolio valuation with aggregated Greeks."""
    pf = _portfolios.get(req.portfolio_id)
    if pf is None:
        raise HTTPException(status_code=404, detail=f"Portfolio '{req.portfolio_id}' not found")

    try:
        # Build env for all underlyings
        underlying = None
        for pos in pf.positions:
            und = getattr(pos.instrument, "underlying", "")
            if und in req.market_data.underlyings:
                underlying = und
                break

        market_env = build_market_env_from_request(req.market_data, underlying=underlying)

        result = pf.value(
            market_env=market_env,
            pricing_service=ps,
            model_type=req.model,
            engine_type=req.engine,
            engine_params=req.engine_params,
            compute_greeks=req.compute_greeks,
        )

        return result.to_dict()

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/scenario")
def portfolio_scenario(req: PortfolioScenarioRequest):
    """Run a scenario on a portfolio."""
    pf = _portfolios.get(req.portfolio_id)
    if pf is None:
        raise HTTPException(status_code=404, detail=f"Portfolio '{req.portfolio_id}' not found")

    try:
        from services.risk.scenario_engine import ScenarioEngine, Scenario, ShockSpec

        underlying = None
        for pos in pf.positions:
            und = getattr(pos.instrument, "underlying", "")
            if und in req.market_data.underlyings:
                underlying = und
                break

        market_env = build_market_env_from_request(req.market_data, underlying=underlying)

        scenario = Scenario(
            name=req.scenario_name,
            shocks=[
                ShockSpec(
                    risk_factor=s.get("risk_factor", "spot"),
                    shock_type=s.get("shock_type", "relative"),
                    value=s.get("value", 0.0),
                    underlying=s.get("underlying"),
                )
                for s in req.shocks
            ],
        )

        engine = ScenarioEngine(
            pricing_service=ps,
            model_type=req.model,
            engine_type=req.engine,
        )
        result = engine.run_scenario(pf.instruments, market_env, scenario)

        return {
            "scenario_name": result.scenario_name,
            "total_base": round(result.total_base, 6),
            "total_shocked": round(result.total_shocked, 6),
            "total_impact": round(result.total_impact, 6),
            "per_trade": {k: round(v, 6) for k, v in result.pnl_impact.items()},
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{portfolio_id}")
def delete_portfolio(portfolio_id: str):
    """Delete a portfolio."""
    if portfolio_id in _portfolios:
        del _portfolios[portfolio_id]
        return {"status": "deleted", "portfolio_id": portfolio_id}
    raise HTTPException(status_code=404, detail=f"Portfolio '{portfolio_id}' not found")