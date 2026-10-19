"""TC1 Bloomberg reconciliation diagnostic (ISOLATED; no production changes).

Uses Optima's own production builders (build_fixed_leg, build_floating_leg,
translate_leg_schedule, assemble_quantlib_irs, attach_discounting_engine).
Only the curve handles and (for cutoff variants) the QuantLib lockoutDays
argument are varied. All valuation is QuantLib instrument/engine output.
"""
from __future__ import annotations

import json
import math
import sys
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import QuantLib as ql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.enums.definitions import DayCountConvention, Frequency  # noqa: E402
from core.types.value_objects import Money  # noqa: E402
from instruments.rates.irs import (  # noqa: E402
    IRSLegKind, IRSLegTerms, ObservationConventions, build_fixed_leg,
    build_floating_leg, translate_leg_schedule,
)
from instruments.rates.irs.schedule import CouponPeriod, LegSchedule  # noqa: E402
from instruments.rates.irs.floating_leg import QuantLibFloatingLeg  # noqa: E402
from instruments.rates.irs.instrument import assemble_quantlib_irs  # noqa: E402
from instruments.rates.irs.engine import attach_discounting_engine  # noqa: E402
from market.curves.irs_market_data import (  # noqa: E402
    DiscountCurveMarketData, DiscountFactorObservation, QuantLibDiscountCurve,
    SimpleForwardCurveMarketData, SimpleForwardObservation, build_discount_curve,
)
from market.curves.irs_provisional_projection import (  # noqa: E402
    build_provisional_projection_curve,
)

REF = date(2026, 3, 31)
QREF = ql.Date(31, 3, 2026)
ql.Settings.instance().evaluationDate = QREF

# ---- Inputs (read-only) ---------------------------------------------------
MD = json.loads((ROOT / "market_data/2026-03-31/USD/market_data.json").read_text())
OBS = MD["observations"]
# Zero Rate column: supplied by the user in chat (not in the repo fixture).
ZERO = [3.70182, 3.70182, 3.70094, 3.70544, 3.7097, 3.71046, 3.70721, 3.70252,
        3.69965, 3.69836, 3.69651, 3.69401, 3.69122, 3.68706, 3.68376, 3.65444,
        3.60422, 3.56121, 3.5692, 3.60763]
TENORS = ["1W", "2W", "3W"] + [f"{n}M" for n in range(1, 13)] + ["18M", "2Y", "3Y", "4Y", "5Y"]

BBG = {
    "cpn": (3.78546, 3.64025), "pay": (20174.40, 4984.11), "df": (0.958306, 0.941092),
    "flt": 24023.74, "fix": -31978.74, "npv": -7955.00,
}
PERIODS = [(date(2026, 5, 31), date(2027, 5, 28), 530000),
           (date(2027, 5, 28), date(2027, 11, 30), 265000)]

SOFR_CAL = ql.UnitedStates(ql.UnitedStates.SOFR)
SPOT = SOFR_CAL.advance(QREF, 2, ql.Days)
PILLARS = [SOFR_CAL.advance(SPOT, ql.Period(t), ql.ModifiedFollowing, False) for t in TENORS]


# ---- Curves ----------------------------------------------------------------
def handle(ts):
    ts.enableExtrapolation()
    return ql.YieldTermStructureHandle(ts)


def zero_curve(zeros=None, interp="linear"):
    z = [x / 100 for x in (zeros or ZERO)]
    dates = [QREF] + PILLARS
    zz = [z[0]] + z  # flat-extrapolate first pillar back to T0
    dc = ql.Actual365Fixed()
    if interp == "linear":
        return handle(ql.ZeroCurve(dates, zz, dc, SOFR_CAL, ql.Linear(), ql.Continuous))
    if interp == "cubic":
        return handle(ql.CubicZeroCurve(dates, zz, dc))
    if interp == "monocubic":
        return handle(ql.MonotonicCubicZeroCurve(dates, zz, dc))
    raise ValueError(interp)


def df_curve_reconstructed_dates():
    dates = [QREF] + PILLARS
    dfs = [1.0] + [o["discount_factor"] for o in OBS]
    return handle(ql.DiscountCurve(dates, dfs, ql.Actual365Fixed()))  # LogLinear DF


def zero_curve_from_dfs():
    """Zero rates implied by the 6dp DF column (precision alternative)."""
    z = [-math.log(o["discount_factor"]) / ((p - QREF) / 365.0) * 100 for o, p in zip(OBS, PILLARS)]
    return zero_curve(z), z


def production_curves():
    dmd = DiscountCurveMarketData(REF, "USD", tuple(
        DiscountFactorObservation(date.fromisoformat(o["date"]), o["discount_factor"]) for o in OBS))
    disc = build_discount_curve(dmd, day_counter=ql.Actual360())
    pmd = SimpleForwardCurveMarketData(REF, "USD", "SOFR", tuple(
        SimpleForwardObservation(date.fromisoformat(o["date"]), o["market_rate"]) for o in OBS))
    proj = build_provisional_projection_curve(pmd, day_counter=ql.Actual360(),
                                              expected_currency="USD", expected_benchmark="SOFR")
    return disc.handle, proj.handle


# ---- Trade (Optima domain objects, mirroring cases/TC1.json) ---------------
def leg_schedule():
    periods = tuple(CouponPeriod(s, e, e, Money(Decimal(n), "USD")) for s, e, n in PERIODS)
    return translate_leg_schedule(LegSchedule(periods=periods, principal_repayments=()))


def terms(lookback):
    usd = Money(Decimal(530000), "USD")
    fixed = IRSLegTerms(kind=IRSLegKind.FIXED, payment_frequency=Frequency.ANNUAL,
                        day_count=DayCountConvention.ACT_360, original_notional=usd,
                        fixed_coupon_rate="0.05")
    flt = IRSLegTerms(kind=IRSLegKind.FLOATING, payment_frequency=Frequency.ANNUAL,
                      day_count=DayCountConvention.ACT_360, original_notional=usd,
                      benchmark="SOFRRATE", benchmark_tenor="1D", floating_spread_rate="0.001",
                      floating_leverage="1.0", reset_frequency=Frequency.DAILY,
                      observation=ObservationConventions(lookback_days=lookback, cutoff_days=1,
                                                         reset_timing="In Arrears",
                                                         compounding="ExcludeSprd",
                                                         lookback_type="Lookback"))
    return fixed, flt


def floating_leg(flt_terms, sched, fwd, lockout, compound_spread_daily=False):
    """Production builder; for lockout/spread variants, the identical
    ql.OvernightLeg call is repeated with only that argument changed."""
    prod = build_floating_leg(flt_terms, sched, "USD", forwarding_curve=fwd)
    if lockout == 0 and not compound_spread_daily:
        return prod
    p = sched.periods
    leg = ql.OvernightLeg(
        ql.DoubleVector([float(x.notional.amount) for x in p]), sched.quantlib_schedule,
        prod.index, ql.Actual360(), ql.Unadjusted,
        gearings=ql.DoubleVector([1.0] * len(p)), spreads=ql.DoubleVector([0.001] * len(p)),
        telescopicValueDates=False, averagingMethod=ql.RateAveraging.Compound,
        paymentCalendar=ql.NullCalendar(), paymentLag=0,
        lookbackDays=prod.observation_settings.lookback_days, lockoutDays=lockout,
        applyObservationShift=False, compoundSpreadDaily=compound_spread_daily,
        inArrears=True,
        paymentDates=ql.DateVector([ql.Date(x.payment_date.day, x.payment_date.month,
                                            x.payment_date.year) for x in p]))
    cps = tuple(ql.as_overnight_indexed_coupon(c) for c in leg)
    return replace(prod, quantlib_leg=leg, coupons=cps)


def price(name, disc, fwd, lookback=0, lockout=1, csd=False):
    sched = leg_schedule()
    fx_terms, fl_terms = terms(lookback)
    fx = build_fixed_leg(fx_terms, sched)
    fl = floating_leg(fl_terms, sched, fwd, lockout, csd)
    inst = assemble_quantlib_irs(fx, fl)
    attach_discounting_engine(inst, QuantLibDiscountCurve(None, disc.currentLink(), disc))
    sw = inst.quantlib_instrument
    r = {"name": name, "cpn": [], "pay": [], "df": [],
         "fix": sw.legNPV(0), "flt": sw.legNPV(1), "npv": sw.NPV(), "obs": []}
    for c in fl.coupons:
        r["cpn"].append(c.rate() * 100)
        r["pay"].append(c.amount())
        r["df"].append(disc.discount(c.date()))
        fd, vd = c.fixingDates(), c.valueDates()
        r["obs"].append((len(fd), fd[0].ISO(), vd[0].ISO(), fd[-1].ISO(), vd[-1].ISO()))
    return r


def show(r):
    b = BBG
    print(f"\n### {r['name']}")
    print("| Metric | P1 | P2 | BBG P1 | BBG P2 | Diff P1 | Diff P2 |")
    print("|---|---:|---:|---:|---:|---:|---:|")
    print(f"| Equiv coupon % | {r['cpn'][0]:.6f} | {r['cpn'][1]:.6f} | {b['cpn'][0]} | {b['cpn'][1]} | "
          f"{(r['cpn'][0]-b['cpn'][0])*100:+.3f}bp | {(r['cpn'][1]-b['cpn'][1])*100:+.3f}bp |")
    print(f"| Float payment | {r['pay'][0]:.2f} | {r['pay'][1]:.2f} | {b['pay'][0]} | {b['pay'][1]} | "
          f"{r['pay'][0]-b['pay'][0]:+.2f} | {r['pay'][1]-b['pay'][1]:+.2f} |")
    print(f"| Payment DF | {r['df'][0]:.7f} | {r['df'][1]:.7f} | {b['df'][0]} | {b['df'][1]} | "
          f"{r['df'][0]-b['df'][0]:+.1e} | {r['df'][1]-b['df'][1]:+.1e} |")
    print(f"| Float PV / Fixed PV / NPV | {r['flt']:.2f} | {r['fix']:.2f} | NPV {r['npv']:.2f} | "
          f"BBG {b['flt']} / {b['fix']} / {b['npv']} | "
          f"d {r['flt']-b['flt']:+.2f} / {r['fix']-b['fix']:+.2f} | dNPV {r['npv']-b['npv']:+.2f} |")
    for i, o in enumerate(r["obs"], 1):
        print(f"  obs P{i}: n_fix={o[0]} first fix {o[1]} (value {o[2]}) last fix {o[3]} (value {o[4]})")


if __name__ == "__main__":
    print(f"QuantLib {ql.__version__}; spot {SPOT.ISO()}")
    pd_disc, pd_proj = production_curves()
    zc = zero_curve()
    rows = [
        price("V0 Production as-is: listed-date DF curve (LogLinear, ACT/360) + provisional projection; "
              "fixture lookback=1, lockout=0", pd_disc, pd_proj, lookback=1, lockout=0),
        price("V1 Reconstructed zero curve (single curve); fixture lookback=1, lockout=0", zc, zc, 1, 0),
        price("V2 Reconstructed curve; lookback=0 (Bloomberg source), lockout=0", zc, zc, 0, 0),
        price("V3 Reconstructed curve; lookback=0, lockout=1 (Bloomberg source conventions)", zc, zc, 0, 1),
        price("V4 = V3 but compoundSpreadDaily=True (tests ExcludeSprd)", zc, zc, 0, 1, csd=True),
        price("V5 = V3, cubic zero interpolation", zero_curve(interp="cubic"), zero_curve(interp="cubic")),
        price("V6 = V3, monotonic-cubic zero interpolation", zero_curve(interp="monocubic"),
              zero_curve(interp="monocubic")),
        price("V7 = V3, reconstructed dates but LogLinear on supplied DFs", df_curve_reconstructed_dates(),
              df_curve_reconstructed_dates()),
    ]
    zdf, zimpl = zero_curve_from_dfs()
    rows.append(price("V8 = V3, zero rates implied from 6dp DF column (precision alternative)", zdf, zdf))
    # rounding envelope on the two pillars bracketing 30-Nov-2027 (18M, 2Y): +/-0.5e-5 %
    for s18, s2y in [(+1, +1), (-1, -1), (+1, -1), (-1, +1)]:
        z = list(ZERO); z[15] += s18 * 0.5e-5; z[16] += s2y * 0.5e-5
        h = zero_curve(z)
        rows.append(price(f"V9 rounding envelope 18M{'+' if s18>0 else '-'} 2Y{'+' if s2y>0 else '-'} 0.5e-5%", h, h))
    # split coupon vs discount effects: projection on V3 curve, discount on a curve forced through BBG DFs
    for r in rows:
        show(r)

    # ---- decomposition (arithmetic on QuantLib outputs only) ----
    v3 = rows[3]
    print("\n### Decomposition of V3 residual (floating leg)")
    for i in range(2):
        coupon_eff = (v3["pay"][i] - BBG["pay"][i]) * BBG["df"][i]
        disc_eff = v3["pay"][i] * (v3["df"][i] - BBG["df"][i])
        print(f"P{i+1}: payment effect x BBG DF = {coupon_eff:+.3f}; DF effect x payment = {disc_eff:+.3f}")
    fixed_pays = [530000 * 0.05 * 362 / 360, 265000 * 0.05 * 186 / 360]
    print("Fixed leg DF effect:", ["%+.3f" % (-fixed_pays[i] * (v3['df'][i] - BBG['df'][i])) for i in range(2)])

    # ---- Bloomberg internal consistency ----
    print("\n### Bloomberg internal consistency")
    for i, (s, e, n) in enumerate(PERIODS):
        tau = (e - s).days / 360
        print(f"P{i+1}: N*cpn*tau = {n*BBG['cpn'][i]/100*tau:.4f} vs payment {BBG['pay'][i]}; "
              f"pay*DF = {BBG['pay'][i]*BBG['df'][i]:.4f}")
    ratio_cpn = (BBG["df"][0] / BBG["df"][1] - 1) / (186 / 360) * 100 + 0.10
    print(f"P2 coupon implied by BBG's own payment DFs (telescoped, no cutoff): {ratio_cpn:.5f}% vs 3.64025%")
    # implied projection DF(30-Nov-27) from BBG coupon, using V3's ratio of exact to telescoped
    v3_tele = (zc.discount(ql.Date(28, 5, 2027)) / zc.discount(ql.Date(30, 11, 2027)) - 1) / (186 / 360) * 100 + 0.1
    cutoff_adj = v3["cpn"][1] - v3_tele
    g = 1 + (BBG["cpn"][1] - 0.1 - cutoff_adj) / 100 * 186 / 360
    print(f"V3 cutoff/compounding adj vs telescoped: {cutoff_adj*100:+.4f}bp")
    print(f"Projection DF(30-Nov-27) implied by BBG P2 coupon, given DF(28-May-27)=0.958306: {0.958306/g:.7f}")
    t = (ql.Date(30, 11, 2027) - QREF) / 365
    print(f"Zero at 30-Nov-27: V3 linear {-math.log(zc.discount(ql.Date(30,11,2027)))/t*100:.5f}% ; "
          f"implied by BBG DF 0.941092: {-math.log(0.941092)/t*100:.5f}%")
    print("Pillars bracketing 30-Nov-27:", PILLARS[15].ISO(), PILLARS[16].ISO())
