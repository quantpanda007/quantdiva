"""
Risk endpoints — scenarios, stress tests, P&L explain, VaR.
"""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException

from api.v1.schemas import (
    ScenarioRequest,
    ScenarioResponse,
    StressTestRequest,
    StressTestResponse,
    PnLExplainRequest,
    PnLExplainResponse,
    VaRRequest,
    VaRResponse,
)
from api.v1.helpers import (
    build_instruments_from_request,
    build_market_env_from_request,
)
from services.pricers.pricing_service import PricingService
from services.risk.scenario_engine import (
    ScenarioEngine,
    Scenario,
    ShockSpec,
    PREDEFINED_SCENARIOS,
)
from services.risk.pnl_explain import PnLExplainService
from services.risk.var import VaREngine

router = APIRouter()
ps = PricingService()


@router.post("/scenario", response_model=ScenarioResponse)
def run_scenario(req: ScenarioRequest):
    """Run a custom scenario with arbitrary shocks."""
    try:
        instruments = build_instruments_from_request(req.instruments)
        underlying = (getattr(instruments[0], "underlying", None) if instruments else None) or (list(req.market_data.underlyings.keys())[0] if req.market_data.underlyings else None)
        market_env = build_market_env_from_request(req.market_data, underlying=underlying)

        scenario = Scenario(
            name=req.scenario_name,
            shocks=[
                ShockSpec(
                    risk_factor=s.risk_factor,
                    shock_type=s.shock_type,
                    value=s.value,
                    underlying=s.underlying,
                )
                for s in req.shocks
            ],
        )

        engine = ScenarioEngine(
            pricing_service=ps,
            model_type=req.model,
            engine_type=req.engine,
        )
        result = engine.run_scenario(instruments, market_env, scenario)

        return ScenarioResponse(
            scenario_name=result.scenario_name,
            total_base=round(result.total_base, 6),
            total_shocked=round(result.total_shocked, 6),
            total_impact=round(result.total_impact, 6),
            per_trade={k: round(v, 6) for k, v in result.pnl_impact.items()},
            elapsed_ms=round(result.elapsed_seconds * 1000, 2),
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/stress-test", response_model=StressTestResponse)
def run_stress_test(req: StressTestRequest):
    """Run predefined or named stress scenarios."""
    try:
        instruments = build_instruments_from_request(req.instruments)
        underlying = (getattr(instruments[0], "underlying", None) if instruments else None) or (list(req.market_data.underlyings.keys())[0] if req.market_data.underlyings else None)
        market_env = build_market_env_from_request(req.market_data, underlying=underlying)

        engine = ScenarioEngine(
            pricing_service=ps,
            model_type=req.model,
            engine_type=req.engine,
        )

        # Resolve scenario names
        if req.scenarios:
            scenarios = []
            for name in req.scenarios:
                if name in PREDEFINED_SCENARIOS:
                    scenarios.append(PREDEFINED_SCENARIOS[name])
                else:
                    raise ValueError(
                        f"Unknown scenario '{name}'. "
                        f"Available: {list(PREDEFINED_SCENARIOS.keys())}"
                    )
        else:
            scenarios = list(PREDEFINED_SCENARIOS.values())

        stress_result = engine.run_stress_test(instruments, market_env, scenarios)

        results = []
        for sr in stress_result.scenario_results:
            results.append(ScenarioResponse(
                scenario_name=sr.scenario_name,
                total_base=round(sr.total_base, 6),
                total_shocked=round(sr.total_shocked, 6),
                total_impact=round(sr.total_impact, 6),
                per_trade={k: round(v, 6) for k, v in sr.pnl_impact.items()},
                elapsed_ms=round(sr.elapsed_seconds * 1000, 2),
            ))

        worst = stress_result.worst_scenario
        best = stress_result.best_scenario

        return StressTestResponse(
            results=results,
            worst_scenario=worst.scenario_name if worst else None,
            best_scenario=best.scenario_name if best else None,
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/pnl-explain", response_model=PnLExplainResponse)
def pnl_explain(req: PnLExplainRequest):
    """P&L explain between two market environments."""
    try:
        instruments = build_instruments_from_request(req.instruments)
        underlying = (getattr(instruments[0], "underlying", None) if instruments else None) or (list(req.market_data.underlyings.keys())[0] if req.market_data.underlyings else None)

        base_env = build_market_env_from_request(req.base_market, underlying=underlying)
        current_env = build_market_env_from_request(req.current_market, underlying=underlying)

        svc = PnLExplainService(
            pricing_service=ps,
            model_type=req.model,
            engine_type=req.engine,
        )
        result = svc.explain_portfolio(instruments, base_env, current_env)

        per_trade = [e.to_dict() for e in result.trade_explains]

        return PnLExplainResponse(
            total_actual_pnl=round(result.total_actual, 6),
            total_explained=round(result.total_explained, 6),
            total_unexplained=round(result.total_unexplained, 6),
            delta_pnl=round(result.total_delta_pnl, 6),
            gamma_pnl=round(result.total_gamma_pnl, 6),
            vega_pnl=round(result.total_vega_pnl, 6),
            theta_pnl=round(result.total_theta_pnl, 6),
            rho_pnl=round(result.total_rho_pnl, 6),
            per_trade=per_trade,
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/var", response_model=VaRResponse)
def compute_var(req: VaRRequest):
    """Compute Value-at-Risk (parametric, historical, or Monte Carlo)."""
    try:
        instruments = build_instruments_from_request(req.instruments)
        underlying = (getattr(instruments[0], "underlying", None) if instruments else None) or (list(req.market_data.underlyings.keys())[0] if req.market_data.underlyings else None)
        market_env = build_market_env_from_request(req.market_data, underlying=underlying)

        var_engine = VaREngine(
            pricing_service=ps,
            model_type=req.model,
            engine_type=req.engine,
        )

        if req.method == "parametric":
            result = var_engine.parametric_var(
                instruments=instruments,
                market_env=market_env,
                confidence=req.confidence,
                horizon_days=req.horizon_days,
                annual_vol=req.annual_vol,
            )

        elif req.method == "historical":
            if not req.historical_returns:
                raise ValueError("historical_returns required for historical VaR")
            result = var_engine.historical_var(
                instruments=instruments,
                market_env=market_env,
                historical_returns=np.array(req.historical_returns),
                confidence=req.confidence,
                horizon_days=req.horizon_days,
            )

        elif req.method == "monte_carlo":
            result = var_engine.monte_carlo_var(
                instruments=instruments,
                market_env=market_env,
                confidence=req.confidence,
                horizon_days=req.horizon_days,
                num_simulations=req.num_simulations,
                annual_vol=req.annual_vol,
            )

        else:
            raise ValueError(f"Unknown VaR method: '{req.method}'")

        return VaRResponse(
            var=round(result.var, 6),
            cvar=round(result.cvar, 6),
            confidence=result.confidence,
            horizon_days=result.horizon_days,
            method=result.method,
            portfolio_value=round(result.portfolio_value, 6),
            trade_contributions=(
                {k: round(v, 6) for k, v in result.trade_contributions.items()}
                if result.trade_contributions else None
            ),
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
