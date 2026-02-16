"""
Random number generation for Monte Carlo simulation.

Provides:
- PseudoRandomGenerator: standard Mersenne Twister (numpy default)
- SobolGenerator: Sobol low-discrepancy quasi-random sequences
- HaltonGenerator: Halton sequence (simpler alternative to Sobol)

Sobol sequences fill the sample space more uniformly than pseudorandom
numbers, leading to faster convergence: O(1/N) vs O(1/√N).

Usage:
    from engines.monte_carlo.rng import SobolGenerator, PseudoRandomGenerator

    # Sobol (recommended for ≤ ~100 dimensions)
    gen = SobolGenerator(seed=42, scramble=True)
    Z = gen.generate(time_steps=252, num_paths=10000)

    # Pseudorandom (standard, always works)
    gen = PseudoRandomGenerator(seed=42)
    Z = gen.generate(time_steps=252, num_paths=10000)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


class BaseRNG(ABC):
    """Abstract base for random number generators."""

    @abstractmethod
    def generate(self, time_steps: int, num_paths: int) -> np.ndarray:
        """
        Generate standard normal random numbers.

        Returns:
            Z: shape (time_steps, num_paths) — standard normal draws
        """
        ...

    @abstractmethod
    def name(self) -> str:
        ...


# ---------------------------------------------------------------------------
# Pseudorandom (Mersenne Twister)
# ---------------------------------------------------------------------------

@dataclass
class PseudoRandomGenerator(BaseRNG):
    """
    Standard pseudorandom number generator (Mersenne Twister).

    Properties:
    - O(1/√N) convergence
    - Works for any dimensionality
    - Reproducible with seed
    """

    seed: int = 42

    def name(self) -> str:
        return "pseudorandom"

    def generate(self, time_steps: int, num_paths: int) -> np.ndarray:
        rng = np.random.RandomState(self.seed)
        return rng.standard_normal((time_steps, num_paths))


# ---------------------------------------------------------------------------
# Sobol (Quasi-random)
# ---------------------------------------------------------------------------

@dataclass
class SobolGenerator(BaseRNG):
    """
    Sobol low-discrepancy quasi-random sequence.

    Properties:
    - O(1/N) convergence (much faster than pseudorandom)
    - Best for dimensionality ≤ ~1000 (time_steps × factors)
    - Scrambled Sobol adds randomization for unbiased error estimation
    - Requires scipy ≥ 1.7 for Sobol support

    Limitations:
    - num_paths should be a power of 2 for optimal uniformity
    - Very high dimensions degrade to pseudorandom performance

    Args:
        seed:       Random seed for scrambling
        scramble:   Apply Owen scrambling (recommended for error estimation)
    """

    seed: int = 42
    scramble: bool = True

    def name(self) -> str:
        return f"sobol{'_scrambled' if self.scramble else ''}"

    def generate(self, time_steps: int, num_paths: int) -> np.ndarray:
        """
        Generate Sobol quasi-random standard normals.

        Uses scipy.stats.qmc.Sobol to generate uniform [0,1) points,
        then applies inverse normal CDF (Moro's algorithm via scipy).
        """
        try:
            from scipy.stats import qmc, norm

            # Sobol engine: dimensions = time_steps
            sampler = qmc.Sobol(d=time_steps, scramble=self.scramble, seed=self.seed)

            # Number of samples: round up to power of 2 for Sobol
            m = int(np.ceil(np.log2(max(num_paths, 2))))
            n_samples = 2 ** m

            # Generate uniform samples: shape (n_samples, time_steps)
            uniform = sampler.random(n_samples)

            # Trim to requested number of paths
            uniform = uniform[:num_paths, :]

            # Clip to avoid inf at boundaries
            uniform = np.clip(uniform, 1e-10, 1 - 1e-10)

            # Inverse normal CDF: uniform → standard normal
            Z = norm.ppf(uniform)

            # Transpose to (time_steps, num_paths)
            return Z.T

        except ImportError:
            logger.warning(
                "scipy.stats.qmc not available. Falling back to pseudorandom. "
                "Install scipy >= 1.7 for Sobol support."
            )
            return PseudoRandomGenerator(self.seed).generate(time_steps, num_paths)

    @staticmethod
    def optimal_paths(desired_paths: int) -> int:
        """
        Return the nearest power-of-2 ≥ desired_paths.

        Sobol sequences are most uniform when N = 2^m.
        """
        m = int(np.ceil(np.log2(max(desired_paths, 2))))
        return 2 ** m


# ---------------------------------------------------------------------------
# Halton (Quasi-random, simpler alternative)
# ---------------------------------------------------------------------------

@dataclass
class HaltonGenerator(BaseRNG):
    """
    Halton low-discrepancy sequence.

    Simpler than Sobol but degrades faster in high dimensions.
    Good for ≤ ~20 dimensions (time steps).

    Args:
        seed:       Random seed for scrambling
        scramble:   Apply scrambling
    """

    seed: int = 42
    scramble: bool = True

    def name(self) -> str:
        return f"halton{'_scrambled' if self.scramble else ''}"

    def generate(self, time_steps: int, num_paths: int) -> np.ndarray:
        try:
            from scipy.stats import qmc, norm

            sampler = qmc.Halton(d=time_steps, scramble=self.scramble, seed=self.seed)
            uniform = sampler.random(num_paths)
            uniform = np.clip(uniform, 1e-10, 1 - 1e-10)
            Z = norm.ppf(uniform)
            return Z.T

        except ImportError:
            logger.warning("scipy.stats.qmc not available. Falling back to pseudorandom.")
            return PseudoRandomGenerator(self.seed).generate(time_steps, num_paths)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_rng(
    rng_type: str = "pseudorandom",
    seed: int = 42,
    scramble: bool = True,
) -> BaseRNG:
    """
    Create a random number generator by name.

    Args:
        rng_type: "pseudorandom", "sobol", "halton"
        seed: random seed
        scramble: scramble quasi-random sequences

    Returns:
        BaseRNG instance
    """
    rng_map = {
        "pseudorandom": lambda: PseudoRandomGenerator(seed=seed),
        "mersenne": lambda: PseudoRandomGenerator(seed=seed),
        "sobol": lambda: SobolGenerator(seed=seed, scramble=scramble),
        "halton": lambda: HaltonGenerator(seed=seed, scramble=scramble),
    }

    factory = rng_map.get(rng_type.lower())
    if factory is None:
        raise ValueError(
            f"Unknown RNG type: '{rng_type}'. Available: {list(rng_map.keys())}"
        )
    return factory()


# ---------------------------------------------------------------------------
# Antithetic wrapper
# ---------------------------------------------------------------------------

def apply_antithetic(Z: np.ndarray, num_paths: int) -> np.ndarray:
    """
    Apply antithetic variates to a random number array.

    Takes the first half of paths and mirrors them:
    Z_anti = [-Z_1, ..., -Z_{N/2}]

    Args:
        Z: shape (time_steps, M) where M >= num_paths // 2
        num_paths: desired final number of paths

    Returns:
        Z_combined: shape (time_steps, num_paths)
    """
    half = num_paths // 2
    Z_first = Z[:, :half]
    Z_second = -Z_first

    if num_paths % 2 == 0:
        return np.column_stack([Z_first, Z_second])
    else:
        # Odd number: keep one extra non-mirrored path
        return np.column_stack([Z_first, Z_second, Z[:, half:half + 1]])
