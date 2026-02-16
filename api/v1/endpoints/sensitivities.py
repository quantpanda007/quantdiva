"""
Sensitivities endpoints — Greeks, ladders, matrices.

All risk-factor agnostic: ladders work on any factor (spot, vol, rate, etc.)
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.v1.schemas import (
    GreeksRequest,
    GreeksResponse,
    LadderRequest,
    LadderResponse,
    MatrixRequest,
    MatrixResponse,
)
from api.v1.helpers import (
    build_instrument_from_request,
    build_instruments_from_request,
    build_market_env_from_request,
)
from services.greeks.bump_reprice import BumpAndRepriceGreeks
from services.pricers.pricing_service import PricingService
from services.risk.scenario_engine import ScenarioEngine, Scenario, ShockSpec

router = APIRouter()
ps = PricingService()


@router.post("/greeks", response_model=GreeksResponse)
def compute_greeks(req: GreeksRequest):
    """Compute Greeks for any instrument via bump-and-reprice."""
    try:
        instrument = build_instrument_from_request(req.instrument)
        underlying = getattr(instrument, "underlying", "")
        market_env = build_market_env_from_request(req.market_data, underlying=underlying)

        greeks_svc = BumpAndRepriceGreeks(pricing_service=ps)
        result = greeks_svc.compute(
            instrument=instrument,
            market_env=market_env,
            model_type=req.model,
            engine_type=req.engine,
            engine_params=req.engine_params,
            measures=req.measures,
        )

        return GreeksResponse(
            trade_id=str(instrument.trade_id()),
            greeks=result.greeks,
            base_npv=result.base_npv,
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/ladder", response_model=LadderResponse)
def run_ladder(req: LadderRequest):
    """
    Run a risk factor ladder on any factor.

    Prices portfolio at each bump level and returns P&L impact.
    """
    try:
        instruments = build_instruments_from_request(req.instruments)
        # Build env for first instrument's underlying
        underlying = getattr(instruments[0], "underlying", "") if instruments else ""
        market_env = build_market_env_from_request(req.market_data, underlying=underlying)

        engine = ScenarioEngine(
            pricing_service=ps,
            model_type=req.model,
            engine_type=req.engine,
        )

        results = []
        for bump in req.bumps:
            scenario = Scenario(
                name=f"{req.risk_factor}_{bump}",
                shocks=[ShockSpec(
                    risk_factor=req.risk_factor,
                    shock_type=req.bump_type,
                    value=bump,
                )],
            )
            sr = engine.run_scenario(instruments, market_env, scenario)
            results.append({
                "bump": bump,
                "total_base": round(sr.total_base, 6),
                "total_shocked": round(sr.total_shocked, 6),
                "total_impact": round(sr.total_impact, 6),
                "per_trade": {k: round(v, 6) for k, v in sr.pnl_impact.items()},
            })

        return LadderResponse(
            risk_factor=req.risk_factor,
            bump_type=req.bump_type,
            results=results,
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/matrix", response_model=MatrixResponse)
def run_matrix(req: MatrixRequest):
    """
    Run a 2D risk factor matrix on any two factors.

    Returns a matrix of P&L impacts.
    """
    try:
        instruments = build_instruments_from_request(req.instruments)
        underlying = getattr(instruments[0], "underlying", "") if instruments else ""
        market_env = build_market_env_from_request(req.market_data, underlying=underlying)

        engine = ScenarioEngine(
            pricing_service=ps,
            model_type=req.model,
            engine_type=req.engine,
        )

        matrix = []
        for b1 in req.factor_1_bumps:
            row = []
            for b2 in req.factor_2_bumps:
                scenario = Scenario(
                    name=f"{req.factor_1}={b1}_{req.factor_2}={b2}",
                    shocks=[
                        ShockSpec(req.factor_1, req.factor_1_bump_type, b1),
                        ShockSpec(req.factor_2, req.factor_2_bump_type, b2),
                    ],
                )
                sr = engine.run_scenario(instruments, market_env, scenario)
                row.append(round(sr.total_impact, 6))
            matrix.append(row)

        return MatrixResponse(
            factor_1=req.factor_1,
            factor_2=req.factor_2,
            matrix=matrix,
            factor_1_labels=[f"{req.factor_1}={b}" for b in req.factor_1_bumps],
            factor_2_labels=[f"{req.factor_2}={b}" for b in req.factor_2_bumps],
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))