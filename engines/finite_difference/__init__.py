"""
Finite Difference pricing engines.

Modules:
- fd_config: Grid configuration, scheme selection, presets, safeguards
- fd_result: FDResult diagnostics container with convergence data
- fd_dividends: Discrete dividend support (DividendSchedule, DividendVanillaOption)
- fd_vanilla_engine: FDVanillaEngine (BSM), FDHestonVanillaEngine, FDDividendEngine
"""

from engines.finite_difference.fd_config import FDGridConfig, STANDARD_GRID, FINE_GRID, FAST_GRID
from engines.finite_difference.fd_result import FDResult
from engines.finite_difference.fd_dividends import DividendSchedule
from engines.finite_difference.fd_vanilla_engine import (
    FDVanillaEngine,
    FDHestonVanillaEngine,
    FDDividendEngine,
)
