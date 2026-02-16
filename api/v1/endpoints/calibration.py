"""
Calibration endpoints — model calibration and implied vol.
"""

from __future__ import annotations

import time
from datetime import date

from fastapi import APIRouter, HTTPException

from api.v1.schemas import (
    ModelCalibrationRequest,
    ModelCalibrationResponse,
    ImpliedVolRequest,
    ImpliedVolResponse,
)
from api.v1.helpers import build_market_env_from_request
from services.calibration.implied_vol import (
    ImpliedVolSolver,
    implied_vol_bisection,
    implied_vol_newton,
)

router = APIRouter()


@router.post("/model", response_model=ModelCalibrationResponse)
def calibrate_model(req: ModelCalibrationRequest):
    """
    Calibrate any model to market data.

    Currently supports: heston, sabr.
    """
    t0 = time.perf_counter()

    try:
        if req.model_type == "heston":
            return _calibrate_heston(req, t0)
        elif req.model_type == "sabr":
            return _calibrate_sabr(req, t0)
        else:
            raise ValueError(
                f"Unsupported model for calibration: '{req.model_type}'. "
                f"Supported: heston, sabr"
            )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


def _calibrate_heston(req: ModelCalibrationRequest, t0: float) -> ModelCalibrationResponse:
    """Calibrate Heston model."""
    from services.calibration.heston_calibration import HestonCalibrationService

    market_env = build_market_env_from_request(req.market_data, underlying=req.underlying)

    cal_data = req.calibration_data
    strikes = cal_data.get("strikes", [])
    expiries = [date.fromisoformat(d) for d in cal_data.get("expiries", [])]

    initial = req.initial_params or {}
    svc = HestonCalibrationService(
        initial_v0=initial.get("v0", 0.04),
        initial_kappa=initial.get("kappa", 1.5),
        initial_theta=initial.get("theta", 0.04),
        initial_sigma=initial.get("sigma", 0.5),
        initial_rho=initial.get("rho", -0.7),
        optimizer_name=req.optimizer,
    )

    result = svc.calibrate_to_surface(
        market_env=market_env,
        underlying=req.underlying,
        strikes=strikes,
        expiries=expiries,
    )

    elapsed_ms = (time.perf_counter() - t0) * 1000

    return ModelCalibrationResponse(
        model_type="heston",
        parameters=result.parameters,
        fit_rmse=round(result.total_rmse, 8),
        fit_report=result.fit_report,
        elapsed_ms=round(elapsed_ms, 2),
    )


def _calibrate_sabr(req: ModelCalibrationRequest, t0: float) -> ModelCalibrationResponse:
    """Calibrate SABR model."""
    from market.volatility.vol_surface import calibrate_sabr

    cal_data = req.calibration_data
    strikes = cal_data.get("strikes", [])
    market_vols = cal_data.get("market_vols", [])
    forward = cal_data.get("forward", 100.0)
    expiry_years = cal_data.get("expiry_years", 1.0)
    beta = cal_data.get("beta", 0.5)

    result = calibrate_sabr(
        forward=forward,
        expiry_years=expiry_years,
        strikes=strikes,
        market_vols=market_vols,
        beta=beta,
    )

    elapsed_ms = (time.perf_counter() - t0) * 1000

    return ModelCalibrationResponse(
        model_type="sabr",
        parameters={
            "alpha": round(result.alpha, 8),
            "beta": result.beta,
            "rho": round(result.rho, 8),
            "nu": round(result.nu, 8),
        },
        fit_rmse=0.0,
        elapsed_ms=round(elapsed_ms, 2),
    )


@router.post("/implied-vol", response_model=ImpliedVolResponse)
def compute_implied_vol(req: ImpliedVolRequest):
    """Compute implied vol from market price."""
    try:
        solver = ImpliedVolSolver(method=req.method)
        result = solver.solve(
            market_price=req.market_price,
            spot=req.spot,
            strike=req.strike,
            T=req.T,
            rate=req.rate,
            div_yield=req.div_yield,
            is_call=req.is_call,
        )

        return ImpliedVolResponse(
            implied_vol=round(result.implied_vol, 8),
            converged=result.converged,
            method=result.method,
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))