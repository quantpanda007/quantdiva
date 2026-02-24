"""
Excel export endpoint.

POST /api/v1/export/pricing — Generate Excel workbook for a pricing result.
Returns the .xlsx file as a downloadable attachment.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import numpy as np
import QuantLib as ql
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.v1.schemas import PricingRequest
from api.v1.helpers import build_instrument_from_request, build_market_env_from_request
from services.pricers.pricing_service import PricingService
from services.greeks.bump_reprice import BumpAndRepriceGreeks
from services.export.excel_export import generate_pricing_excel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/export", tags=["export"])
ps = PricingService()


class ExportPricingRequest(PricingRequest):
    """Extends PricingRequest with export options."""
    include_mc_data: bool = True


@router.post("/pricing")
def export_pricing_to_excel(req: ExportPricingRequest):
    """Price the instrument and export full results to Excel."""
    try:
        instrument = build_instrument_from_request(req.instrument)

        # Resolve underlying
        und = getattr(instrument, "underlying", None)
        if not und or (isinstance(und, str) and und.strip() == ""):
            if hasattr(instrument, "ccy_pair"):
                und = getattr(instrument, "ccy_pair", None)
            if not und and req.market_data.underlyings:
                und = list(req.market_data.underlyings.keys())[0]
        und = und or None

        market_env = build_market_env_from_request(req.market_data, underlying=und)

        # Price
        t0 = time.perf_counter()
        price_result = ps.price(
            instrument=instrument,
            market_env=market_env,
            model_type=req.model,
            engine_type=req.engine,
            engine_params=req.engine_params,
        )
        elapsed = round((time.perf_counter() - t0) * 1000, 1)

        result = {
            "npv": price_result.npv,
            "trade_id": str(price_result.trade_id),
            "model": req.model,
            "engine": req.engine,
            "elapsed_ms": elapsed,
        }

        # Greeks
        greeks = None
        try:
            greeks_service = BumpAndRepriceGreeks(pricing_service=ps)
            greeks_result = greeks_service.compute(
                instrument, market_env, req.model, req.engine,
                req.engine_params or {},
                measures=["delta", "gamma", "vega", "theta", "rho",
                          "dv01", "duration", "convexity"],
            )
            greeks = greeks_result.greeks
        except Exception as e:
            logger.debug(f"Greeks failed: {e}")

        # Build raw market data dict for the Excel sheet
        market_data_dict = _market_req_to_dict(req.market_data, und)

        # MC data
        mc_data = None
        eng = str(req.engine or "").lower()
        if req.include_mc_data and ("monte_carlo" in eng or "mc" in eng):
            mc_data = _run_mc_simulation(
                instrument, market_env, market_data_dict,
                req.engine_params or {},
            )

        # Build instrument dict for Excel
        inst_dict = {
            "type": req.instrument.type,
            "params": req.instrument.params or {},
        }

        xlsx_bytes = generate_pricing_excel(
            instrument=inst_dict,
            market_data=market_data_dict,
            model=req.model,
            engine=req.engine,
            result=result,
            greeks=greeks,
            engine_params=req.engine_params,
            mc_data=mc_data,
        )

        trade_id = str(price_result.trade_id).replace(" ", "_")
        filename = f"QuantPricer_{trade_id}_{req.engine}.xlsx"

        return StreamingResponse(
            iter([xlsx_bytes]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    except Exception as e:
        logger.error(f"Export failed: {e}", exc_info=True)
        raise HTTPException(500, f"Export failed: {str(e)}")


def _market_req_to_dict(md, underlying):
    """Convert MarketDataRequest to a flat dict for the Excel export."""
    d = {
        "pricing_date": md.pricing_date,
        "spot_prices": {},
        "flat_vols": {},
        "dividend_yields": {},
        "rate_curve": [],
    }
    if md.underlyings:
        for sym, data in md.underlyings.items():
    # Convert Pydantic model to dict safely
            if hasattr(data, "model_dump"):
                data_dict = data.model_dump()
            elif hasattr(data, "dict"):
                data_dict = data.dict()
            else:
                data_dict = dict(data)

            d["spot_prices"][sym] = data_dict.get("spot", 0)

            if "vol" in data_dict:
                d["flat_vols"][sym] = data_dict["vol"]

            if "div_yield" in data_dict:
                d["dividend_yields"][sym] = data_dict["div_yield"]


    # Handle optional rate curve
    if hasattr(md, "rate_curve") and md.rate_curve:
        d["rate_curve"] = [
            {"tenor": pt.get("tenor", ""), "rate": pt.get("rate", 0)}
            for pt in md.rate_curve
        ]
    elif hasattr(md, "rate"):
        # Fallback to flat rate if provided
        d["rate_curve"] = [{"tenor": "flat", "rate": md.rate}]
    

    return d


def _run_mc_simulation(instrument, market_env, market_data_dict, engine_params):
    """Run Monte Carlo and capture paths + randoms for Excel."""
    try:
        num_paths = int(engine_params.get("num_paths", 10000))
        num_steps = int(engine_params.get("num_steps", 252))
        export_paths = min(num_paths, 1000)

        spots = market_data_dict.get("spot_prices", {})
        spot = list(spots.values())[0] if spots else 100.0
        vols = market_data_dict.get("flat_vols", {})
        vol = list(vols.values())[0] if vols else 0.25
        divs = market_data_dict.get("dividend_yields", {})
        div_yield = list(divs.values())[0] if divs else 0.0

        rate = 0.045
        rate_points = market_data_dict.get("rate_curve", [])
        if rate_points:
            rate = rate_points[0].get("rate", 0.045)

        strike = getattr(instrument, "strike", spot)
        ot = getattr(instrument, "option_type", "call")
        if hasattr(ot, "value"):
            ot = ot.value
        opt_type = str(ot).lower()

        T = 1.0
        eval_date = market_env.pricing_date.to_ql()
        if hasattr(instrument, "expiry") and instrument.expiry:
            from datetime import date as dt_date
            expiry = instrument.expiry
            if isinstance(expiry, dt_date):
                exp_ql = ql.Date(expiry.day, expiry.month, expiry.year)
                T = ql.Actual365Fixed().yearFraction(eval_date, exp_ql)
        if T <= 0:
            T = 1.0

        dt = T / num_steps
        np.random.seed(42)
        Z = np.random.standard_normal((export_paths, num_steps))

        drift = (rate - div_yield - 0.5 * vol * vol) * dt
        diffusion = vol * np.sqrt(dt)

        paths = np.zeros((export_paths, num_steps + 1))
        paths[:, 0] = spot
        for t in range(num_steps):
            paths[:, t + 1] = paths[:, t] * np.exp(drift + diffusion * Z[:, t])

        S_T = paths[:, -1]
        if opt_type == "call":
            payoffs = np.maximum(S_T - strike, 0)
        else:
            payoffs = np.maximum(strike - S_T, 0)

        discount = np.exp(-rate * T)
        npv_mc = discount * np.mean(payoffs)

        stats = {
            "mean_payoff": float(np.mean(payoffs)),
            "std_payoff": float(np.std(payoffs)),
            "npv": float(npv_mc),
            "std_error": float(np.std(payoffs) / np.sqrt(export_paths)),
            "ci_lower": float(npv_mc - 1.96 * np.std(payoffs) / np.sqrt(export_paths) * discount),
            "ci_upper": float(npv_mc + 1.96 * np.std(payoffs) / np.sqrt(export_paths) * discount),
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
        logger.warning(f"MC export failed: {e}")
        return None