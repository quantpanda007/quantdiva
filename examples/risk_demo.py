"""
Risk Framework Demo — scenarios, P&L explain, and VaR.

Demonstrates:
1. Build a mini portfolio (vanilla + barrier + digital)
2. Run predefined stress scenarios
3. Spot and vol ladders
4. Spot × Vol matrix (the desk standard)
5. P&L explain between two dates
6. Parametric and Historical VaR

Usage:
    python examples/risk_demo.py
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

# #region agent log
_logpath = Path(__file__).resolve().parent.parent / ".cursor" / "debug.log"
try:
    _logpath.parent.mkdir(parents=True, exist_ok=True)
    _ql_ok, _ql_err = True, None
    try:
        import QuantLib as _ql  # noqa: F401
    except Exception as _e:
        _ql_ok, _ql_err = False, str(_e)
    with open(_logpath, "a", encoding="utf-8") as _f:
        _f.write(json.dumps({"id": "log_import", "timestamp": __import__("time").time() * 1000, "location": "risk_demo.py:import", "message": "Import env", "data": {"executable": sys.executable, "quantlib_ok": _ql_ok, "quantlib_error": _ql_err, "path_prefix": list(sys.path[:3])}, "runId": "run1", "hypothesisId": "H1_H2_H3"}) + "\n")
except Exception:
    pass
# #endregion

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

import registry.bootstrap  # noqa: F401
import QuantLib as ql

from core.enums.definitions import OptionType, ExerciseType, BarrierType
from core.types.value_objects import PricingDate
from instruments.equity.vanilla_option import VanillaOption
from instruments.equity.barrier_option import BarrierOption
from instruments.equity.digital_option import DigitalOption, DigitalType
from market.curves.yield_curve import build_test_market_env
from services.pricers.pricing_service import PricingService
from services.risk.scenario_engine import (
    ScenarioEngine,
    Scenario,
    ShockSpec,
    PREDEFINED_SCENARIOS,
)
from services.risk.pnl_explain import PnLExplainService
from services.risk.var import VaREngine


def build_portfolio():
    """Build a mini portfolio of 5 trades."""
    return [
        # Long ATM call
        VanillaOption(
            _trade_id="PORT-VAN-CALL",
            underlying="SPX",
            strike=100.0,
            expiry=date(2025, 7, 15),
            option_type=OptionType.CALL,
            exercise_type=ExerciseType.EUROPEAN,
            _currency="USD",
        ),
        # Long OTM put (hedging)
        VanillaOption(
            _trade_id="PORT-VAN-PUT",
            underlying="SPX",
            strike=90.0,
            expiry=date(2025, 7, 15),
            option_type=OptionType.PUT,
            exercise_type=ExerciseType.EUROPEAN,
            _currency="USD",
        ),
        # Short down-and-out call (yield enhancement)
        BarrierOption(
            _trade_id="PORT-BAR-DO",
            underlying="SPX",
            strike=100.0,
            expiry=date(2025, 7, 15),
            option_type=OptionType.CALL,
            barrier_type=BarrierType.DOWN_OUT,
            barrier_level=85.0,
            rebate=0.0,
            _currency="USD",
        ),
        # Long digital put (crash insurance)
        DigitalOption(
            _trade_id="PORT-DIG-PUT",
            underlying="SPX",
            strike=90.0,
            expiry=date(2025, 7, 15),
            option_type=OptionType.PUT,
            digital_type=DigitalType.CASH_OR_NOTHING,
            cash_payoff=50.0,
            _currency="USD",
        ),
        # Long OTM call (upside participation)
        VanillaOption(
            _trade_id="PORT-VAN-CALL-OTM",
            underlying="SPX",
            strike=115.0,
            expiry=date(2025, 7, 15),
            option_type=OptionType.CALL,
            exercise_type=ExerciseType.EUROPEAN,
            _currency="USD",
        ),
    ]


def main():
    # #region agent log
    _logpath = Path(__file__).resolve().parent.parent / ".cursor" / "debug.log"  # noqa: PLW0601
    try:
        with open(_logpath, "a", encoding="utf-8") as _f:
            _f.write(json.dumps({"id": "log_main_entry", "timestamp": __import__("time").time() * 1000, "location": "risk_demo.py:main", "message": "main() entered", "data": {}, "runId": "run1", "hypothesisId": "H4"}) + "\n")
    except Exception:
        pass
    # #endregion
    ps = PricingService()

    # ===================================================================
    # 1. Base market and portfolio
    # ===================================================================
    print("=" * 70)
    print("RISK FRAMEWORK DEMO")
    print("=" * 70)

    pricing_date = PricingDate(date(2025, 1, 15))
    base_env = build_test_market_env(
        pricing_date=pricing_date,
        spot=100.0,
        rate=0.05,
        vol=0.20,
        div_yield=0.02,
        underlying="SPX",
    )

    portfolio = build_portfolio()

    # Show base portfolio
    print("\nPortfolio:")
    print(f"{'Trade ID':<22} {'Type':<20} {'Strike':>8} {'NPV':>12}")
    print("-" * 65)
    total = 0.0
    pricing_errors = 0
    for inst in portfolio:
        try:
            npv = ps.price(inst, base_env, model_type="black_scholes", engine_type="analytic").npv
            total += npv
            strike = getattr(inst, "strike", 0)
            print(f"{str(inst.trade_id()):<22} {inst.instrument_type().value:<20} {strike:>8.1f} {npv:>12.4f}")
        except Exception as e:
            pricing_errors += 1
            print(f"{str(inst.trade_id()):<22} ERROR: {e}")
    # #region agent log
    try:
        with open(_logpath, "a", encoding="utf-8") as _f:
            _f.write(json.dumps({"id": "log_portfolio_done", "timestamp": __import__("time").time() * 1000, "location": "risk_demo.py:portfolio", "message": "Portfolio priced", "data": {"total": total, "portfolio_len": len(portfolio), "pricing_errors": pricing_errors}, "runId": "run1", "hypothesisId": "H4"}) + "\n")
    except Exception:
        pass
    # #endregion
    print(f"{'':>50} {'─'*12}")
    print(f"{'Total':>50} {total:>12.4f}")

    # ===================================================================
    # 2. Stress scenarios
    # ===================================================================
    print(f"\n{'='*70}")
    print("STRESS TEST — PREDEFINED SCENARIOS")
    print(f"{'='*70}")

    scenario_engine = ScenarioEngine(pricing_service=ps)

    # Pick key scenarios
    key_scenarios = [
        PREDEFINED_SCENARIOS["spot_down_5pct"],
        PREDEFINED_SCENARIOS["spot_down_10pct"],
        PREDEFINED_SCENARIOS["spot_down_20pct"],
        PREDEFINED_SCENARIOS["spot_up_10pct"],
        PREDEFINED_SCENARIOS["vol_up_5pts"],
        PREDEFINED_SCENARIOS["vol_up_10pts"],
        PREDEFINED_SCENARIOS["crash_scenario"],
        PREDEFINED_SCENARIOS["rally_scenario"],
        PREDEFINED_SCENARIOS["rate_up_100bp"],
    ]

    stress_result = scenario_engine.run_stress_test(portfolio, base_env, key_scenarios)
    stress_result.print_summary()

    # ===================================================================
    # 3. Spot ladder
    # ===================================================================
    print(f"\n{'='*70}")
    print("SPOT LADDER")
    print(f"{'='*70}")

    spot_ladder = scenario_engine.run_spot_ladder(
        portfolio, base_env,
        bumps_pct=[-20, -15, -10, -5, -2, 0, 2, 5, 10, 15, 20],
    )
    spot_ladder.print_summary()

    # ===================================================================
    # 4. Vol ladder
    # ===================================================================
    print(f"\n{'='*70}")
    print("VOL LADDER")
    print(f"{'='*70}")

    vol_ladder = scenario_engine.run_vol_ladder(
        portfolio, base_env,
        bumps_pts=[-0.05, -0.02, 0.0, 0.02, 0.05, 0.10],
    )
    vol_ladder.print_summary()

    # ===================================================================
    # 5. Spot × Vol matrix
    # ===================================================================
    print(f"\n{'='*70}")
    print("SPOT × VOL MATRIX")
    print(f"{'='*70}")

    matrix_result = scenario_engine.run_spot_vol_matrix(
        portfolio, base_env,
        spot_bumps_pct=[-10, -5, 0, 5, 10],
        vol_bumps_pts=[-0.05, 0.0, 0.05, 0.10],
    )

    # Print as 2D grid
    spot_bumps = [-10, -5, 0, 5, 10]
    vol_bumps = [-0.05, 0.0, 0.05, 0.10]

    print(f"\n{'':>12}", end="")
    for v in vol_bumps:
        print(f"  V{v*100:+.0f}pts  ", end="")
    print()
    print("-" * (12 + len(vol_bumps) * 12))

    idx = 0
    expected_cells = len(spot_bumps) * len(vol_bumps)
    for s in spot_bumps:
        print(f"S{s:+3.0f}%    ", end="")
        for v in vol_bumps:
            if idx < len(matrix_result.scenario_results):
                impact = matrix_result.scenario_results[idx].total_impact
                print(f" {impact:>10.4f}", end="")
            idx += 1
        print()
    # #region agent log
    try:
        with open(_logpath, "a", encoding="utf-8") as _f:
            _f.write(json.dumps({"id": "log_matrix_done", "timestamp": __import__("time").time() * 1000, "location": "risk_demo.py:matrix", "message": "Spot×Vol matrix printed", "data": {"scenario_results_len": len(matrix_result.scenario_results), "expected_cells": expected_cells, "spot_bumps": len(spot_bumps), "vol_bumps": len(vol_bumps)}, "runId": "run1", "hypothesisId": "H5"}) + "\n")
    except Exception:
        pass
    # #endregion

    # ===================================================================
    # 6. P&L Explain
    # ===================================================================
    print(f"\n{'='*70}")
    print("P&L EXPLAIN (Day-over-Day)")
    print(f"{'='*70}")

    # Simulate next-day market: spot moved, vol changed, 1 day passed
    next_date = PricingDate(date(2025, 1, 16))
    next_env = build_test_market_env(
        pricing_date=next_date,
        spot=98.5,         # spot dropped 1.5%
        rate=0.05,
        vol=0.22,          # vol up 2pts
        div_yield=0.02,
        underlying="SPX",
    )

    print("\nMarket moves:")
    print(f"  Spot:  100.00 → 98.50  (ΔS = -1.50)")
    print(f"  Vol:   20.00% → 22.00% (Δσ = +2.00pts)")
    print(f"  Rate:  5.00%  → 5.00%  (Δr = 0)")
    print(f"  Time:  +1 day")

    pnl_svc = PnLExplainService(pricing_service=ps)
    portfolio_explain = pnl_svc.explain_portfolio(portfolio, base_env, next_env)
    portfolio_explain.print_report()
    # #region agent log
    try:
        _e0 = portfolio_explain.trade_explains[0] if portfolio_explain.trade_explains else None
        _ratio = (_e0.explained_pnl / _e0.actual_pnl * 100) if (_e0 and abs(_e0.actual_pnl) > 1e-10) else None
        with open(_logpath, "a", encoding="utf-8") as _f:
            _f.write(json.dumps({"id": "log_pnl_explain", "timestamp": __import__("time").time() * 1000, "location": "risk_demo.py:pnl_explain", "message": "P&L explain first trade", "data": {"actual_pnl": _e0.actual_pnl if _e0 else None, "explained_pnl": _e0.explained_pnl if _e0 else None, "explain_ratio_pct": _ratio, "vega_pnl": _e0.vega_pnl if _e0 else None}, "runId": "post-fix", "hypothesisId": "H4"}) + "\n")
    except Exception:
        pass
    # #endregion

    # ===================================================================
    # 7. Parametric VaR
    # ===================================================================
    print(f"\n{'='*70}")
    print("PARAMETRIC VaR (Delta-Normal)")
    print(f"{'='*70}")

    var_engine = VaREngine(pricing_service=ps)

    param_var = var_engine.parametric_var(
        instruments=portfolio,
        market_env=base_env,
        confidence=0.99,
        horizon_days=1,
        annual_vol=0.20,
    )
    param_var.print_report()

    # Also compute 95% VaR
    param_var_95 = var_engine.parametric_var(
        instruments=portfolio,
        market_env=base_env,
        confidence=0.95,
        horizon_days=1,
        annual_vol=0.20,
    )
    print(f"  95% 1-day VaR:  {param_var_95.var:>14.4f}")
    print(f"  99% 1-day VaR:  {param_var.var:>14.4f}")

    # 10-day VaR
    param_var_10d = var_engine.parametric_var(
        instruments=portfolio,
        market_env=base_env,
        confidence=0.99,
        horizon_days=10,
        annual_vol=0.20,
    )
    print(f"  99% 10-day VaR: {param_var_10d.var:>14.4f}")

    # ===================================================================
    # 8. Historical VaR
    # ===================================================================
    print(f"\n{'='*70}")
    print("HISTORICAL VaR (250 scenarios)")
    print(f"{'='*70}")

    # Simulate 250 days of historical returns (realistic fat tails)
    np.random.seed(42)
    # Mix of normal and occasional large moves (student-t like)
    normal_returns = np.random.normal(0, 0.012, 230)
    tail_returns = np.random.normal(-0.02, 0.03, 20)
    historical_returns = np.concatenate([normal_returns, tail_returns])
    np.random.shuffle(historical_returns)

    print(f"\n  Historical returns: {len(historical_returns)} days")
    print(f"  Mean daily return:  {np.mean(historical_returns)*100:>6.2f}%")
    print(f"  Daily vol:          {np.std(historical_returns)*100:>6.2f}%")
    print(f"  Min return:         {np.min(historical_returns)*100:>6.2f}%")
    print(f"  Max return:         {np.max(historical_returns)*100:>6.2f}%")

    hist_var = var_engine.historical_var(
        instruments=portfolio,
        market_env=base_env,
        historical_returns=historical_returns,
        confidence=0.99,
        horizon_days=1,
    )
    hist_var.print_report()

    # ===================================================================
    # Summary
    # ===================================================================
    # #region agent log
    try:
        _worst = stress_result.worst_scenario
        _best = stress_result.best_scenario
        with open(_logpath, "a", encoding="utf-8") as _f:
            _f.write(json.dumps({"id": "log_summary", "timestamp": __import__("time").time() * 1000, "location": "risk_demo.py:summary", "message": "Before summary print", "data": {"worst_is_none": _worst is None, "best_is_none": _best is None, "worst_name": _worst.scenario_name if _worst else None, "best_name": _best.scenario_name if _best else None}, "runId": "run1", "hypothesisId": "H4"}) + "\n")
    except Exception as _e:
        try:
            with open(_logpath, "a", encoding="utf-8") as _f:
                _f.write(json.dumps({"id": "log_summary_err", "timestamp": __import__("time").time() * 1000, "location": "risk_demo.py:summary", "message": "Summary log failed", "data": {"error": str(_e)}, "runId": "run1", "hypothesisId": "H4"}) + "\n")
        except Exception:
            pass
    # #endregion
    print(f"\n{'='*70}")
    print("RISK SUMMARY")
    print(f"{'='*70}")
    print(f"  Portfolio value:        {total:>12.4f}")
    print(f"  99% Parametric VaR:     {param_var.var:>12.4f}")
    print(f"  99% Historical VaR:     {hist_var.var:>12.4f}")
    print(f"  99% Parametric CVaR:    {param_var.cvar:>12.4f}")
    print(f"  99% Historical CVaR:    {hist_var.cvar:>12.4f}")
    print(f"  Worst scenario:         {stress_result.worst_scenario.scenario_name} ({stress_result.worst_scenario.total_impact:+.4f})")
    print(f"  Best scenario:          {stress_result.best_scenario.scenario_name} ({stress_result.best_scenario.total_impact:+.4f})")
    print()


if __name__ == "__main__":
    main()