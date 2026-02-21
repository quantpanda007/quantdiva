"""
QuantPricer Integration Test Suite
===================================

Tests every API endpoint via the Dash API client.
Run with backend running on port 8000:

    cd frontend/dash
    python test_integration.py

Reports: PASS / FAIL / SKIP for each endpoint.
"""

from __future__ import annotations

import sys
import time
import traceback
from typing import Any, Dict, List

# Add parent to path so we can import services
sys.path.insert(0, ".")

from services.api_client import api_client, APIError


# ─── Test infrastructure ──────────────────────────────────────────

class TestResult:
    def __init__(self, name: str, status: str, detail: str = "", elapsed_ms: float = 0):
        self.name = name
        self.status = status  # PASS, FAIL, SKIP
        self.detail = detail
        self.elapsed_ms = elapsed_ms


results: List[TestResult] = []

def run_test(name: str, func, *args, **kwargs):
    """Run a test, catch exceptions, record result."""
    t0 = time.perf_counter()
    try:
        result = func(*args, **kwargs)
        elapsed = (time.perf_counter() - t0) * 1000
        results.append(TestResult(name, "PASS", str(result)[:200], elapsed))
        print(f"  ✓ {name} ({elapsed:.0f}ms)")
        return result
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        detail = str(e)
        results.append(TestResult(name, "FAIL", detail, elapsed))
        print(f"  ✗ {name} — {detail[:120]}")
        return None


# ─── Test data ────────────────────────────────────────────────────

VANILLA_INSTRUMENT = {
    "type": "vanilla_option",
    "params": {
        "trade_id": "TEST-VAN-001",
        "underlying": "AAPL",
        "strike": 185.0,
        "expiry": "2026-01-15",
        "option_type": "call",
        "exercise_type": "european",
        "currency": "USD",
    },
}

BARRIER_INSTRUMENT = {
    "type": "barrier_option",
    "params": {
        "trade_id": "TEST-BAR-001",
        "underlying": "AAPL",
        "strike": 185.0,
        "expiry": "2026-01-15",
        "option_type": "call",
        "barrier_type": "down_out",
        "barrier_level": 160.0,
        "rebate": 0.0,
    },
}

DIGITAL_INSTRUMENT = {
    "type": "digital_option",
    "params": {
        "trade_id": "TEST-DIG-001",
        "underlying": "AAPL",
        "strike": 185.0,
        "expiry": "2026-01-15",
        "option_type": "call",
        "digital_type": "cash_or_nothing",
        "cash_payoff": 100.0,
    },
}

ASIAN_INSTRUMENT = {
    "type": "asian_option",
    "params": {
        "trade_id": "TEST-ASIAN-001",
        "underlying": "AAPL",
        "strike": 185.0,
        "expiry": "2026-01-15",
        "option_type": "call",
        "average_type": "arithmetic",
        "strike_type": "fixed",
        "averaging_start": "2025-01-15",
        "fixing_frequency": "monthly",
    },
}

LOOKBACK_INSTRUMENT = {
    "type": "lookback_option",
    "params": {
        "trade_id": "TEST-LB-001",
        "underlying": "AAPL",
        "expiry": "2026-01-15",
        "option_type": "call",
        "strike_type": "floating",
    },
}

IRS_INSTRUMENT = {
    "type": "irs",
    "params": {
        "trade_id": "TEST-IRS-001",
        "notional": 1000000,
        "currency": "USD",
        "start_date": "2025-01-15",
        "end_date": "2030-01-15",
        "fixed_rate": 0.04,
        "direction": "pay",
        "fixed_leg_frequency": "semiannual",
        "float_leg_frequency": "quarterly",
        "float_index_tenor": "3M",
    },
}

BOND_INSTRUMENT = {
    "type": "bond",
    "params": {
        "trade_id": "TEST-BOND-001",
        "face_value": 100,
        "coupon_rate": 0.05,
        "issue_date": "2024-01-15",
        "maturity_date": "2034-01-15",
        "coupon_frequency": "semiannual",
        "day_count": "ACT/ACT",
        "currency": "USD",
    },
}

FRA_INSTRUMENT = {
    "type": "fra",
    "params": {
        "trade_id": "TEST-FRA-001",
        "notional": 1000000,
        "currency": "USD",
        "start_date": "2025-04-15",
        "end_date": "2025-07-15",
        "fixed_rate": 0.045,
        "direction": "pay",
        "float_index_tenor": "3M",
        "day_count": "ACT/360",
    },
}

CAP_INSTRUMENT = {
    "type": "cap_floor",
    "params": {
        "trade_id": "TEST-CAP-001",
        "notional": 1000000,
        "currency": "USD",
        "start_date": "2025-03-15",
        "end_date": "2030-03-15",
        "strike": 0.05,
        "cap_or_floor": "cap",
        "float_frequency": "quarterly",
        "float_index_tenor": "3M",
        "vol": 0.20,
    },
}

SWAPTION_INSTRUMENT = {
    "type": "swaption",
    "params": {
        "trade_id": "TEST-SWPN-001",
        "notional": 1000000,
        "currency": "USD",
        "expiry_date": "2026-01-15",
        "swap_end": "2031-01-15",
        "strike": 0.04,
        "swaption_type": "payer",
        "fixed_leg_frequency": "semiannual",
        "float_leg_frequency": "quarterly",
        "float_index_tenor": "3M",
        "settlement_type": "physical",
        "vol": 0.20,
    },
}

CDS_INSTRUMENT = {
    "type": "cds",
    "params": {
        "trade_id": "TEST-CDS-001",
        "notional": 10000000,
        "currency": "USD",
        "start_date": "2025-03-20",
        "maturity_date": "2030-03-20",
        "spread": 0.01,
        "direction": "buy",
        "recovery_rate": 0.40,
        "hazard_rate": 0.02,
        "payment_frequency": "quarterly",
    },
}

MARKET_DATA = {
    "pricing_date": "2025-01-15",
    "underlyings": {
        "AAPL": {"spot": 185.0, "vol": 0.25, "div_yield": 0.005}
    },
    "rate": 0.045,
}


ALL_INSTRUMENTS = [
    ("vanilla_option", VANILLA_INSTRUMENT),
    ("barrier_option", BARRIER_INSTRUMENT),
    ("digital_option", DIGITAL_INSTRUMENT),
    ("asian_option",   ASIAN_INSTRUMENT),
    ("lookback_option", LOOKBACK_INSTRUMENT),
]


# ─── Tests ────────────────────────────────────────────────────────

def test_health():
    r = api_client.health()
    assert r.get("status") in ("ok", "healthy"), f"Unexpected status: {r}"
    return r


# === REGISTRY =====================================================

def test_get_instruments():
    r = api_client.get_instruments()
    assert isinstance(r, list), "Expected list"
    assert len(r) > 0, "No instruments registered"
    types = [i["type"] for i in r]
    assert "vanilla_option" in types, f"vanilla_option not in {types}"
    return f"{len(r)} instruments"


def test_get_models():
    r = api_client.get_models()
    assert isinstance(r, list), "Expected list"
    return f"{len(r)} models"


def test_get_engines():
    r = api_client.get_engines()
    assert isinstance(r, list), "Expected list"
    return f"{len(r)} engines"


def test_get_engine_compatibility():
    r = api_client.get_engine_compatibility()
    assert isinstance(r, dict), "Expected dict"
    assert "vanilla_option" in r, "vanilla_option not in compatibility"
    return f"{len(r)} instrument types"


def test_get_scenarios():
    r = api_client.get_scenarios()
    assert isinstance(r, list), "Expected list"
    return f"{len(r)} scenarios"


# === PRICING ======================================================

def test_price_vanilla():
    r = api_client.price_single({
        "instrument": VANILLA_INSTRUMENT,
        "market_data": MARKET_DATA,
        "model": "black_scholes",
        "engine": "analytic",
    })
    assert "npv" in r, f"No npv in response: {r}"
    assert r["npv"] > 0, f"NPV should be positive: {r['npv']}"
    return f"NPV = {r['npv']:.4f}"


def test_price_barrier():
    r = api_client.price_single({
        "instrument": BARRIER_INSTRUMENT,
        "market_data": MARKET_DATA,
        "model": "black_scholes",
        "engine": "analytic",
    })
    assert r["npv"] > 0, f"NPV should be positive: {r['npv']}"
    return f"NPV = {r['npv']:.4f}"


def test_price_digital():
    r = api_client.price_single({
        "instrument": DIGITAL_INSTRUMENT,
        "market_data": MARKET_DATA,
        "model": "black_scholes",
        "engine": "analytic",
    })
    assert r["npv"] > 0
    return f"NPV = {r['npv']:.4f}"


def test_price_asian():
    r = api_client.price_single({
        "instrument": ASIAN_INSTRUMENT,
        "market_data": MARKET_DATA,
        "model": "black_scholes",
        "engine": "monte_carlo",
    })
    assert r["npv"] > 0
    return f"NPV = {r['npv']:.4f}"


def test_price_lookback():
    r = api_client.price_single({
        "instrument": LOOKBACK_INSTRUMENT,
        "market_data": MARKET_DATA,
        "model": "black_scholes",
        "engine": "monte_carlo",
    })
    assert r["npv"] > 0
    return f"NPV = {r['npv']:.4f}"


def test_price_with_engine_params():
    r = api_client.price_single({
        "instrument": VANILLA_INSTRUMENT,
        "market_data": MARKET_DATA,
        "model": "black_scholes",
        "engine": "monte_carlo",
        "engine_params": {"num_paths": 50000},
    })
    assert r["npv"] > 0
    return f"NPV = {r['npv']:.4f} (50K paths)"


def test_price_irs():
    r = api_client.price_single({
        "instrument": IRS_INSTRUMENT,
        "market_data": MARKET_DATA,
        "model": "black_scholes",
        "engine": "analytic",
    })
    assert "npv" in r, f"No npv in response: {r}"
    return f"NPV = {r['npv']:,.2f}"


def test_price_bond():
    r = api_client.price_single({
        "instrument": BOND_INSTRUMENT,
        "market_data": MARKET_DATA,
        "model": "black_scholes",
        "engine": "analytic",
    })
    assert "npv" in r, f"No npv in response: {r}"
    assert r["npv"] > 0, f"Bond NPV should be positive: {r['npv']}"
    return f"NPV = {r['npv']:.4f}"


def test_price_fra():
    r = api_client.price_single({
        "instrument": FRA_INSTRUMENT,
        "market_data": MARKET_DATA,
        "model": "black_scholes",
        "engine": "analytic",
    })
    assert "npv" in r, f"No npv in response: {r}"
    return f"NPV = {r['npv']:,.2f}"


def test_price_cap():
    r = api_client.price_single({
        "instrument": CAP_INSTRUMENT,
        "market_data": MARKET_DATA,
        "model": "black_scholes",
        "engine": "analytic",
    })
    assert "npv" in r, f"No npv in response: {r}"
    assert r["npv"] >= 0, f"Cap NPV should be non-negative: {r['npv']}"
    return f"NPV = {r['npv']:,.2f}"


def test_price_swaption():
    r = api_client.price_single({
        "instrument": SWAPTION_INSTRUMENT,
        "market_data": MARKET_DATA,
        "model": "black_scholes",
        "engine": "analytic",
    })
    assert "npv" in r, f"No npv in response: {r}"
    assert r["npv"] >= 0, f"Swaption NPV should be non-negative: {r['npv']}"
    return f"NPV = {r['npv']:,.2f}"


def test_price_cds():
    r = api_client.price_single({
        "instrument": CDS_INSTRUMENT,
        "market_data": MARKET_DATA,
        "model": "black_scholes",
        "engine": "analytic",
    })
    assert "npv" in r, f"No npv in response: {r}"
    return f"NPV = {r['npv']:,.2f}"


def test_batch_pricing():
    r = api_client.price_batch({
        "instruments": [VANILLA_INSTRUMENT, BARRIER_INSTRUMENT],
        "market_data": MARKET_DATA,
        "model": "black_scholes",
        "engine": "analytic",
    })
    assert "results" in r
    assert len(r["results"]) == 2
    return f"{len(r['results'])} priced"


def test_engine_compare():
    r = api_client.price_compare({
        "instrument": VANILLA_INSTRUMENT,
        "market_data": MARKET_DATA,
        "model": "black_scholes",
    })
    assert "results" in r
    assert "reference_npv" in r
    return f"{len(r['results'])} engines compared"


# === SENSITIVITIES ================================================

def test_greeks():
    r = api_client.compute_greeks({
        "instrument": VANILLA_INSTRUMENT,
        "market_data": MARKET_DATA,
        "model": "black_scholes",
        "engine": "analytic",
        "measures": ["delta", "gamma", "vega", "theta", "rho"],
    })
    assert "greeks" in r
    assert "delta" in r["greeks"]
    delta = r["greeks"]["delta"]
    assert 0 < delta < 1, f"Delta out of range: {delta}"
    return f"delta={delta:.4f}"


def test_spot_ladder():
    r = api_client.run_ladder({
        "instruments": [VANILLA_INSTRUMENT],
        "market_data": MARKET_DATA,
        "model": "black_scholes",
        "engine": "analytic",
        "risk_factor": "spot",
        "bump_type": "relative",
        "bumps": [-0.10, -0.05, 0, 0.05, 0.10],
    })
    assert "results" in r
    assert len(r["results"]) == 5
    return f"{len(r['results'])} bumps"


def test_vol_ladder():
    r = api_client.run_ladder({
        "instruments": [VANILLA_INSTRUMENT],
        "market_data": MARKET_DATA,
        "model": "black_scholes",
        "engine": "analytic",
        "risk_factor": "vol",
        "bump_type": "absolute",
        "bumps": [-0.05, -0.02, 0, 0.02, 0.05],
    })
    assert "results" in r
    return f"{len(r['results'])} bumps"


def test_matrix():
    r = api_client.run_matrix({
        "instruments": [VANILLA_INSTRUMENT],
        "market_data": MARKET_DATA,
        "model": "black_scholes",
        "engine": "analytic",
        "factor_1": "spot",
        "factor_1_bumps": [-0.10, -0.05, 0, 0.05, 0.10],
        "factor_1_bump_type": "relative",
        "factor_2": "vol",
        "factor_2_bumps": [-0.05, 0, 0.05],
        "factor_2_bump_type": "absolute",
    })
    assert "matrix" in r
    return f"{len(r['matrix'])}x{len(r['matrix'][0])} matrix"


# === RISK =========================================================

def test_scenario():
    r = api_client.run_scenario({
        "instruments": [VANILLA_INSTRUMENT],
        "market_data": MARKET_DATA,
        "model": "black_scholes",
        "engine": "analytic",
        "scenario_name": "test_crash",
        "shocks": [
            {"risk_factor": "spot", "shock_type": "relative", "value": -0.20},
            {"risk_factor": "vol", "shock_type": "absolute", "value": 0.10},
        ],
    })
    assert "total_impact" in r
    return f"impact = {r['total_impact']:+.4f}"


def test_stress_test():
    r = api_client.run_stress_test({
        "instruments": [VANILLA_INSTRUMENT],
        "market_data": MARKET_DATA,
        "model": "black_scholes",
        "engine": "analytic",
    })
    assert "results" in r
    assert len(r["results"]) > 0
    return f"{len(r['results'])} scenarios, worst={r.get('worst_scenario', '?')}"


def test_pnl_explain():
    base_market = MARKET_DATA.copy()
    current_market = {
        "pricing_date": "2025-01-16",
        "underlyings": {
            "AAPL": {"spot": 188.0, "vol": 0.26, "div_yield": 0.005}
        },
        "rate": 0.045,
    }
    r = api_client.run_pnl_explain({
        "instruments": [VANILLA_INSTRUMENT],
        "base_market": base_market,
        "current_market": current_market,
        "model": "black_scholes",
        "engine": "analytic",
    })
    assert "total_actual_pnl" in r
    return f"actual={r['total_actual_pnl']:+.4f}, explained={r['total_explained']:+.4f}"


def test_var_parametric():
    r = api_client.compute_var({
        "instruments": [VANILLA_INSTRUMENT],
        "market_data": MARKET_DATA,
        "model": "black_scholes",
        "engine": "analytic",
        "method": "parametric",
        "confidence": 0.99,
        "horizon_days": 1,
        "annual_vol": 0.25,
    })
    assert "var" in r
    assert r["var"] > 0
    return f"VaR={r['var']:.4f}, CVaR={r['cvar']:.4f}"


# === CALIBRATION ==================================================

def test_implied_vol():
    r = api_client.compute_implied_vol({
        "market_price": 12.50,
        "spot": 185.0,
        "strike": 185.0,
        "T": 1.0,
        "rate": 0.045,
        "div_yield": 0.005,
        "is_call": True,
        "method": "newton",
    })
    assert "implied_vol" in r
    assert r["converged"] is True
    iv = r["implied_vol"]
    assert 0.05 < iv < 1.0, f"IV out of range: {iv}"
    return f"IV = {iv*100:.2f}%"


# === MARKET DATA ==================================================

def test_yield_curve_query():
    r = api_client.query_yield_curve({
        "market_data": MARKET_DATA,
        "tenors": [0.25, 0.5, 1.0, 2.0, 5.0, 10.0],
    })
    assert "results" in r
    assert len(r["results"]) == 6
    return f"{len(r['results'])} tenors"


def test_vol_surface_build():
    r = api_client.build_vol_surface({
        "pricing_date": "2025-01-15",
        "underlying": "SPX",
        "spot": 5800.0,
        "rate": 0.045,
        "div_yield": 0.015,
        "strikes": [5200, 5400, 5600, 5800, 6000, 6200],
        "expiry_dates": ["2025-04-15", "2025-07-15", "2025-10-15"],
        "vol_matrix": [
            [0.24, 0.21, 0.19, 0.18, 0.19, 0.21],
            [0.23, 0.20, 0.18, 0.17, 0.18, 0.20],
            [0.22, 0.19, 0.17, 0.16, 0.17, 0.19],
        ],
        "method": "svi",
    })
    assert r.get("num_expiries") == 3
    return f"{r['num_expiries']}x{r['num_strikes']} surface"


# === FRONTEND-SPECIFIC FLOWS ======================================

def test_pricer_flow():
    """Simulates the full Pricer page flow."""
    # 1. Get instruments
    instruments = api_client.get_instruments()
    assert len(instruments) > 0

    # 2. Get compatibility
    compat = api_client.get_engine_compatibility()
    vanilla_engines = compat.get("vanilla_option", [])
    assert "analytic" in vanilla_engines

    # 3. Price
    r = api_client.price_single({
        "instrument": VANILLA_INSTRUMENT,
        "market_data": MARKET_DATA,
        "model": "black_scholes",
        "engine": "analytic",
    })
    assert r["npv"] > 0

    # 4. Greeks
    g = api_client.compute_greeks({
        "instrument": VANILLA_INSTRUMENT,
        "market_data": MARKET_DATA,
        "model": "black_scholes",
        "engine": "analytic",
        "measures": ["delta", "gamma", "vega", "theta", "rho"],
    })
    assert "delta" in g["greeks"]

    return f"Full pricer flow OK (NPV={r['npv']:.4f}, delta={g['greeks']['delta']:.4f})"


def test_risk_lab_flow():
    """Simulates the Risk Lab page flow."""
    # Spot ladder
    ladder = api_client.run_ladder({
        "instruments": [VANILLA_INSTRUMENT],
        "market_data": MARKET_DATA,
        "model": "black_scholes",
        "engine": "analytic",
        "risk_factor": "spot",
        "bump_type": "relative",
        "bumps": [-0.10, -0.05, 0, 0.05, 0.10],
    })
    assert len(ladder["results"]) == 5

    # Stress test
    stress = api_client.run_stress_test({
        "instruments": [VANILLA_INSTRUMENT],
        "market_data": MARKET_DATA,
        "model": "black_scholes",
        "engine": "analytic",
    })
    assert len(stress["results"]) > 0

    return f"Risk lab flow OK ({len(ladder['results'])} bumps, {len(stress['results'])} scenarios)"


def test_portfolio_flow():
    """Simulates portfolio valuation (client-side aggregation)."""
    positions = [
        {"instrument": VANILLA_INSTRUMENT, "qty": 100, "direction": "buy"},
        {"instrument": BARRIER_INSTRUMENT, "qty": 50, "direction": "sell"},
    ]

    total_npv = 0
    for pos in positions:
        r = api_client.price_single({
            "instrument": pos["instrument"],
            "market_data": MARKET_DATA,
            "model": "black_scholes",
            "engine": "analytic",
        })
        sign = 1 if pos["direction"] == "buy" else -1
        total_npv += r["npv"] * pos["qty"] * sign

    return f"Portfolio NPV = ${total_npv:,.2f} ({len(positions)} positions)"


# ─── Runner ───────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 60)
    print("  QuantPricer Integration Test Suite")
    print("  Backend: http://127.0.0.1:8000")
    print("=" * 60)

    # Health check first
    print("\n─── HEALTH ──────────────────────────────────────")
    run_test("Health check", test_health)

    if results[-1].status == "FAIL":
        print("\n  ✗ Backend not reachable. Start it with:")
        print("    uvicorn api.app:app --reload --port 8000\n")
        _print_summary()
        return

    # Registry
    print("\n─── REGISTRY ────────────────────────────────────")
    run_test("GET /registry/instruments", test_get_instruments)
    run_test("GET /registry/models", test_get_models)
    run_test("GET /registry/engines", test_get_engines)
    run_test("GET /registry/engines/compatibility", test_get_engine_compatibility)
    run_test("GET /registry/scenarios", test_get_scenarios)

    # Pricing — each instrument type
    print("\n─── PRICING ─────────────────────────────────────")
    run_test("POST /pricing/single (vanilla)", test_price_vanilla)
    run_test("POST /pricing/single (barrier)", test_price_barrier)
    run_test("POST /pricing/single (digital)", test_price_digital)
    run_test("POST /pricing/single (asian MC)", test_price_asian)
    run_test("POST /pricing/single (lookback MC)", test_price_lookback)
    run_test("POST /pricing/single (MC 50K paths)", test_price_with_engine_params)
    run_test("POST /pricing/single (IRS)", test_price_irs)
    run_test("POST /pricing/single (Bond)", test_price_bond)
    run_test("POST /pricing/single (FRA)", test_price_fra)
    run_test("POST /pricing/single (Cap)", test_price_cap)
    run_test("POST /pricing/single (Swaption)", test_price_swaption)
    run_test("POST /pricing/single (CDS)", test_price_cds)
    run_test("POST /pricing/batch (2 instruments)", test_batch_pricing)
    run_test("POST /pricing/compare (all engines)", test_engine_compare)

    # Sensitivities
    print("\n─── SENSITIVITIES ───────────────────────────────")
    run_test("POST /sensitivities/greeks", test_greeks)
    run_test("POST /sensitivities/ladder (spot)", test_spot_ladder)
    run_test("POST /sensitivities/ladder (vol)", test_vol_ladder)
    run_test("POST /sensitivities/matrix (spot×vol)", test_matrix)

    # Risk
    print("\n─── RISK ────────────────────────────────────────")
    run_test("POST /risk/scenario (custom)", test_scenario)
    run_test("POST /risk/stress-test (all)", test_stress_test)
    run_test("POST /risk/pnl-explain", test_pnl_explain)
    run_test("POST /risk/var (parametric)", test_var_parametric)

    # Calibration
    print("\n─── CALIBRATION ─────────────────────────────────")
    run_test("POST /calibration/implied-vol", test_implied_vol)

    # Market Data
    print("\n─── MARKET DATA ─────────────────────────────────")
    run_test("POST /market/yield-curve/query", test_yield_curve_query)
    run_test("POST /market/vol-surface/build (SVI)", test_vol_surface_build)

    # End-to-end flows
    print("\n─── E2E FLOWS ───────────────────────────────────")
    run_test("Pricer page flow", test_pricer_flow)
    run_test("Risk Lab page flow", test_risk_lab_flow)
    run_test("Portfolio flow (client-side)", test_portfolio_flow)

    _print_summary()


def _print_summary():
    print("\n" + "=" * 60)
    print("  RESULTS SUMMARY")
    print("=" * 60)

    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    skipped = sum(1 for r in results if r.status == "SKIP")
    total = len(results)

    print(f"\n  Total:   {total}")
    print(f"  Passed:  {passed}  ✓")
    print(f"  Failed:  {failed}  ✗")
    if skipped:
        print(f"  Skipped: {skipped}")

    if failed:
        print(f"\n─── FAILURES ────────────────────────────────────")
        for r in results:
            if r.status == "FAIL":
                print(f"\n  ✗ {r.name}")
                print(f"    {r.detail[:200]}")

    total_time = sum(r.elapsed_ms for r in results)
    print(f"\n  Total time: {total_time:.0f}ms")
    print(f"\n  Score: {passed}/{total} ({passed/total*100:.0f}%)")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
