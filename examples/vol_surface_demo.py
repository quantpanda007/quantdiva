"""
Vol Surface Demo — build, calibrate, and price with a proper smile.

Demonstrates:
1. Build market vol surface from strike × expiry grid
2. Calibrate SVI per expiry
3. Extract local vol (Dupire)
4. Price vanilla options using the smile (not flat vol)
5. Arbitrage diagnostics

Usage:
    python examples/vol_surface_demo.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np

# Ensure project root on path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

import registry.bootstrap  # noqa: F401
import QuantLib as ql

from core.enums.definitions import OptionType, ExerciseType
from core.types.value_objects import PricingDate
from core.interfaces.base import MarketEnvironment
from instruments.equity.vanilla_option import VanillaOption
from services.pricers.pricing_service import PricingService
from market.curves.yield_curve import build_flat_curve
from market.volatility.vol_surface_ext import (
    SVIVolSurface,
    LocalVolSurface,
    VolSurfaceManager,
    calibrate_svi,
    check_calendar_arbitrage,
    check_butterfly_arbitrage,
)


def main():
    # ===================================================================
    # 1. Market data setup
    # ===================================================================
    pricing_date = PricingDate(date(2025, 1, 15))
    ql_date = pricing_date.to_ql()
    ql.Settings.instance().evaluationDate = ql_date

    spot = 100.0
    rate = 0.05
    div_yield = 0.02
    underlying = "SPX"

    # Strike × Expiry vol matrix (realistic skew)
    strikes = [80.0, 85.0, 90.0, 95.0, 100.0, 105.0, 110.0, 115.0, 120.0]
    expiry_dates = [
        date(2025, 4, 15),   # 3M
        date(2025, 7, 15),   # 6M
        date(2026, 1, 15),   # 1Y
        date(2027, 1, 15),   # 2Y
    ]

    # Implied vols with typical equity skew (put skew, call wing)
    vol_matrix = [
        # 3M:  deep skew
        [0.32, 0.29, 0.26, 0.23, 0.21, 0.20, 0.19, 0.19, 0.20],
        # 6M:  moderate skew
        [0.30, 0.27, 0.25, 0.23, 0.21, 0.20, 0.19, 0.19, 0.20],
        # 1Y:  flatter
        [0.28, 0.26, 0.24, 0.22, 0.21, 0.20, 0.20, 0.20, 0.21],
        # 2Y:  flattest
        [0.26, 0.25, 0.23, 0.22, 0.21, 0.21, 0.21, 0.21, 0.22],
    ]

    # ===================================================================
    # 2. Calibrate SVI surface
    # ===================================================================
    print("=" * 70)
    print("SVI CALIBRATION")
    print("=" * 70)

    svi_surface = SVIVolSurface.from_market_quotes(
        pricing_date=pricing_date,
        strikes=strikes,
        expiry_dates=expiry_dates,
        vol_matrix=vol_matrix,
        spot=spot,
        rate=rate,
        div_yield=div_yield,
    )

    # Print fit report
    print(f"\n{'T':>6} {'Forward':>8} {'a':>8} {'b':>8} {'ρ':>8} {'m':>8} {'σ':>8} {'RMSE':>10} {'ArbFree':>8}")
    print("-" * 70)
    for r in svi_surface.fit_report():
        print(
            f"{r['T']:>6.3f} {r['forward']:>8.2f} "
            f"{r['a']:>8.4f} {r['b']:>8.4f} {r['rho']:>8.4f} "
            f"{r['m']:>8.4f} {r['sigma']:>8.4f} "
            f"{r['rmse']:>10.6f} {'✓' if r['arbitrage_free'] else '✗':>8}"
        )

    # ===================================================================
    # 3. Compare SVI smile vs market at 6M
    # ===================================================================
    print(f"\n{'='*70}")
    print("SVI FIT: 6M SMILE")
    print(f"{'='*70}")

    slice_6m = svi_surface.slices[1]  # 6M
    print(f"\n{'Strike':>8} {'Market':>8} {'SVI':>8} {'Error(bps)':>10}")
    print("-" * 40)
    for i, K in enumerate(strikes):
        mkt_vol = vol_matrix[1][i]
        svi_vol = slice_6m.implied_vol(K)
        err_bps = (svi_vol - mkt_vol) * 10000
        print(f"{K:>8.1f} {mkt_vol:>8.4f} {svi_vol:>8.4f} {err_bps:>10.2f}")

    # ===================================================================
    # 4. Arbitrage checks
    # ===================================================================
    print(f"\n{'='*70}")
    print("ARBITRAGE DIAGNOSTICS")
    print(f"{'='*70}")

    strike_grid = np.linspace(75, 125, 51)

    cal_violations = check_calendar_arbitrage(svi_surface, strike_grid)
    print(f"\nCalendar arbitrage violations: {len(cal_violations)}")
    for v in cal_violations[:5]:
        print(f"  K={v['strike']:.1f}, T={v['T']:.3f}: w={v['total_var']:.6f} < prev={v['prev_total_var']:.6f}")

    for s in svi_surface.slices:
        bfly = check_butterfly_arbitrage(s, strike_grid)
        print(f"Butterfly arbitrage at T={s.T:.3f}: {len(bfly)} violations")

    # ===================================================================
    # 5. Extract local vol
    # ===================================================================
    print(f"\n{'='*70}")
    print("LOCAL VOL (DUPIRE)")
    print(f"{'='*70}")

    risk_free = build_flat_curve(pricing_date, rate)
    div_handle = ql.YieldTermStructureHandle(
        ql.FlatForward(ql_date, div_yield, ql.Actual365Fixed())
    )

    implied_handle = svi_surface.to_ql_surface()
    local_vol = LocalVolSurface.from_implied_surface(
        pricing_date=pricing_date,
        implied_vol_handle=implied_handle,
        spot=spot,
        risk_free_handle=risk_free,
        dividend_handle=div_handle,
    )

    print(f"\n{'Strike':>8}", end="")
    T_points = [0.25, 0.50, 1.00]
    for T in T_points:
        print(f"  {'T=' + str(T):>8}", end="")
    print()
    print("-" * 40)

    for K in [85, 90, 95, 100, 105, 110, 115]:
        print(f"{K:>8}", end="")
        for T in T_points:
            lv = local_vol.local_vol(T, float(K))
            print(f"  {lv:>8.4f}", end="")
        print()

    # ===================================================================
    # 6. Price with smile vs flat vol
    # ===================================================================
    print(f"\n{'='*70}")
    print("PRICING: SMILE vs FLAT VOL")
    print(f"{'='*70}")

    ps = PricingService()

    # Build market env with SVI surface
    vol_mgr = VolSurfaceManager(pricing_date)
    vol_mgr.add_svi_surface(underlying, svi_surface)

    smile_env = MarketEnvironment(
        pricing_date=pricing_date,
        discount_curves={"USD": risk_free, underlying: risk_free},
        forecast_curves={"USD": risk_free},
        vol_surfaces={underlying: vol_mgr.get_ql_handle(underlying)},
        spot_prices={underlying: spot},
        dividend_curves={f"{underlying}_div": div_handle},
    )

    # Build market env with flat vol (ATM = 21%)
    flat_vol = ql.BlackVolTermStructureHandle(
        ql.BlackConstantVol(ql_date, ql.NullCalendar(), 0.21, ql.Actual365Fixed())
    )
    flat_env = MarketEnvironment(
        pricing_date=pricing_date,
        discount_curves={"USD": risk_free, underlying: risk_free},
        forecast_curves={"USD": risk_free},
        vol_surfaces={underlying: flat_vol},
        spot_prices={underlying: spot},
        dividend_curves={f"{underlying}_div": div_handle},
    )

    print(f"\n{'Strike':>8} {'Type':>6} {'Smile NPV':>12} {'Flat NPV':>12} {'Diff':>10} {'Diff%':>8}")
    print("-" * 60)

    for K in [85, 90, 95, 100, 105, 110, 115]:
        for opt_type in [OptionType.CALL, OptionType.PUT]:
            option = VanillaOption(
                _trade_id=f"SMILE-{K}-{opt_type.value}",
                underlying=underlying,
                strike=float(K),
                expiry=date(2025, 7, 15),
                option_type=opt_type,
                exercise_type=ExerciseType.EUROPEAN,
                _currency="USD",
            )

            try:
                smile_npv = ps.price(option, smile_env, model_type="black_scholes", engine_type="analytic").npv
                flat_npv = ps.price(option, flat_env, model_type="black_scholes", engine_type="analytic").npv
                diff = smile_npv - flat_npv
                diff_pct = diff / flat_npv * 100 if flat_npv != 0 else 0

                print(
                    f"{K:>8.0f} {opt_type.value:>6} "
                    f"{smile_npv:>12.4f} {flat_npv:>12.4f} "
                    f"{diff:>10.4f} {diff_pct:>7.1f}%"
                )
            except Exception as e:
                print(f"{K:>8.0f} {opt_type.value:>6} ERROR: {e}")

    print(f"\n{'='*70}")
    print("Key insight: OTM puts are MORE expensive with skew (risk premium)")
    print("ATM options are similar. OTM calls are CHEAPER with skew.")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()