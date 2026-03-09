"""
Risk management services.

Modules:
- scenario_engine: Stress testing, spot/vol/rate ladders, spot×vol matrix
- pnl_explain: Greek P&L attribution (Taylor expansion)
- var: Value-at-Risk (parametric, historical, Monte Carlo)
"""

from services.risk.scenario_engine import ScenarioEngine, Scenario, ShockSpec, StressTestResult
from services.risk.pnl_explain import PnLExplainService, PnLExplainResult, PortfolioPnLExplain
from services.risk.var import VaREngine, VaRResult