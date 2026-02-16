"""
MCResult — Container for Monte Carlo simulation output.

Stores the full simulation state for audit, debugging, and analysis.
Supports export to Parquet and CSV.

Separated from engine code so it can be imported independently
(e.g., by PricingService, reporting, notebooks).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class MCResult:
    """
    Container for Monte Carlo simulation output.

    Core data (always populated):
        metadata:           Run config (seed, paths, steps, model, T, strike, etc.)
        random_numbers:     Gaussian draws, shape (time_steps, num_paths)
        spot_paths:         Simulated spot prices, shape (time_steps+1, num_paths)
        intrinsic_values:   Payoff at each step, shape (time_steps+1, num_paths)
        discount_factors:   Discount factor at each step, shape (time_steps+1,)
        npv:                Option price (mean of discounted payoffs)
        std_error:          Standard error of the NPV estimate
        confidence_interval: 95% CI (lower, upper)

    American/Bermudan specific:
        continuation_values: Regression-estimated continuation, shape (time_steps+1, num_paths)
        exercise_flags:     Boolean — True where early exercise is optimal, shape (time_steps+1, num_paths)
        exercise_boundary:  Spot level at which exercise is optimal, shape (time_steps+1,)
        cashflows:          Per-path: [exercise_time_idx, payoff], shape (num_paths, 2)
    """

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Core simulation data
    random_numbers: Optional[np.ndarray] = None       # (T, N)
    spot_paths: Optional[np.ndarray] = None            # (T+1, N)
    intrinsic_values: Optional[np.ndarray] = None      # (T+1, N)
    discount_factors: Optional[np.ndarray] = None      # (T+1,)

    # Pricing output
    npv: float = 0.0
    std_error: float = 0.0
    confidence_interval: tuple = (0.0, 0.0)

    # American/Bermudan specific
    continuation_values: Optional[np.ndarray] = None   # (T+1, N)
    exercise_flags: Optional[np.ndarray] = None        # (T+1, N) boolean
    exercise_boundary: Optional[np.ndarray] = None     # (T+1,)
    cashflows: Optional[np.ndarray] = None             # (N, 2)

    # Timing
    elapsed_seconds: float = 0.0

    # -------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------

    def summary(self) -> Dict[str, Any]:
        """Return a human-readable summary dictionary."""
        s = {
            "npv": round(self.npv, 8),
            "std_error": round(self.std_error, 8),
            "confidence_interval_95": (
                round(self.confidence_interval[0], 8),
                round(self.confidence_interval[1], 8),
            ),
            "elapsed_seconds": round(self.elapsed_seconds, 4),
        }
        s.update({k: v for k, v in self.metadata.items() if k != "timestamp"})

        if self.spot_paths is not None:
            s["num_paths"] = self.spot_paths.shape[1]
            s["time_steps"] = self.spot_paths.shape[0] - 1
            s["spot_initial"] = float(self.spot_paths[0, 0])
            s["spot_mean_terminal"] = float(np.mean(self.spot_paths[-1, :]))
            s["spot_std_terminal"] = float(np.std(self.spot_paths[-1, :]))

        if self.exercise_flags is not None:
            # Percentage of paths that exercise before maturity
            early_exercise = np.any(self.exercise_flags[:-1, :], axis=0)
            s["pct_early_exercised"] = round(float(np.mean(early_exercise) * 100), 2)

        return s

    # -------------------------------------------------------------------
    # Export to Parquet
    # -------------------------------------------------------------------

    def to_parquet(self, output_dir: str) -> None:
        """
        Export all MC data to Parquet files.

        Creates:
            output_dir/
            ├── metadata.json
            ├── summary.json
            ├── random_numbers.parquet      (time_steps × num_paths)
            ├── spot_paths.parquet           (time_steps+1 × num_paths)
            ├── intrinsic_values.parquet     (time_steps+1 × num_paths)
            ├── discount_factors.parquet     (time_steps+1,)
            ├── exercise_boundary.parquet    (if American/Bermudan)
            └── cashflows.parquet            (if American/Bermudan)
        """
        import pandas as pd

        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)

        # Metadata & summary
        with open(path / "metadata.json", "w") as f:
            json.dump(self.metadata, f, indent=2, default=str)
        with open(path / "summary.json", "w") as f:
            json.dump(self.summary(), f, indent=2, default=str)

        def _save_matrix(arr: np.ndarray, name: str, row_prefix: str = "t"):
            if arr is not None:
                n_rows, n_cols = arr.shape if arr.ndim == 2 else (len(arr), 1)
                if arr.ndim == 2:
                    df = pd.DataFrame(
                        arr,
                        index=[f"{row_prefix}_{i}" for i in range(n_rows)],
                        columns=[f"path_{j}" for j in range(n_cols)],
                    )
                else:
                    df = pd.DataFrame({name: arr})
                df.to_parquet(path / f"{name}.parquet")

        _save_matrix(self.random_numbers, "random_numbers")
        _save_matrix(self.spot_paths, "spot_paths")
        _save_matrix(self.intrinsic_values, "intrinsic_values")

        if self.discount_factors is not None:
            import pandas as pd
            pd.DataFrame({"discount_factor": self.discount_factors}).to_parquet(
                path / "discount_factors.parquet"
            )

        if self.exercise_boundary is not None:
            import pandas as pd
            pd.DataFrame({
                "time_step": range(len(self.exercise_boundary)),
                "exercise_boundary": self.exercise_boundary,
            }).to_parquet(path / "exercise_boundary.parquet")

        if self.cashflows is not None:
            import pandas as pd
            pd.DataFrame(
                self.cashflows, columns=["exercise_time_step", "payoff"]
            ).to_parquet(path / "cashflows.parquet")

        logger.info(f"MC results exported to {path} (Parquet)")

    # -------------------------------------------------------------------
    # Export to CSV
    # -------------------------------------------------------------------

    def to_csv(self, output_dir: str) -> None:
        """Export all MC data to CSV files."""
        import pandas as pd

        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)

        with open(path / "metadata.json", "w") as f:
            json.dump(self.metadata, f, indent=2, default=str)
        with open(path / "summary.json", "w") as f:
            json.dump(self.summary(), f, indent=2, default=str)

        if self.random_numbers is not None:
            pd.DataFrame(self.random_numbers).to_csv(
                path / "random_numbers.csv", index=False
            )
        if self.spot_paths is not None:
            pd.DataFrame(self.spot_paths).to_csv(
                path / "spot_paths.csv", index=False
            )
        if self.intrinsic_values is not None:
            pd.DataFrame(self.intrinsic_values).to_csv(
                path / "intrinsic_values.csv", index=False
            )
        if self.discount_factors is not None:
            pd.DataFrame({"discount_factor": self.discount_factors}).to_csv(
                path / "discount_factors.csv", index=False
            )
        if self.exercise_boundary is not None:
            pd.DataFrame({"exercise_boundary": self.exercise_boundary}).to_csv(
                path / "exercise_boundary.csv", index=False
            )
        if self.cashflows is not None:
            pd.DataFrame(
                self.cashflows, columns=["exercise_time_step", "payoff"]
            ).to_csv(path / "cashflows.csv", index=False)

        logger.info(f"MC results exported to {path} (CSV)")

    # -------------------------------------------------------------------
    # Load from Parquet
    # -------------------------------------------------------------------

    @classmethod
    def from_parquet(cls, input_dir: str) -> MCResult:
        """Load MCResult from a previously exported Parquet directory."""
        import pandas as pd

        path = Path(input_dir)
        result = cls()

        if (path / "metadata.json").exists():
            with open(path / "metadata.json") as f:
                result.metadata = json.load(f)

        if (path / "summary.json").exists():
            with open(path / "summary.json") as f:
                summary = json.load(f)
                result.npv = summary.get("npv", 0.0)
                result.std_error = summary.get("std_error", 0.0)
                ci = summary.get("confidence_interval_95", (0.0, 0.0))
                result.confidence_interval = tuple(ci)

        def _load(name: str) -> Optional[np.ndarray]:
            fp = path / f"{name}.parquet"
            if fp.exists():
                return pd.read_parquet(fp).values
            return None

        result.random_numbers = _load("random_numbers")
        result.spot_paths = _load("spot_paths")
        result.intrinsic_values = _load("intrinsic_values")

        df = _load("discount_factors")
        if df is not None:
            result.discount_factors = df.flatten()

        eb = _load("exercise_boundary")
        if eb is not None:
            result.exercise_boundary = eb.flatten()

        result.cashflows = _load("cashflows")

        return result
