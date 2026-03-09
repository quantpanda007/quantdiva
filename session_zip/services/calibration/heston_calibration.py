"""
Heston Model Calibration Service.

Calibrates the Heston stochastic volatility model to market option prices
or implied volatilities using QuantLib's optimization framework.

Workflow:
    1. Build calibration helpers from market vol surface (strikes × expiries)
    2. Set up initial parameter guess
    3. Run Levenberg-Marquardt (or other) optimizer
    4. Report diagnostics: parameter values, fit quality, Feller condition

Supports:
- Calibration to implied vol surface (most common)
- Calibration to option prices directly
- Multiple optimizers: Levenberg-Marquardt, Simplex, Differential Evolution
- Parameter bounds and constraints
- Fit quality report per strike/expiry

Usage:
    from services.calibration.heston_calibration import HestonCalibrationService

    calib = HestonCalibrationService()
    result = calib.calibrate_to_surface(
        market_env=env,
        underlying="SPX",
        strikes=[90, 95, 100, 105, 110],
        expiries=[date(2025, 7, 15), date(2026, 1, 15), date(2026, 7, 15)],
    )
    print(result.parameters)
    print(result.fit_report)
    heston_model = result.model  # calibrated HestonModel ready for pricing
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import QuantLib as ql

from core.enums.definitions import ModelType
from core.exceptions.errors import CalibrationError, ModelError
from core.interfaces.base import MarketEnvironment
from models.equity.black_scholes import HestonModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Calibration result
# ---------------------------------------------------------------------------

@dataclass
class HestonCalibrationResult:
    """
    Output of Heston calibration.

    Attributes:
        model:              Calibrated HestonModel instance
        parameters:         Dict of calibrated parameters
        initial_parameters: Dict of starting parameters
        fit_report:         Per-helper fit quality
        total_rmse:         Root mean square error across all helpers
        total_mae:          Mean absolute error
        max_error:          Maximum absolute error
        feller_satisfied:   Whether 2κθ > σ² holds
        optimizer_used:     Name of optimizer
        iterations:         Number of optimizer iterations
        elapsed_seconds:    Wall clock time
    """

    model: HestonModel = None
    parameters: Dict[str, float] = field(default_factory=dict)
    initial_parameters: Dict[str, float] = field(default_factory=dict)
    fit_report: List[Dict[str, Any]] = field(default_factory=list)
    total_rmse: float = 0.0
    total_mae: float = 0.0
    max_error: float = 0.0
    feller_satisfied: bool = True
    optimizer_used: str = ""
    iterations: int = 0
    elapsed_seconds: float = 0.0

    def summary(self) -> Dict[str, Any]:
        return {
            "parameters": self.parameters,
            "feller_satisfied": self.feller_satisfied,
            "feller_ratio": (
                2 * self.parameters.get("kappa", 0) * self.parameters.get("theta", 0)
                / max(self.parameters.get("sigma", 0.01) ** 2, 1e-10)
            ),
            "total_rmse": round(self.total_rmse, 6),
            "total_mae": round(self.total_mae, 6),
            "max_error": round(self.max_error, 6),
            "num_helpers": len(self.fit_report),
            "optimizer": self.optimizer_used,
            "elapsed_seconds": round(self.elapsed_seconds, 4),
        }


# ---------------------------------------------------------------------------
# Optimizer presets
# ---------------------------------------------------------------------------

def _create_optimizer(name: str) -> Tuple[ql.OptimizationMethod, ql.EndCriteria]:
    """Create optimizer and end criteria by name."""
    name = name.lower()

    if name == "levenberg_marquardt" or name == "lm":
        optimizer = ql.LevenbergMarquardt(1e-8, 1e-8, 1e-8)
        end_criteria = ql.EndCriteria(1000, 500, 1e-8, 1e-8, 1e-8)

    elif name == "simplex":
        optimizer = ql.Simplex(0.01)
        end_criteria = ql.EndCriteria(10000, 5000, 1e-8, 1e-8, 1e-8)

    elif name == "differential_evolution" or name == "de":
        # QuantLib Differential Evolution
        conf = ql.DifferentialEvolution.Configuration()
        optimizer = ql.DifferentialEvolution(conf)
        end_criteria = ql.EndCriteria(5000, 2000, 1e-8, 1e-8, 1e-8)

    else:
        raise CalibrationError(
            f"Unknown optimizer: '{name}'. "
            f"Available: levenberg_marquardt, simplex, differential_evolution"
        )

    return optimizer, end_criteria


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------

def build_heston_helpers_from_surface(
    market_env: MarketEnvironment,
    underlying: str,
    strikes: List[float],
    expiries: List[date],
    option_type: str = "call",
) -> Tuple[List[ql.HestonModelHelper], List[Dict]]:
    """
    Build QuantLib HestonModelHelper instances from market vol surface.

    For each (strike, expiry) pair:
    1. Extract implied vol from market_env vol surface
    2. Create HestonModelHelper

    Args:
        market_env:  Market environment with vol surface
        underlying:  Underlying asset code
        strikes:     List of strike prices
        expiries:    List of expiry dates
        option_type: "call" or "put"

    Returns:
        (helpers, helper_info) where helper_info contains market data per helper
    """
    pricing_date = market_env.pricing_date.value
    ql_pricing = market_env.pricing_date.to_ql()

    spot = market_env.spot_prices.get(underlying)
    if spot is None:
        raise CalibrationError(f"No spot price for '{underlying}'")

    vol_surface = market_env.vol_surfaces.get(underlying)
    if vol_surface is None:
        raise CalibrationError(f"No vol surface for '{underlying}'")

    # Risk-free rate handle
    risk_free = market_env.get_discount_curve(
        underlying if underlying in market_env.discount_curves else "USD"
    )

    # Dividend handle
    div_key = f"{underlying}_div"
    if div_key in market_env.dividend_curves:
        dividend = market_env.dividend_curves[div_key]
    else:
        dividend = ql.YieldTermStructureHandle(
            ql.FlatForward(ql_pricing, 0.0, ql.Actual365Fixed())
        )

    helpers = []
    helper_info = []
    dc = ql.Actual365Fixed()

    for expiry in expiries:
        ql_expiry = ql.Date(expiry.day, expiry.month, expiry.year)
        T = dc.yearFraction(ql_pricing, ql_expiry)
        if T <= 0:
            continue

        period = ql.Period(int(round(T * 365)), ql.Days)

        for strike in strikes:
            try:
                market_vol = vol_surface.blackVol(T, strike)

                helper = ql.HestonModelHelper(
                    period,
                    ql.TARGET(),
                    ql.QuoteHandle(ql.SimpleQuote(spot)),
                    strike,
                    ql.QuoteHandle(ql.SimpleQuote(market_vol)),
                    risk_free,
                    dividend,
                )

                helpers.append(helper)
                helper_info.append({
                    "expiry": expiry.isoformat(),
                    "T": round(T, 4),
                    "strike": strike,
                    "moneyness": round(strike / spot, 4),
                    "market_vol": round(market_vol, 6),
                })

            except Exception as e:
                logger.warning(
                    f"Skipping helper at K={strike}, T={T:.3f}: {e}"
                )

    if not helpers:
        raise CalibrationError(
            "No valid calibration helpers could be built. "
            "Check vol surface, strikes, and expiries."
        )

    logger.info(f"Built {len(helpers)} Heston calibration helpers")
    return helpers, helper_info


def build_heston_helpers_from_prices(
    market_env: MarketEnvironment,
    underlying: str,
    market_data: List[Dict[str, Any]],
) -> Tuple[List[ql.HestonModelHelper], List[Dict]]:
    """
    Build HestonModelHelper from explicit option prices.

    market_data is a list of dicts, each with:
    - "expiry": date
    - "strike": float
    - "price": float (market option price)
    - "option_type": "call" or "put" (optional, default "call")

    This uses QuantLib's price-based helper constructor.
    """
    pricing_date = market_env.pricing_date.value
    ql_pricing = market_env.pricing_date.to_ql()

    spot = market_env.spot_prices.get(underlying)
    if spot is None:
        raise CalibrationError(f"No spot price for '{underlying}'")

    risk_free = market_env.get_discount_curve(
        underlying if underlying in market_env.discount_curves else "USD"
    )

    div_key = f"{underlying}_div"
    if div_key in market_env.dividend_curves:
        dividend = market_env.dividend_curves[div_key]
    else:
        dividend = ql.YieldTermStructureHandle(
            ql.FlatForward(ql_pricing, 0.0, ql.Actual365Fixed())
        )

    helpers = []
    helper_info = []
    dc = ql.Actual365Fixed()

    for entry in market_data:
        expiry = entry["expiry"]
        strike = entry["strike"]
        price = entry["price"]

        ql_expiry = ql.Date(expiry.day, expiry.month, expiry.year)
        T = dc.yearFraction(ql_pricing, ql_expiry)
        if T <= 0:
            continue

        period = ql.Period(int(round(T * 365)), ql.Days)

        try:
            # Use vol-based helper — convert price to implied vol first
            # This is more robust than price-based calibration
            from services.calibration.implied_vol import implied_vol_bisection

            is_call = entry.get("option_type", "call").lower() == "call"
            rate = risk_free.zeroRate(T, ql.Continuous, ql.Annual).rate()
            div_rate = dividend.zeroRate(T, ql.Continuous, ql.Annual).rate()

            iv = implied_vol_bisection(
                market_price=price,
                spot=spot,
                strike=strike,
                T=T,
                rate=rate,
                div_yield=div_rate,
                is_call=is_call,
            )

            helper = ql.HestonModelHelper(
                period,
                ql.TARGET(),
                ql.QuoteHandle(ql.SimpleQuote(spot)),
                strike,
                ql.QuoteHandle(ql.SimpleQuote(iv)),
                risk_free,
                dividend,
            )

            helpers.append(helper)
            helper_info.append({
                "expiry": expiry.isoformat(),
                "T": round(T, 4),
                "strike": strike,
                "moneyness": round(strike / spot, 4),
                "market_price": round(price, 6),
                "implied_vol": round(iv, 6),
            })

        except Exception as e:
            logger.warning(f"Skipping price-based helper at K={strike}, T={T:.3f}: {e}")

    if not helpers:
        raise CalibrationError("No valid calibration helpers from prices.")

    return helpers, helper_info


# ---------------------------------------------------------------------------
# Calibration Service
# ---------------------------------------------------------------------------

@dataclass
class HestonCalibrationService:
    """
    Service for calibrating the Heston model to market data.

    Supports:
    - Calibration to implied vol surface
    - Calibration to option prices
    - Multiple optimizers
    - Fit quality diagnostics
    """

    # Initial parameter guess
    initial_v0: float = 0.04
    initial_kappa: float = 1.5
    initial_theta: float = 0.04
    initial_sigma: float = 0.5
    initial_rho: float = -0.7

    # Optimizer
    optimizer_name: str = "levenberg_marquardt"

    def calibrate_to_surface(
        self,
        market_env: MarketEnvironment,
        underlying: str,
        strikes: List[float],
        expiries: List[date],
    ) -> HestonCalibrationResult:
        """
        Calibrate Heston to implied vol surface.

        This is the standard calibration workflow:
        1. Extract vols from surface at (strike, expiry) grid
        2. Build HestonModelHelper for each point
        3. Optimize Heston parameters to minimize vol error

        Args:
            market_env: Market environment with vol surface
            underlying: Underlying asset code
            strikes:    Strike prices to calibrate to
            expiries:   Expiry dates to calibrate to

        Returns:
            HestonCalibrationResult with calibrated model and diagnostics
        """
        t0 = time.perf_counter()

        # Build helpers
        helpers, helper_info = build_heston_helpers_from_surface(
            market_env, underlying, strikes, expiries,
        )

        # Run calibration
        return self._run_calibration(
            market_env, underlying, helpers, helper_info, t0
        )

    def calibrate_to_prices(
        self,
        market_env: MarketEnvironment,
        underlying: str,
        market_data: List[Dict[str, Any]],
    ) -> HestonCalibrationResult:
        """
        Calibrate Heston to option prices.

        market_data: list of {"expiry": date, "strike": float, "price": float}
        """
        t0 = time.perf_counter()

        helpers, helper_info = build_heston_helpers_from_prices(
            market_env, underlying, market_data,
        )

        return self._run_calibration(
            market_env, underlying, helpers, helper_info, t0
        )

    def _run_calibration(
        self,
        market_env: MarketEnvironment,
        underlying: str,
        helpers: List,
        helper_info: List[Dict],
        t0: float,
    ) -> HestonCalibrationResult:
        """Core calibration loop."""
        initial_params = {
            "v0": self.initial_v0,
            "kappa": self.initial_kappa,
            "theta": self.initial_theta,
            "sigma": self.initial_sigma,
            "rho": self.initial_rho,
        }

        # Build initial model
        heston = HestonModel(
            underlying=underlying,
            v0=self.initial_v0,
            kappa=self.initial_kappa,
            theta=self.initial_theta,
            sigma=self.initial_sigma,
            rho=self.initial_rho,
        )

        try:
            process = heston.build_process(market_env)
            ql_model = ql.HestonModel(process)

            # Set pricing engine for helpers
            engine = ql.AnalyticHestonEngine(ql_model)
            for h in helpers:
                h.setPricingEngine(engine)

            # Optimizer
            optimizer, end_criteria = _create_optimizer(self.optimizer_name)

            # Calibrate
            ql_model.calibrate(helpers, optimizer, end_criteria)

            # Extract calibrated parameters
            cal_v0 = ql_model.v0()
            cal_kappa = ql_model.kappa()
            cal_theta = ql_model.theta()
            cal_sigma = ql_model.sigma()
            cal_rho = ql_model.rho()

            calibrated_params = {
                "v0": round(cal_v0, 8),
                "kappa": round(cal_kappa, 8),
                "theta": round(cal_theta, 8),
                "sigma": round(cal_sigma, 8),
                "rho": round(cal_rho, 8),
            }

            # Update model
            heston.v0 = cal_v0
            heston.kappa = cal_kappa
            heston.theta = cal_theta
            heston.sigma = cal_sigma
            heston.rho = cal_rho

            # Feller condition
            feller = 2 * cal_kappa * cal_theta > cal_sigma ** 2

            # Fit quality per helper
            fit_report = []
            errors = []
            for i, h in enumerate(helpers):
                model_vol = h.impliedVolatility(
                    h.modelValue(), 1e-6, 1000, 0.001, 3.0
                )
                market_vol = helper_info[i].get("market_vol") or helper_info[i].get("implied_vol", 0)
                error = abs(model_vol - market_vol)
                errors.append(error)

                report = {**helper_info[i]}
                report["model_vol"] = round(model_vol, 6)
                report["error"] = round(error, 6)
                report["error_bps"] = round(error * 10000, 2)
                fit_report.append(report)

            import numpy as np
            rmse = float(np.sqrt(np.mean(np.array(errors) ** 2)))
            mae = float(np.mean(errors))
            max_err = float(np.max(errors))

            elapsed = time.perf_counter() - t0

            logger.info(
                f"Heston calibration complete: "
                f"v0={cal_v0:.4f}, κ={cal_kappa:.4f}, θ={cal_theta:.4f}, "
                f"σ={cal_sigma:.4f}, ρ={cal_rho:.4f} | "
                f"RMSE={rmse:.6f}, MAE={mae:.6f}, MaxErr={max_err:.6f} | "
                f"Feller={'✓' if feller else '✗'} | {elapsed:.3f}s"
            )

            return HestonCalibrationResult(
                model=heston,
                parameters=calibrated_params,
                initial_parameters=initial_params,
                fit_report=fit_report,
                total_rmse=rmse,
                total_mae=mae,
                max_error=max_err,
                feller_satisfied=feller,
                optimizer_used=self.optimizer_name,
                elapsed_seconds=elapsed,
            )

        except Exception as e:
            raise CalibrationError(f"Heston calibration failed: {e}") from e