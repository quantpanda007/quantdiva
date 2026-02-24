"""
Excel export endpoint.

POST /api/v1/export/pricing — Generate Excel workbook for a pricing result.
Returns the .xlsx file as a downloadable attachment.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np
import QuantLib as ql
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.export.excel_export import generate_pricing_excel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/export", tags=["export"])


class ExportPricingRequest(BaseModel):
    instrument: Dict[str, Any]
    market_data: Dict[str, Any]
    model: str = "black_scholes"
    engine: str = "analytic"
    engine_params: Optional[Dict[str, Any]] = None
    include_mc_data: bool = True


@router.post("/pricing")
def export_pricing_to_excel(req: ExportPricingRequest):
    """Price the instrument and export full results to Excel.

    For Monte Carlo engines, includes simulation paths, payoffs,
    and random numbers in additional sheets.
    """
    from api.v1.helpers import build_instrument, build_market_env
    from services.pricing.pricing_service import PricingService
    from services.greeks.bump_reprice import BumpRepriceGreeks

    try:
        # Build instrument and market environment
        instrument = build_instrument(req.instrument)
        market_env = build_market_env(req.market_data)
        model_type = req.model
        engine_type = req.engine
        engine_params = req.engine_params or {}

        # Price
        pricing_service = PricingService()
        import time
        t0 = time.time()
        npv = pricing_service.price(
            instrument, market_env, model_type, engine_type, engine_params
        )
        elapsed = round((time.time() - t0) * 1000, 1)

        result = {
            "npv": npv,
            "trade_id": str(instrument.trade_id()),
            "model": model_type,
            "engine": engine_type,
            "elapsed_ms": elapsed,
        }

        # Compute Greeks
        greeks = None
        try:
            greeks_service = BumpRepriceGreeks(pricing_service)
            greeks_result = greeks_service.compute(
                instrument, market_env, model_type, engine_type, engine_params,
                measures=["delta", "gamma", "vega", "theta", "rho",
                          "dv01", "duration", "convexity"],
            )
            greeks = greeks_result.greeks
        except Exception as e:
            logger.debug(f"Greeks computation failed: {e}")

        # MC simulation data (if Monte Carlo engine)
        mc_data = None
        eng = str(engine_type).lower()
        if req.include_mc_data and ("monte_carlo" in eng or "mc" in eng):
            mc_data = _run_mc_simulation(
                instrument, market_env, req.market_data, engine_params,
            )

        # Generate Excel
        xlsx_bytes = generate_pricing_excel(
            instrument=req.instrument,
            market_data=req.market_data,
            model=model_type,
            engine=engine_type,
            result=result,
            greeks=greeks,
            engine_params=engine_params,
            mc_data=mc_data,
        )

        # Return as downloadable file
        trade_id = str(instrument.trade_id()).replace(" ", "_")
        filename = f"QuantPricer_{trade_id}_{engine_type}.xlsx"

        return StreamingResponse(
            iter([xlsx_bytes]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    except Exception as e:
        logger.error(f"Export failed: {e}")
        raise HTTPException(500, f"Export failed: {str(e)}")


def _run_mc_simulation(instrument, market_env, market_data_dict, engine_params):
    """Run Monte Carlo simulation and capture paths + random numbers.

    Uses QuantLib's GBM process to generate paths explicitly,
    compute payoffs, and return all data for the Excel export.
    """
    try:
        num_paths = int(engine_params.get("num_paths", 10000))
        num_steps = int(engine_params.get("num_steps", 252))

        # Cap for Excel export (too many paths = huge file)
        export_paths = min(num_paths, 1000)

        # Get market params
        spots = market_data_dict.get("spot_prices", {})
        spot = list(spots.values())[0] if spots else 100.0
        vols = market_data_dict.get("flat_vols", {})
        vol = list(vols.values())[0] if vols else 0.25
        divs = market_data_dict.get("dividend_yields", {})
        div_yield = list(divs.values())[0] if divs else 0.0

        # Get rate
        rate = 0.045
        rate_points = market_data_dict.get("rate_curve", [])
        if isinstance(rate_points, list) and rate_points:
            rate = rate_points[0].get("rate", 0.045)

        # Get instrument params
        params = {}
        if hasattr(instrument, "strike"):
            params["strike"] = instrument.strike
        if hasattr(instrument, "option_type"):
            ot = instrument.option_type
            if hasattr(ot, "value"):
                ot = ot.value
            params["option_type"] = str(ot).lower()

        # Time to maturity
        T = 1.0
        eval_date = market_env.pricing_date.to_ql()
        if hasattr(instrument, "expiry") and instrument.expiry:
            from datetime import date as dt_date
            expiry = instrument.expiry
            if isinstance(expiry, dt_date):
                exp_ql = ql.Date(expiry.day, expiry.month, expiry.year)
                T = ql.Actual365Fixed().yearFraction(eval_date, exp_ql)
            elif hasattr(expiry, "to_ql"):
                T = ql.Actual365Fixed().yearFraction(eval_date, expiry.to_ql())

        if T <= 0:
            T = 1.0

        dt = T / num_steps

        # Generate random numbers
        np.random.seed(42)  # Reproducible for export
        Z = np.random.standard_normal((export_paths, num_steps))

        # Generate GBM paths: S(t+dt) = S(t) * exp((r - d - 0.5*vol^2)*dt + vol*sqrt(dt)*Z)
        drift = (rate - div_yield - 0.5 * vol * vol) * dt
        diffusion = vol * np.sqrt(dt)

        paths = np.zeros((export_paths, num_steps + 1))
        paths[:, 0] = spot

        for t in range(num_steps):
            paths[:, t + 1] = paths[:, t] * np.exp(drift + diffusion * Z[:, t])

        # Compute payoffs
        S_T = paths[:, -1]
        strike = params.get("strike", spot)
        opt_type = params.get("option_type", "call")

        if opt_type == "call":
            payoffs = np.maximum(S_T - strike, 0)
        else:
            payoffs = np.maximum(strike - S_T, 0)

        # Discount
        discount = np.exp(-rate * T)
        npv_mc = discount * np.mean(payoffs)

        # Statistics
        stats = {
            "mean_payoff": float(np.mean(payoffs)),
            "std_payoff": float(np.std(payoffs)),
            "npv": float(npv_mc),
            "std_error": float(np.std(payoffs) / np.sqrt(export_paths)),
            "ci_lower": float(npv_mc - 1.96 * np.std(payoffs) / np.sqrt(export_paths) * discount),
            "ci_upper": float(npv_mc + 1.96 * np.std(payoffs) / np.sqrt(export_paths) * discount),
            "spot": spot,
            "strike": strike,
            "vol": vol,
            "rate": rate,
            "T": T,
        }

        return {
            "paths": paths,
            "payoffs": payoffs,
            "random_numbers": Z,
            "num_paths": export_paths,
            "num_steps": num_steps,
            "statistics": stats,
        }

    except Exception as e:
        logger.warning(f"MC simulation export failed: {e}")
        return None
