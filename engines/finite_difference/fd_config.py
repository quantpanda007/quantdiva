"""
Finite Difference grid configuration.

Controls:
- Spot grid bounds (min/max)
- Grid density
- FD scheme selection
- Boundary conditions
- Performance safeguards

Fixes from audit:
✓ Expose FD scheme (Crank-Nicolson, Douglas, etc.)
✓ Configurable spot grid min/max and boundary conditions
✓ Grid size warnings and performance caps
✓ Adaptive grid guidance
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FD Schemes available in QuantLib
# ---------------------------------------------------------------------------

FD_SCHEMES = {
    "crank_nicolson": "CrankNicolson",
    "cn": "CrankNicolson",
    "douglas": "Douglas",
    "craig_sneyd": "CraigSneyd",
    "hundsdorfer_verwer": "HundsdorferVerwer",
    "hv": "HundsdorferVerwer",
    "modified_craig_sneyd": "ModifiedCraigSneyd",
    "mcs": "ModifiedCraigSneyd",
    "implicit_euler": "ImplicitEuler",
    "explicit_euler": "ExplicitEuler",
}


# ---------------------------------------------------------------------------
# Grid Configuration
# ---------------------------------------------------------------------------

@dataclass
class FDGridConfig:
    """
    Configuration for Finite Difference grid.

    Attributes:
        time_steps:      Number of time grid points (default: 200)
        spot_steps:      Number of spot grid points (default: 400)
        vol_steps:       Number of variance grid points for 2D PDE (Heston, default: 50)
        damping_steps:   Rannacher smoothing steps for discontinuous payoffs (default: 0)

        spot_min_factor: Lower spot bound as fraction of strike (default: 0.01)
                         Grid goes from strike * spot_min_factor
        spot_max_factor: Upper spot bound as multiple of strike (default: 5.0)
                         Grid goes up to strike * spot_max_factor

        scheme:          FD scheme: "crank_nicolson", "douglas", "craig_sneyd",
                         "hundsdorfer_verwer", "implicit_euler", "explicit_euler"
                         Default: "crank_nicolson"

        theta:           Theta parameter for mixed scheme (0=explicit, 0.5=CN, 1=implicit)
                         Only used if scheme supports it. Default: 0.5

    Performance safeguards:
        max_total_nodes:  Maximum total grid nodes (time × spot × vol). Default: 50M.
        warn_threshold:   Warn if total nodes exceed this. Default: 5M.
    """

    time_steps: int = 200
    spot_steps: int = 400
    vol_steps: int = 50
    damping_steps: int = 0

    # Grid bounds
    spot_min_factor: float = 0.01
    spot_max_factor: float = 5.0

    # Scheme
    scheme: str = "crank_nicolson"
    theta: float = 0.5

    # Safeguards
    max_total_nodes: int = 50_000_000
    warn_threshold: int = 5_000_000

    def validate(self, is_2d: bool = False) -> None:
        """Validate grid configuration and warn about performance."""
        if self.time_steps < 10:
            raise ValueError(f"time_steps too small: {self.time_steps}. Minimum: 10.")
        if self.spot_steps < 10:
            raise ValueError(f"spot_steps too small: {self.spot_steps}. Minimum: 10.")

        if self.spot_min_factor <= 0 or self.spot_min_factor >= 1:
            raise ValueError(
                f"spot_min_factor must be in (0, 1), got {self.spot_min_factor}"
            )
        if self.spot_max_factor <= 1:
            raise ValueError(
                f"spot_max_factor must be > 1, got {self.spot_max_factor}"
            )

        # Scheme validation
        if self.scheme.lower() not in FD_SCHEMES:
            raise ValueError(
                f"Unknown FD scheme: '{self.scheme}'. "
                f"Available: {list(FD_SCHEMES.keys())}"
            )

        # Performance check
        if is_2d:
            total_nodes = self.time_steps * self.spot_steps * self.vol_steps
        else:
            total_nodes = self.time_steps * self.spot_steps

        if total_nodes > self.max_total_nodes:
            raise ValueError(
                f"Grid too large: {total_nodes:,} nodes "
                f"(limit: {self.max_total_nodes:,}). "
                f"Reduce time_steps ({self.time_steps}) or "
                f"spot_steps ({self.spot_steps})"
                + (f" or vol_steps ({self.vol_steps})" if is_2d else "")
                + "."
            )

        if total_nodes > self.warn_threshold:
            logger.warning(
                f"FD grid has {total_nodes:,} nodes. "
                f"This may be slow. Consider reducing grid size."
            )

    def get_scheme_name(self) -> str:
        """Return the QuantLib scheme name."""
        return FD_SCHEMES[self.scheme.lower()]

    def compute_spot_bounds(self, strike: float, spot: float) -> tuple:
        """
        Compute spot grid bounds based on strike and current spot.

        Returns (spot_min, spot_max).
        """
        # Use strike as reference for symmetric grid around ATM
        reference = max(strike, spot)
        spot_min = reference * self.spot_min_factor
        spot_max = reference * self.spot_max_factor
        return spot_min, spot_max

    def estimate_runtime_ms(self, is_2d: bool = False) -> float:
        """Rough runtime estimate in milliseconds."""
        if is_2d:
            nodes = self.time_steps * self.spot_steps * self.vol_steps
            # ~1ms per 10k nodes for 2D
            return nodes / 10_000
        else:
            nodes = self.time_steps * self.spot_steps
            # ~1ms per 50k nodes for 1D
            return nodes / 50_000

    def __repr__(self) -> str:
        return (
            f"FDGridConfig("
            f"t={self.time_steps}, s={self.spot_steps}, "
            f"scheme={self.scheme}, "
            f"spot=[{self.spot_min_factor}K, {self.spot_max_factor}K])"
        )


# ---------------------------------------------------------------------------
# Preset configurations
# ---------------------------------------------------------------------------

FAST_GRID = FDGridConfig(time_steps=50, spot_steps=100, vol_steps=20, scheme="crank_nicolson")
STANDARD_GRID = FDGridConfig(time_steps=200, spot_steps=400, vol_steps=50, scheme="crank_nicolson")
FINE_GRID = FDGridConfig(time_steps=500, spot_steps=1000, vol_steps=100, scheme="crank_nicolson")
BENCHMARK_GRID = FDGridConfig(time_steps=1000, spot_steps=2000, vol_steps=150, scheme="crank_nicolson")

# For short-maturity options, damping helps with stability
SHORT_MATURITY_GRID = FDGridConfig(
    time_steps=200, spot_steps=400, damping_steps=5, scheme="crank_nicolson"
)

# Douglas scheme for 2D (Heston) — better for mixed derivative terms
HESTON_GRID = FDGridConfig(
    time_steps=100, spot_steps=200, vol_steps=50, scheme="douglas"
)
