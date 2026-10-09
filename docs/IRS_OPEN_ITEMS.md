# Fresh IRS: Open Items

Register of unresolved items for the fresh IRS implementation. Each item lists
what is known (observed), what has been done, what is still missing, and where it
is monitored. Items here are **not** resolved by tuning, hardcoded adjustments, or
editing recorded baselines.

Last updated: 09-Oct-2026 · QuantLib 1.43

| ID | Item | Status | Monitored by |
|---|---|---|---|
| OI-1 | TC1 Period 2 / 30-Nov-2027 discount factor vs Bloomberg (also TC3 Period 3) | Open: awaiting Bloomberg curve-490 data | `test_tc1_bloomberg_reconciliation.py`, `test_tc3_pricing_service_e2e.py` |
| OI-2 | Bloomberg rate cutoff vs QuantLib `lockoutDays` | Open: mapping not confirmed | `test_tc1_bloomberg_reconciliation.py::test_baseline_conventions_are_the_recorded_ones` |
| OI-3 | TC1 lookback: case fixture 1 vs Bloomberg source 0 | Open: fixture not changed | `test_tc1_period1_regression.py::test_lookback_is_taken_from_bloomberg_source` |
| OI-4 | Legacy SOFR path (`interest_rate_swap.py`, `yield_curve.py`) | Excluded, uncommitted experimental work | not part of the fresh IRS suite |
| OI-5 | Curve market-data source, tenor mapping, request-level curve input | Partly done: service path wired; curve data still from the test fixture | `test_irs_zero_curve.py`, `test_tc1_pricing_service_e2e.py`, `test_tc3_pricing_service_e2e.py` |
| OI-6 | Bloomberg-derived data and the public GitHub remote | Decision deferred: keep all commits local | — |
| OI-7 | TC3 Period 4 / 28-Apr-2028 discount factor vs Bloomberg | Open: awaiting Bloomberg curve-490 data (with OI-1) | `test_tc3_pricing_service_e2e.py` |
| OI-8 | Contractual maturity vs adjusted accrual dates; calendar mapping | Implemented with provisional convention and FD-only calendar | `test_tc1_pricing_service_e2e.py`, `test_tc3_pricing_service_e2e.py` |
| OI-9 | TC3 Bloomberg `leg_*_market` NPVs differ from the cashflow-leg NPVs | Open: unexplained, not used as references | `test_tc3_pricing_service_e2e.py` |

---

## OI-1: 30-Nov-2027 discount factor (TC1 Period 2)

**Observed (Bloomberg, as displayed):** payment DF 0.941092 at 30-Nov-2027; Period 2
equivalent coupon 3.64025%; floating-leg NPV 24,023.74; total NPV −7,955.00.

**Optima (recorded baseline):** DF 0.9410946; Period 2 coupon 3.639708%; floating-leg
NPV 24,023.04; total NPV −7,955.73.

| Metric | Optima − Bloomberg |
|---|---:|
| 30-Nov-2027 DF | +2.6e-6 |
| Zero rate at 30-Nov-2027 | −0.016 bp |
| Period 2 coupon | −0.054 bp |
| Period 2 payment | −$0.74 |
| Floating-leg NPV | **−$0.70** |
| Fixed-leg NPV | −$0.02 |
| Total NPV | −$0.73 |

**Established:**
- Period 1 reconciles within Bloomberg display precision, and so do the
  28-May-2027 DF and the Period 1 start DF implied by the coupon.
- Bloomberg's own Period 2 coupon and 30-Nov DF are mutually consistent
  (coupon-implied DF 0.9410922).
- The floating-leg gap comes through the Period 2 coupon (projection); the
  discounting effect is under $0.02.
- Ruled out: input rounding (effect ≤ 1e-7 in DF), and replacing the
  interpolation everywhere (log-linear DF, cubic and monotone-cubic all break
  the 28-May-2027 check).
- The gap is about 5× the display-rounding band, so it is real but small.
- TC3 Period 3 has the same dates (28-May-2027 → 30-Nov-2027) and the same
  result: Bloomberg DF 0.941092, Optima DF +2.56e-6, coupon −0.054 bp (−$1.10 on
  TC3's 395,000 notional). The compounded SOFR is identical to TC1 Period 2 once
  the spreads (70 bp vs 10 bp) are removed, so this is one curve difference seen
  in two trades.

**Hypotheses (unconfirmed):**
- Bloomberg curve members between 18M (04-Oct-2027) and 2Y (03-Apr-2028) that the
  20-row export does not show.
- A segment-specific convention. This is the only checked segment spanning a
  year end (31-Dec-2027), but a typical positive turn premium would move the
  rate the other way.
- Interpolation weights on another day basis. Not tested, deliberately, to avoid
  fitting.

**Required from Bloomberg (curve 490, curve date 31-Mar-2026, same snapshot as SWPM):**
1. Complete curve member list: instrument type, tenor, maturity, quote, active status.
2. Curve settings: interpolation method and quantity, turn-of-year or
   meeting-date settings, interpolation day basis.
3. Full-precision zero rate and DF at 30-Nov-2027 and 28-May-2027 (control),
   at 28-Apr-2028 (OI-7), and at the 04-Oct-2027, 03-Apr-2028 and
   02-Apr-2029 pillars.
4. Confirmation that the SWPM trades (TC1 and TC3) used curve 490 for both
   projection and discounting from that snapshot.

**Rule:** do not change interpolation or add adjustments to match the two
cashflows. When the data arrives, re-run the analysis, then update the recorded
baseline and this entry together.

## OI-2: Rate cutoff vs lockout

Bloomberg TC1 has `rate_cut_off_days = 1`. The fresh floating leg keeps the cutoff
as contractual metadata and passes `lockoutDays = 0` to QuantLib. On TC1 the two
readings differ by about 0.001 bp, below Bloomberg's display precision, so TC1
cannot confirm the mapping. Needs a Bloomberg proof-out of the last observations
in a period, or a trade where the difference is material.

## OI-3: TC1 lookback discrepancy

`tests/fixtures/bloomberg_irs/cases/TC1.json` records `lookback_days: 1`;
the Bloomberg source (`source/TC1.json`, `leg_2.days_before_accrual`) is 0. The TC1
tests read the lookback from the source. With lookback 1, Period 1 moves by
+0.045 bp. The fixture has not been changed and needs an owner decision. The
legacy fixture `tests/fixtures/bloomberg_irs_case.json` also records 1.

## OI-4: Legacy SOFR path

The uncommitted changes to `instruments/rates/interest_rate_swap.py` and
`market/curves/yield_curve.py` are kept separate from the fresh implementation.
Unresolved issues:
- `rate_cutoff_days` is passed as `lockoutDays`.
- `reset_type` and `principal_exchange` are stored but not applied.
- Lookback is 1, from the legacy fixture.
- Forward rates are chained interval forwards, and DFs sit on display dates.
- The schedule uses the Federal Reserve calendar while the index fixes on the
  SOFR calendar.
- Same frequency on both legs only; empty-handle fallback.

TC1 NPV on that path is −7,520.51 (QL 1.43). `tests/irs/test_bloomberg_irs_discount_curve.py`
fails, a known curve gap. Not to be merged into the fresh implementation
without explicit decisions.

## OI-5: Curve market-data source and request integration

**Done:**
- `market/curves/irs_zero_curve.py` builds the curve from structured
  `ZeroCurveMarketData` only.
- `market/curves/irs_market_environment.py` puts that one curve into a
  `MarketEnvironment` as both the discount and forecast curve of its currency.
- TC1 prices end to end through `build_instrument_from_request` and
  `PricingService.price`, using instrument `"ois"` (`FreshOISInstrument`), model
  `"analytical"` and engine `("ois", "discounting")` (`FreshIRSDiscountingEngine`,
  which never falls back to another curve).
- The service result equals the recorded reconciliation baseline exactly.
- TC3 (amortising, semiannual, short final stub, contractual maturity on a
  Sunday) prices through the same path with no instrument- or engine-specific code.

**Still open:**
- The curve data comes from the committed test fixture
  `tests/fixtures/bloomberg_irs/curves/2026-03-31-USD-SOFR-zero.json`, through a
  test-side adapter in `tests/unit/test_irs/conftest.py`. Its tenors are inferred,
  because the Bloomberg export has no Tenor column. A production market-data source
  waits until the Bloomberg tenor mapping and curve conventions are confirmed.
- `MarketDataRequest` cannot carry zero curves, and `build_market_env_from_request`
  builds flat test curves only. The e2e test therefore builds the environment with
  the helper and uses the request for the instrument and the model/engine selection.
- `MarketEnvironment` keys curves by currency only, which is enough for
  single-curve TC1. Separate discount and projection curves per benchmark need a
  typed IRS pricing context.
- `build_instrument_from_request` swallows `from_dict` errors and retries with the
  constructor. `FreshOISInstrument` refuses untyped constructor input, so a bad
  request still fails, but with a generic `TypeError` rather than the specific
  validation message.
- The TC1 test helpers wrap the zero curve in `QuantLibDiscountCurve` for
  `attach_discounting_engine`. The service path does not need this.

## OI-6: Bloomberg-derived data and the public remote

`origin` (github.com/quantpanda007/quantdiva) is public. Bloomberg-derived
fixtures, including the zero-curve fixture in commit `581e68b`, are committed
locally only. Decision: keep all commits local, no push, until the data-sharing
implications are reviewed.

## OI-7: 28-Apr-2028 discount factor (TC3 Period 4)

Linked to OI-1 (same curve, same missing Bloomberg data), but measured and tracked
separately: it sits in a different curve segment and has the opposite sign.

**Observed (Bloomberg, as displayed):** Period 4 (30-Nov-2027 → 28-Apr-2028,
150 days, notional 197,500) equivalent coupon 4.12404%, payment 3,393.74,
DF 0.927854.

| Metric | Optima − Bloomberg |
|---|---:|
| 28-Apr-2028 DF | −5.30e-6 |
| Period 4 coupon | +0.217 bp |
| Period 4 payment | +$1.79 |
| Period 4 payment effect on PV | +$1.66 |

TC3 totals (Optima − Bloomberg, cashflow-leg references): floating leg +$0.59,
fixed leg +$0.0015, NPV +$0.59. The floating-leg total is the net of the OI-1
Period 3 effect (−$1.04) and this one (+$1.66), so the small total hides two
larger opposing differences.

**Established:** TC3 Periods 1 and 2 reconcile within display precision (coupons
≤ 0.001 bp, DFs ≤ 2.5e-7) and the four fixed cashflows within $0.005, so the
amortisation, spread and stub handling are not the source. Period 4 is the first
TC case that uses the curve beyond the 2Y pillar (03-Apr-2028 → 02-Apr-2029
segment), and its accrual spans the 18M–2Y segment.

**Rule:** as OI-1. No interpolation or curve changes to match; resolve with the
Bloomberg curve-490 data and update the TC3 baseline and this entry together.

## OI-8: Contractual maturity vs adjusted accrual dates

**Date meanings (fresh IRS, `FreshOISInstrument`):**
- `effective_date`: contractual start date as supplied.
- `maturity_date`: contractual, unadjusted maturity, stored and returned by
  `maturity()` exactly as supplied; never normalised.
- Accrual and payment dates: supplied explicitly per period. The schedule and leg
  builders use them as given (QuantLib `NullCalendar`, `Unadjusted`); no builder
  generates or adjusts dates.
- `accrual_date_adjustment` (required, per leg): `calendar` and
  `business_day_convention`. Used **only** to validate the final accrual end; it
  cannot change a price.

**Validation rule (provisional):** start exact, end adjusted.
- The first accrual start must equal `effective_date` exactly.
- The final accrual end must equal `maturity_date` adjusted with that leg's
  calendar and convention.

This is the convention observed in Bloomberg TC1, TC3 and TC4, not a universal IRS
rule: all three start on a non-business day that Bloomberg leaves unadjusted
(31-May-2026, 31-May-2026, 01-Jan-2026), and TC3 and TC4 end on a Sunday
contractual maturity that Bloomberg adjusts Modified Following (30-Apr-2028 →
28-Apr-2028; 28-Feb-2027 → 26-Feb-2027). Revisit if another case contradicts it.

**Calendar mapping (assumption):** Bloomberg `FD` → QuantLib
`UnitedStates(FederalReserve)`. On every TC1/TC3/TC4 date checked, the Federal
Reserve, Government Bond and SOFR calendars give the same result, so the data
cannot confirm the mapping. Only `FD` is mapped; any other code (for example `SZ`
in TC2, `RB` in TC5) is rejected until confirmed.

**Known limitations:**
- One-way check: an already-adjusted date passed as `maturity_date` also validates
  (adjusting a business day leaves it unchanged), and is then stored as given. The
  check proves consistency, not that the supplied date is the contractual one.
  Covered by `test_tc3_pricing_service_e2e.py::test_one_way_validation_limitation`.
- Payment dates are not checked against accrual ends or a payment delay; all TC
  cases so far have pay delay 0.
- Interior accrual dates are not checked against the calendar.
- The pure schedule generator (`instruments/rates/irs/schedule.py`) produces
  unadjusted dates and is not on the pricing path; it does not use this
  adjustment.

## OI-9: TC3 Bloomberg `leg_*_market` NPVs

`references/TC3.json` has two sets of leg values:

| Section | Leg 1 (pay fixed) | Leg 2 (receive float) | Sum |
|---|---:|---:|---:|
| `cashflow_leg_*` npv | −18,850.36 | 40,653.83 | 21,803.47 |
| `leg_*_market` npv | 15,205.84 | 6,597.63 | 21,803.47 |

Both sum to the trade NPV. The `cashflow_leg_*` values are the PVs of the listed
cashflows and are the references used. The `leg_*_market` values differ from them
by ±34,056.20 and appear to split the NPV by premium (1.92% + 0.84% ≈ 2.76%); their
definition is not confirmed. They are recorded and not used. Needs the Bloomberg
field definition.
