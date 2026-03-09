"""
Jobs endpoints — async job submission, polling, and retrieval.

For long-running tasks (MC VaR, calibration, large batch pricing),
submit a job and poll for results instead of blocking.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.jobs.job_manager import job_manager, JobStatus

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class JobSubmitRequest(BaseModel):
    """
    Generic job submission.

    job_type determines which function to run.
    params are passed to the function.
    """
    job_type: str = Field(..., description="Job type: 'batch_pricing', 'monte_carlo_var', 'calibration', 'stress_test'")
    params: Dict[str, Any] = Field(..., description="Job parameters")


class JobStatusResponse(BaseModel):
    job_id: str
    job_type: str
    status: str
    submitted_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    progress: float = 0.0
    error: Optional[str] = None
    has_result: bool = False


# ---------------------------------------------------------------------------
# Job executors (map job_type to actual function)
# ---------------------------------------------------------------------------

def _execute_batch_pricing(params: Dict) -> Dict:
    """Batch pricing job."""
    from api.v1.schemas import MarketDataRequest, UnderlyingData, InstrumentRequest
    from api.v1.helpers import build_instrument_from_request, build_market_env_from_request
    from services.pricers.pricing_service import PricingService

    ps = PricingService()
    results = []

    market_data = MarketDataRequest(
        pricing_date=params["market_data"]["pricing_date"],
        underlyings={
            k: UnderlyingData(**v)
            for k, v in params["market_data"]["underlyings"].items()
        },
        rate=params["market_data"].get("rate", 0.05),
    )

    for inst_data in params.get("instruments", []):
        inst_req = InstrumentRequest(type=inst_data["type"], params=inst_data["params"])
        try:
            instrument = build_instrument_from_request(inst_req)
            underlying = getattr(instrument, "underlying", "")
            market_env = build_market_env_from_request(market_data, underlying=underlying)

            result = ps.price(
                instrument, market_env,
                model_type=params.get("model", "black_scholes"),
                engine_type=params.get("engine", "analytic"),
            )
            results.append({
                "trade_id": str(result.trade_id),
                "npv": result.npv,
            })
        except Exception as e:
            results.append({
                "trade_id": inst_data.get("params", {}).get("trade_id", "unknown"),
                "error": str(e),
            })

    return {"results": results, "count": len(results)}


def _execute_monte_carlo_var(params: Dict) -> Dict:
    """Monte Carlo VaR job."""
    import numpy as np
    from api.v1.schemas import MarketDataRequest, UnderlyingData, InstrumentRequest
    from api.v1.helpers import build_instrument_from_request, build_market_env_from_request
    from services.risk.var import VaREngine

    instruments = []
    market_data = MarketDataRequest(
        pricing_date=params["market_data"]["pricing_date"],
        underlyings={
            k: UnderlyingData(**v)
            for k, v in params["market_data"]["underlyings"].items()
        },
        rate=params["market_data"].get("rate", 0.05),
    )

    for inst_data in params.get("instruments", []):
        inst_req = InstrumentRequest(type=inst_data["type"], params=inst_data["params"])
        instruments.append(build_instrument_from_request(inst_req))

    underlying = getattr(instruments[0], "underlying", "") if instruments else ""
    market_env = build_market_env_from_request(market_data, underlying=underlying)

    var_engine = VaREngine()
    result = var_engine.monte_carlo_var(
        instruments=instruments,
        market_env=market_env,
        confidence=params.get("confidence", 0.99),
        horizon_days=params.get("horizon_days", 1),
        num_simulations=params.get("num_simulations", 10000),
        annual_vol=params.get("annual_vol", 0.20),
    )

    return result.to_dict()


def _execute_stress_test(params: Dict) -> Dict:
    """Full stress test job."""
    from api.v1.schemas import MarketDataRequest, UnderlyingData, InstrumentRequest
    from api.v1.helpers import build_instrument_from_request, build_market_env_from_request
    from services.risk.scenario_engine import ScenarioEngine, PREDEFINED_SCENARIOS

    instruments = []
    market_data = MarketDataRequest(
        pricing_date=params["market_data"]["pricing_date"],
        underlyings={
            k: UnderlyingData(**v)
            for k, v in params["market_data"]["underlyings"].items()
        },
        rate=params["market_data"].get("rate", 0.05),
    )

    for inst_data in params.get("instruments", []):
        inst_req = InstrumentRequest(type=inst_data["type"], params=inst_data["params"])
        instruments.append(build_instrument_from_request(inst_req))

    underlying = getattr(instruments[0], "underlying", "") if instruments else ""
    market_env = build_market_env_from_request(market_data, underlying=underlying)

    engine = ScenarioEngine()
    result = engine.run_stress_test(instruments, market_env)

    return {
        "scenarios": [r.summary() for r in result.scenario_results],
        "worst": result.worst_scenario.scenario_name if result.worst_scenario else None,
        "best": result.best_scenario.scenario_name if result.best_scenario else None,
    }


# Job type dispatcher
JOB_EXECUTORS = {
    "batch_pricing": _execute_batch_pricing,
    "monte_carlo_var": _execute_monte_carlo_var,
    "stress_test": _execute_stress_test,
}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/submit", response_model=JobStatusResponse)
def submit_job(req: JobSubmitRequest):
    """Submit a long-running job. Returns immediately with job_id."""
    executor = JOB_EXECUTORS.get(req.job_type)
    if executor is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown job type: '{req.job_type}'. Available: {list(JOB_EXECUTORS.keys())}",
        )

    job_id = job_manager.submit(
        job_type=req.job_type,
        func=executor,
        kwargs={"params": req.params},
    )

    status = job_manager.get_status(job_id)
    return JobStatusResponse(**status)


@router.get("/status/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str):
    """Poll job status."""
    status = job_manager.get_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return JobStatusResponse(**status)


@router.get("/result/{job_id}")
def get_job_result(job_id: str):
    """Get job result. Returns 202 if still running."""
    status = job_manager.get_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    if status["status"] == "running" or status["status"] == "pending":
        return {"job_id": job_id, "status": status["status"], "message": "Job still in progress"}

    if status["status"] == "failed":
        raise HTTPException(status_code=500, detail=f"Job failed: {status.get('error')}")

    result = job_manager.get_result(job_id)
    return {"job_id": job_id, "status": "completed", "result": result}


@router.get("/list")
def list_jobs(
    status: Optional[str] = None,
    job_type: Optional[str] = None,
):
    """List all jobs, optionally filtered by status or type."""
    filter_status = JobStatus(status) if status else None
    return job_manager.list_jobs(status=filter_status, job_type=job_type)


@router.post("/cancel/{job_id}")
def cancel_job(job_id: str):
    """Cancel a pending job."""
    if job_manager.cancel(job_id):
        return {"job_id": job_id, "status": "cancelled"}
    raise HTTPException(status_code=400, detail="Cannot cancel: job not found or already running")