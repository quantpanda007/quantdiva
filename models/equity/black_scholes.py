"""
Black-Scholes-Merton model implementation.

Builds a GeneralizedBlackScholesProcess from market data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import QuantLib as ql

from core.enums.definitions import ModelType
from core.exceptions.errors import ModelError
from core.interfaces.base import BaseModel, MarketEnvironment
from registry import model_registry


@model_registry.register_decorator(ModelType.BLACK_SCHOLES.value)
@dataclass
class BlackScholesModel(BaseModel):
    """
    Black-Scholes-Merton model.

    Builds a GeneralizedBlackScholesProcess which requires:
    - Spot price
    - Risk-free rate curve
    - Dividend yield curve
    - Volatility surface
    """

    underlying: str = ""
    _vol_override: Optional[float] = None  # flat vol override for quick pricing
    _calibrated_params: Dict[str, Any] = field(default_factory=dict)

    def model_type(self) -> ModelType:
        return ModelType.BLACK_SCHOLES

    def parameters(self) -> Dict[str, Any]:
        return {
            "underlying": self.underlying,
            "vol_override": self._vol_override,
            **self._calibrated_params,
        }

    def build_process(self, market_env: MarketEnvironment) -> ql.GeneralizedBlackScholesProcess:
        """Build BSM process from market environment."""
        try:
            # Spot
            spot = market_env.spot_prices.get(self.underlying)
            if spot is None:
                raise ModelError(f"No spot price for {self.underlying}")
            spot_handle = ql.QuoteHandle(ql.SimpleQuote(spot))

            # Risk-free rate (discount curve)
            risk_free = market_env.get_discount_curve(
                # try underlying-specific, fall back to currency
                self.underlying if self.underlying in market_env.discount_curves
                else "USD"
            )

            # Dividend yield
            div_key = f"{self.underlying}_div"
            if div_key in market_env.dividend_curves:
                dividend = market_env.dividend_curves[div_key]
            else:
                # Assume zero dividends
                dividend = ql.YieldTermStructureHandle(
                    ql.FlatForward(
                        market_env.pricing_date.to_ql(), 0.0, ql.Actual365Fixed()
                    )
                )

            # Volatility
            if self._vol_override is not None:
                vol = ql.BlackVolTermStructureHandle(
                    ql.BlackConstantVol(
                        market_env.pricing_date.to_ql(),
                        ql.NullCalendar(),
                        self._vol_override,
                        ql.Actual365Fixed(),
                    )
                )
            else:
                vol = market_env.get_vol_surface(self.underlying)

            return ql.BlackScholesMertonProcess(spot_handle, dividend, risk_free, vol)

        except ModelError:
            raise
        except Exception as e:
            raise ModelError(f"Failed to build BSM process: {e}") from e

    def calibrate(self, market_env: MarketEnvironment, helpers: List[Any]) -> None:
        """BSM has no calibration — it's fully implied by market data."""
        pass


@model_registry.register_decorator(ModelType.HESTON.value)
@dataclass
class HestonModel(BaseModel):
    """
    Heston stochastic volatility model.

    Parameters:
    - v0: initial variance
    - kappa: mean reversion speed
    - theta: long-run variance
    - sigma: vol of vol
    - rho: correlation between spot and vol
    """

    underlying: str = ""
    v0: float = 0.04       # initial variance (vol^2)
    kappa: float = 1.0     # mean reversion speed
    theta: float = 0.04    # long-run variance
    sigma: float = 0.5     # vol of vol
    rho: float = -0.7      # spot-vol correlation

    def model_type(self) -> ModelType:
        return ModelType.HESTON

    def parameters(self) -> Dict[str, Any]:
        return {
            "underlying": self.underlying,
            "v0": self.v0,
            "kappa": self.kappa,
            "theta": self.theta,
            "sigma": self.sigma,
            "rho": self.rho,
        }

    def validate(self) -> bool:
        """Feller condition: 2*kappa*theta > sigma^2."""
        feller = 2 * self.kappa * self.theta > self.sigma ** 2
        if not feller:
            import logging
            logging.getLogger(__name__).warning(
                f"Feller condition violated: 2κθ={2*self.kappa*self.theta:.4f} "
                f"<= σ²={self.sigma**2:.4f}"
            )
        return True  # warn but don't prevent

    def build_process(self, market_env: MarketEnvironment) -> ql.HestonProcess:
        try:
            spot = market_env.spot_prices.get(self.underlying)
            if spot is None:
                raise ModelError(f"No spot price for {self.underlying}")

            risk_free = market_env.get_discount_curve("USD")

            div_key = f"{self.underlying}_div"
            if div_key in market_env.dividend_curves:
                dividend = market_env.dividend_curves[div_key]
            else:
                dividend = ql.YieldTermStructureHandle(
                    ql.FlatForward(market_env.pricing_date.to_ql(), 0.0, ql.Actual365Fixed())
                )

            return ql.HestonProcess(
                risk_free, dividend,
                ql.QuoteHandle(ql.SimpleQuote(spot)),
                self.v0, self.kappa, self.theta, self.sigma, self.rho,
            )

        except ModelError:
            raise
        except Exception as e:
            raise ModelError(f"Failed to build Heston process: {e}") from e

    def calibrate(self, market_env: MarketEnvironment, helpers: List[Any]) -> None:
        """
        Calibrate Heston to a set of market option helpers.

        helpers should be a list of ql.HestonModelHelper instances.
        """
        try:
            process = self.build_process(market_env)
            ql_model = ql.HestonModel(process)

            engine = ql.AnalyticHestonEngine(ql_model)
            for h in helpers:
                h.setPricingEngine(engine)

            optimizer = ql.LevenbergMarquardt()
            end_criteria = ql.EndCriteria(1000, 500, 1e-8, 1e-8, 1e-8)

            ql_model.calibrate(helpers, optimizer, end_criteria)

            # Update parameters from calibration
            self.v0 = ql_model.v0()
            self.kappa = ql_model.kappa()
            self.theta = ql_model.theta()
            self.sigma = ql_model.sigma()
            self.rho = ql_model.rho()

            self.validate()

        except Exception as e:
            from core.exceptions.errors import CalibrationError
            raise CalibrationError(f"Heston calibration failed: {e}") from e
