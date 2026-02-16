"""
Monte Carlo Greeks computation.

Three approaches, each with different tradeoffs:

1. Pathwise (Tangent) Method:
   - Differentiates the payoff along the path
   - Works for: delta (smooth payoffs), gamma (with smoothing)
   - Does NOT work for: discontinuous payoffs (digitals, barriers)
   - Fast: one simulation, no re-pricing

2. Likelihood Ratio (Score Function) Method:
   - Differentiates the probability density, not the payoff
   - Works for: ALL payoffs including discontinuous
   - Gives: vega, rho (parameters that enter the density)
   - Higher variance than pathwise

3. Bump-and-Reprice (Finite Difference):
   - Re-runs MC with bumped input
   - Works for: everything
   - Slow: requires 2 or 3 full MC runs per Greek
   - Most robust, used as benchmark

Theory:
    Pathwise delta:
        Δ = E[exp(-rT) * ∂payoff/∂S(T) * ∂S(T)/∂S(0)]
        For GBM: ∂S(T)/∂S(0) = S(T)/S(0)
        For call: ∂payoff/∂S(T) = 1{S(T)>K}
        So: Δ = E[exp(-rT) * 1{S(T)>K} * S(T)/S(0)]

    Likelihood ratio vega:
        ν = E[exp(-rT) * payoff * ∂ln(f)/∂σ]
        For GBM: ∂ln(f)/∂σ = (Z² - 1)/σ - Z*√T
        where Z = (ln(S(T)/S(0)) - (r-q-σ²/2)T) / (σ√T)

Usage:
    from engines.monte_carlo.mc_greeks import MCGreeks

    greeks = MCGreeks()
    result = greeks.compute_all(
        spot_paths=paths, random_numbers=Z,
        strike=100, T=1.0, rate=0.05, div_yield=0.02, vol=0.20,
        is_call=True,
    )
    print(result)
    # {'delta': 0.6321, 'gamma': 0.0189, 'vega': 37.52, 'theta': -6.41, 'rho': 41.23}
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class MCGreeksResult:
    """Container for MC Greeks output."""
    delta: Optional[float] = None           # pathwise
    gamma: Optional[float] = None           # pathwise with smoothing
    vega: Optional[float] = None            # likelihood ratio
    theta: Optional[float] = None           # bump-and-reprice
    rho: Optional[float] = None             # likelihood ratio
    delta_std_error: Optional[float] = None
    gamma_std_error: Optional[float] = None
    vega_std_error: Optional[float] = None
    rho_std_error: Optional[float] = None
    method: Dict[str, str] = field(default_factory=dict)  # which method was used for each

    def to_dict(self) -> Dict[str, Optional[float]]:
        return {
            "delta": self.delta,
            "gamma": self.gamma,
            "vega": self.vega,
            "theta": self.theta,
            "rho": self.rho,
        }

    def to_dict_with_errors(self) -> Dict[str, Optional[float]]:
        return {
            "delta": self.delta,
            "delta_std_error": self.delta_std_error,
            "gamma": self.gamma,
            "gamma_std_error": self.gamma_std_error,
            "vega": self.vega,
            "vega_std_error": self.vega_std_error,
            "theta": self.theta,
            "rho": self.rho,
            "rho_std_error": self.rho_std_error,
        }


@dataclass
class MCGreeks:
    """
    Computes Greeks from MC simulation data.

    Uses pathwise for delta/gamma, likelihood ratio for vega/rho.
    """

    # Smoothing bandwidth for gamma (as fraction of strike)
    gamma_bandwidth: float = 0.01

    def compute_all(
        self,
        spot_paths: np.ndarray,
        random_numbers: np.ndarray,
        strike: float,
        T: float,
        rate: float,
        div_yield: float,
        vol: float,
        is_call: bool,
    ) -> MCGreeksResult:
        """
        Compute all available Greeks from MC simulation data.

        Args:
            spot_paths:      (T+1, N) simulated spot paths
            random_numbers:  (T, N) Gaussian draws used in simulation
            strike:          option strike
            T:               time to maturity
            rate:            risk-free rate
            div_yield:       dividend yield
            vol:             Black-Scholes volatility
            is_call:         True for call, False for put

        Returns:
            MCGreeksResult with all computed Greeks
        """
        result = MCGreeksResult()

        S0 = spot_paths[0, 0]
        S_T = spot_paths[-1, :]
        N = len(S_T)
        df = np.exp(-rate * T)

        # --- Pathwise Delta ---
        delta_val, delta_se = self._pathwise_delta(S0, S_T, strike, T, rate, df, is_call)
        result.delta = delta_val
        result.delta_std_error = delta_se
        result.method["delta"] = "pathwise"

        # --- Pathwise Gamma (with smoothing) ---
        gamma_val, gamma_se = self._pathwise_gamma(
            S0, S_T, strike, T, rate, vol, df, is_call
        )
        result.gamma = gamma_val
        result.gamma_std_error = gamma_se
        result.method["gamma"] = "pathwise_smoothed"

        # --- Likelihood Ratio Vega ---
        vega_val, vega_se = self._lr_vega(
            S0, S_T, random_numbers, strike, T, rate, div_yield, vol, df, is_call
        )
        result.vega = vega_val
        result.vega_std_error = vega_se
        result.method["vega"] = "likelihood_ratio"

        # --- Likelihood Ratio Rho ---
        rho_val, rho_se = self._lr_rho(
            S0, S_T, random_numbers, strike, T, rate, div_yield, vol, df, is_call
        )
        result.rho = rho_val
        result.rho_std_error = rho_se
        result.method["rho"] = "likelihood_ratio"

        # --- Theta (finite difference on T) ---
        result.theta = self._fd_theta(S0, S_T, strike, T, rate, div_yield, vol, df, is_call)
        result.method["theta"] = "finite_difference"

        return result

    # -------------------------------------------------------------------
    # Pathwise Delta
    # -------------------------------------------------------------------

    def _pathwise_delta(
        self,
        S0: float,
        S_T: np.ndarray,
        strike: float,
        T: float,
        rate: float,
        df: float,
        is_call: bool,
    ) -> tuple:
        """
        Pathwise (tangent) delta.

        For call: Δ = E[exp(-rT) * 1{S(T)>K} * S(T)/S(0)]
        For put:  Δ = -E[exp(-rT) * 1{S(T)<K} * S(T)/S(0)]

        Under GBM, ∂S(T)/∂S(0) = S(T)/S(0)
        """
        N = len(S_T)
        path_sensitivity = S_T / S0  # ∂S(T)/∂S(0)

        if is_call:
            itm = S_T > strike
            delta_samples = df * itm.astype(float) * path_sensitivity
        else:
            itm = S_T < strike
            delta_samples = -df * itm.astype(float) * path_sensitivity

        delta = float(np.mean(delta_samples))
        se = float(np.std(delta_samples) / np.sqrt(N))
        return delta, se

    # -------------------------------------------------------------------
    # Pathwise Gamma (smoothed)
    # -------------------------------------------------------------------

    def _pathwise_gamma(
        self,
        S0: float,
        S_T: np.ndarray,
        strike: float,
        T: float,
        rate: float,
        vol: float,
        df: float,
        is_call: bool,
    ) -> tuple:
        """
        Pathwise gamma using Broadie-Glasserman smoothing.

        Gamma involves the delta function δ(S(T)-K), which we smooth
        with a Gaussian kernel of bandwidth ε.

        Γ ≈ E[exp(-rT) * φ_ε(S(T)-K) * (S(T)/S(0))² / S(T)]
        where φ_ε is a Gaussian density with std = ε
        """
        N = len(S_T)
        eps = self.gamma_bandwidth * strike  # bandwidth

        # Gaussian kernel centered at strike
        kernel = np.exp(-0.5 * ((S_T - strike) / eps) ** 2) / (eps * np.sqrt(2 * np.pi))

        # Gamma samples
        gamma_samples = df * kernel * (S_T / S0) ** 2 / S_T

        gamma = float(np.mean(gamma_samples))
        se = float(np.std(gamma_samples) / np.sqrt(N))
        return gamma, se

    # -------------------------------------------------------------------
    # Likelihood Ratio Vega
    # -------------------------------------------------------------------

    def _lr_vega(
        self,
        S0: float,
        S_T: np.ndarray,
        Z: np.ndarray,
        strike: float,
        T: float,
        rate: float,
        div_yield: float,
        vol: float,
        df: float,
        is_call: bool,
    ) -> tuple:
        """
        Likelihood ratio vega.

        ν = E[exp(-rT) * payoff(S(T)) * ∂ln(f)/∂σ]

        For GBM with Z ~ N(0,1):
        ∂ln(f)/∂σ = -1/σ + Z_total² / σ - Z_total * √T
        where Z_total is the composite normal driving S(T):
            Z_total = [ln(S(T)/S(0)) - (r-q-σ²/2)T] / (σ√T)
        """
        N = len(S_T)

        # Reconstruct Z from terminal values (more accurate than using path Z)
        Z_total = (np.log(S_T / S0) - (rate - div_yield - 0.5 * vol ** 2) * T) / (vol * np.sqrt(T))

        # Score function for vega
        score = (Z_total ** 2 - 1) / vol - Z_total * np.sqrt(T)

        # Payoff
        if is_call:
            payoff = np.maximum(S_T - strike, 0.0)
        else:
            payoff = np.maximum(strike - S_T, 0.0)

        vega_samples = df * payoff * score

        vega = float(np.mean(vega_samples))
        se = float(np.std(vega_samples) / np.sqrt(N))
        return vega, se

    # -------------------------------------------------------------------
    # Likelihood Ratio Rho
    # -------------------------------------------------------------------

    def _lr_rho(
        self,
        S0: float,
        S_T: np.ndarray,
        Z: np.ndarray,
        strike: float,
        T: float,
        rate: float,
        div_yield: float,
        vol: float,
        df: float,
        is_call: bool,
    ) -> tuple:
        """
        Likelihood ratio rho.

        ρ = E[-T * exp(-rT) * payoff] + E[exp(-rT) * payoff * ∂ln(f)/∂r]

        For GBM:
        ∂ln(f)/∂r = Z_total * √T / σ
        Combined with discounting term: -T * payoff + payoff * Z_total * √T / σ
        """
        N = len(S_T)

        Z_total = (np.log(S_T / S0) - (rate - div_yield - 0.5 * vol ** 2) * T) / (vol * np.sqrt(T))

        if is_call:
            payoff = np.maximum(S_T - strike, 0.0)
        else:
            payoff = np.maximum(strike - S_T, 0.0)

        # Two terms: discounting sensitivity + drift sensitivity
        rho_samples = df * payoff * (-T + Z_total * np.sqrt(T) / vol)

        rho = float(np.mean(rho_samples))
        se = float(np.std(rho_samples) / np.sqrt(N))
        return rho, se

    # -------------------------------------------------------------------
    # Finite Difference Theta
    # -------------------------------------------------------------------

    def _fd_theta(
        self,
        S0: float,
        S_T: np.ndarray,
        strike: float,
        T: float,
        rate: float,
        div_yield: float,
        vol: float,
        df: float,
        is_call: bool,
    ) -> Optional[float]:
        """
        Theta via finite difference on T.

        θ ≈ (V(T-dT) - V(T)) / dT

        We approximate by recomputing the discounted payoff with T-dT.
        This is approximate since we don't re-simulate paths.
        """
        dT = 1.0 / 365  # 1 day

        if T <= dT:
            return None

        if is_call:
            payoff = np.maximum(S_T - strike, 0.0)
        else:
            payoff = np.maximum(strike - S_T, 0.0)

        # Price at T
        V_T = float(np.mean(np.exp(-rate * T) * payoff))

        # Approximate price at T-dT (same terminal values, different discounting)
        # This is a rough approximation — proper theta requires resimulation
        V_T_minus = float(np.mean(np.exp(-rate * (T - dT)) * payoff))

        theta = (V_T_minus - V_T) / dT  # per-day theta
        return theta
