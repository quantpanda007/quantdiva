"""
FDResult — Diagnostics container for Finite Difference pricing.

Captures grid parameters, convergence info, early exercise boundary,
and Greeks extraction details. Supports export for audit/debugging.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class FDResult:
    """
    Container for Finite Difference pricing diagnostics.

    Attributes:
        metadata:               Run config (scheme, grid sizes, etc.)
        npv:                    Option price from FD solve
        grid_spot_min:          Lower bound of spot grid
        grid_spot_max:          Upper bound of spot grid
        time_steps:             Number of time grid points
        spot_steps:             Number of spot grid points
        vol_steps:              Number of variance grid points (Heston only)
        scheme:                 FD scheme used
        exercise_boundary:      Early exercise boundary S*(t) at each time step
        convergence_data:       NPV at different grid sizes for convergence analysis
        greeks:                 Greeks extracted from FD grid
        elapsed_seconds:        Wall clock time
    """

    metadata: Dict[str, Any] = field(default_factory=dict)

    npv: float = 0.0
    grid_spot_min: float = 0.0
    grid_spot_max: float = 0.0
    time_steps: int = 0
    spot_steps: int = 0
    vol_steps: int = 0
    scheme: str = ""

    exercise_boundary: Optional[np.ndarray] = None
    convergence_data: Optional[List[Dict[str, Any]]] = None
    greeks: Dict[str, Optional[float]] = field(default_factory=dict)

    elapsed_seconds: float = 0.0

    def summary(self) -> Dict[str, Any]:
        s = {
            "npv": round(self.npv, 8),
            "scheme": self.scheme,
            "grid": f"{self.time_steps}×{self.spot_steps}",
            "spot_range": f"[{self.grid_spot_min:.2f}, {self.grid_spot_max:.2f}]",
            "elapsed_seconds": round(self.elapsed_seconds, 4),
        }
        if self.vol_steps > 0:
            s["grid"] += f"×{self.vol_steps}"
        if self.greeks:
            s["greeks"] = {k: round(v, 8) if v is not None else None
                          for k, v in self.greeks.items()}
        if self.exercise_boundary is not None:
            valid = self.exercise_boundary[~np.isnan(self.exercise_boundary)]
            if len(valid) > 0:
                s["exercise_boundary_range"] = f"[{valid.min():.2f}, {valid.max():.2f}]"
        s.update(self.metadata)
        return s

    def to_json(self, output_path: str) -> None:
        """Export diagnostics to JSON."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.summary(), f, indent=2, default=str)
        logger.info(f"FD diagnostics exported to {path}")

    def to_csv(self, output_dir: str) -> None:
        """Export exercise boundary and convergence data to CSV."""
        import pandas as pd

        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)

        with open(path / "fd_summary.json", "w") as f:
            json.dump(self.summary(), f, indent=2, default=str)

        if self.exercise_boundary is not None:
            pd.DataFrame({
                "time_step": range(len(self.exercise_boundary)),
                "exercise_boundary": self.exercise_boundary,
            }).to_csv(path / "fd_exercise_boundary.csv", index=False)

        if self.convergence_data:
            pd.DataFrame(self.convergence_data).to_csv(
                path / "fd_convergence.csv", index=False
            )

        logger.info(f"FD diagnostics exported to {path}")


@dataclass
class ConvergencePoint:
    """Single point in a convergence study."""
    time_steps: int
    spot_steps: int
    vol_steps: int = 0
    npv: float = 0.0
    delta: Optional[float] = None
    gamma: Optional[float] = None
    elapsed_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "time_steps": self.time_steps,
            "spot_steps": self.spot_steps,
            "vol_steps": self.vol_steps,
            "npv": self.npv,
            "delta": self.delta,
            "gamma": self.gamma,
            "elapsed_seconds": self.elapsed_seconds,
        }
