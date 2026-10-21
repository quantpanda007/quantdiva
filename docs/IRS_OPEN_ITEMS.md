# Fresh IRS: Open Items

Register of unresolved items for the fresh IRS implementation. Each item lists
what is known (observed), what has been done, what is still missing, and where it
is monitored. Items here are **not** resolved by tuning, hardcoded adjustments, or
editing recorded baselines.

Last updated: 14-Oct-2026 (later) · QuantLib 1.43

| ID | Item | Status | Monitored by |
|---|---|---|---|
| OI-1 | TC1 Period 2 / 30-Nov-2027 discount factor vs Bloomberg (also TC3 Period 3) | Open: unresolved; tested curve variants do not match both payment-date DFs; awaiting Bloomberg curve-490 details | `test_tc1_bloomberg_reconciliation.py`, `test_tc3_pricing_service_e2e.py` |
| OI-2 | Bloomberg rate cutoff vs QuantLib `lockoutDays` | Open: mapping not confirmed; TC1 (0.001 bp) and JPY TC6/TC10 (lockout 1 makes every coupon slightly worse) support the unmapped treatment | `test_tc1_bloomberg_reconciliation.py::test_baseline_conventions_are_the_recorded_ones` |
| OI-3 | TC1 lookback: case fixture 1 vs Bloomberg source 0 | Open: fixture not changed | `test_tc1_period1_regression.py::test_lookback_is_taken_from_bloomberg_source` |
| OI-4 | Legacy SOFR path (`interest_rate_swap.py`, `yield_curve.py`) | Excluded, uncommitted experimental work | not part of the fresh IRS suite |
| OI-5 | Curve market-data source, tenor mapping, request-level curve input | Partly done: file-driven CLI workflow in place; tenor mapping and conventions still unconfirmed | `test_irs_zero_curve.py`, `test_tc1_pricing_service_e2e.py`, `test_tc3_pricing_service_e2e.py`, `test_irs_input_workflow.py` |
| OI-6 | Bloomberg-derived data and the public GitHub remote | Decision deferred: keep all commits local | — |
| OI-7 | TC3 Period 4 / 28-Apr-2028 discount factor vs Bloomberg | Open: awaiting Bloomberg curve-490 data (with OI-1) | `test_tc3_pricing_service_e2e.py` |
| OI-8 | Contractual maturity vs adjusted accrual dates; calendar mapping | Implemented with provisional convention; calendars FD, SZ, JN, RB (accrual) and EN, SZ, RB (fixing), evidence-based, not SME-confirmed | `test_tc1_pricing_service_e2e.py`, `test_tc3_pricing_service_e2e.py` |
| OI-9 | TC3 Bloomberg `leg_*_market` NPVs differ from the cashflow-leg NPVs | Open: unexplained, not used as references | `test_tc3_pricing_service_e2e.py` |
| OI-10 | Seasoned trades: already-paid cashflows and historical fixings | Implemented (14-Oct-2026): settled cashflows excluded as by the engine and listed; fixings on or before the valuation date are market data with stated sources; a missing fixing blocks the case | `test_irs_cashflows.py`, `test_irs_input_workflow.py`, `test_irs_case_audit.py` |
| OI-11 | TC2 (`SLLSL9SL`): analysis notional 20,000 vs source schedule 20,000,000; fixing-date convention | Notional settled (20,000); Method B fixing rule established by evidence (P2–P8 effective reset dates match exactly; **P1 differs by one day, cause unresolved**, R8); under Method B, TC2 P1 needs SARON fixings 29-Jan → 30-Mar-2026 (R3). TC2 is now priced with Method A (OI-17) | `test_irs_case_audit.py` (TC2 MISSING_FIXINGS) |
| OI-12 | TC2/TC7: SF0006M fallback projection (6M SARON compounded, 2-day observation shift, + 0.0741%) | Provisional: payment mechanics confirmed; 0.0741% settled; rate period starts 1 EN business day after the reset date (TC2: 7/7 windows end on Bloomberg's effective reset dates) | `test_irs_tc7_term_rate.py` |
| OI-13 | TC7 reset-projection residuals: Optima vs Bloomberg Resets tab −0.054 / −0.052 / −0.014 bp (was −0.18 on the first reset before the window-start rule) | Open: `latest_index` not used (SME); remaining gaps 2.7e-6 / 2.6e-6 / 0.7e-6 in the windows' DF ratios; curve vs compounding/rounding open; awaiting curve-234 DFs at 7+ decimals | `test_irs_tc7_term_rate.py::test_provisional_fallback_against_resets_tab` |
| OI-14 | TC7 31-Jul-2028 discount factor: Optima 0.9959637 vs Bloomberg 0.995966 (−2.3e-6), between the 2Y and 3Y pillars | Open: outside display tolerance (5e-7); interpolation/pillar convention not yet investigated | `test_irs_tc7_term_rate.py::test_payment_date_dfs_against_bloomberg` |
| OI-15 | INR (TC5, TC8, TC9): MIBOR OIS curve and IRSWOF 6M projection | Curve validated (Bloomberg trade DFs within 4.3e-7); IRSWOF projection provisional (full 6M resets within 0.3 bp); reset periods shorter than 6M 23–39 bp off, unresolved, SME question | `test_irs_inr_jpy.py`, `test_irs_full_report.py` |
| OI-16 | JPY (TC6, TC10): TONA OIS curve, +390-day row, TONA leg | Curve validated (Bloomberg trade DFs within 1.0e-6; +390-day row = 15M); TONA leg within 0.016 bp; Bloomberg shows whole-yen amounts | `test_irs_inr_jpy.py`, `test_irs_full_report.py` |
| OI-17 | TC2 SARON observation-date method: Method A (contractual accrual, no shift) vs Method B (reset-date fallback) | **Method A configured as a PROVISIONAL operational default** (14-Oct-2026), not Bloomberg/SME-confirmed; no-shift is an operational assumption (no shift term in the trade data). TC2 NPV −153.3732 vs −158.91 (+5.537). Method B preserved and selectable; not computable without R3. Decision: R9 | `test_irs_observation_methods.py` |

---

## OI-1: 30-Nov-2027 discount factor (TC1 Period 2)

**Status (12-Oct-2026):** unresolved. No tested curve variant reproduces Bloomberg
at both TC1 payment dates; the remaining gap is the Period 2 coupon.

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

**Payment-date DFs (Bloomberg displays six decimals, ±5e-7):**

| Payment date | Bloomberg | Optima baseline | Optima − Bloomberg | Within display rounding? |
|---|---:|---:|---:|---|
| 28-May-2027 (Period 1; control) | 0.958306 | 0.9583058 | −2.4e-7 | Yes |
| 30-Nov-2027 (Period 2) | 0.941092 | 0.9410946 | +2.6e-6 | No (about 5×) |

**Current baseline curve:** linear interpolation of continuously compounded zero
rates (ACT/365F) between the reconstructed maturity pillars, flat before the
first pillar. It is retained as the baseline because it is the only tested
interpolation consistent with the 28-May-2027 check (inside the long 12M–18M
segment) and the Period 1 coupon. This does not establish it as Bloomberg's
methodology.

**Established:**
- Period 1 reconciles within Bloomberg display precision, and so do the
  28-May-2027 DF and the Period 1 start DF implied by the coupon.
- Bloomberg's own Period 2 coupon and 30-Nov DF are mutually consistent
  (coupon-implied DF 0.9410922).
- The floating-leg gap comes through the Period 2 coupon (projection); the
  discounting effect is under $0.02.
- Ruled out: input rounding (effect ≤ 1e-7 in DF).
- The gap is about 5× the display-rounding band, so it is real but small.
- TC3 Period 3 has the same dates (28-May-2027 → 30-Nov-2027) and the same
  result: Bloomberg DF 0.941092, Optima DF +2.56e-6, coupon −0.054 bp (−$1.10 on
  TC3's 395,000 notional). The compounded SOFR is identical to TC1 Period 2 once
  the spreads (70 bp vs 10 bp) are removed, so this is one curve difference seen
  in two trades.

**Curve construction evidence (12-Oct-2026, scratch diagnostics only):**
- The SME confirmed that curve 490 is built by repricing each market instrument
  to zero at inception, solved with Excel Goal Seek. Instrument types,
  conventions, the solved quantity, node placement and interpolation are not yet
  confirmed.
- Reading the export's Market Rate values as SOFR OIS par quotes (hypothesis) and
  bootstrapping them in QuantLib (T+2 on the US SOFR calendar; annual ACT/360 fixed
  leg; backward schedule, Modified Following; payment lag 0; nodes at maturity;
  linear zero) reprices every quote to 1e-9 bp and reproduces the SME zero rates
  and DFs at all 20 pillars within export rounding (≤ 0.0013 bp, ≤ 5e-7). TC1 on
  that curve is within 0.012 of the baseline NPV and 0.0007 bp of its coupons.
- Because each instrument's coupon dates fall on pillars, the solved pillar values
  do not depend on the interpolation. Matching the SME pillars therefore cannot
  reveal Bloomberg's interpolation; only off-pillar checks (28-May and 30-Nov) can.
- Reading Market Rate instead as a simple ACT/360 rate from the valuation date,
  interpolated linearly, gives TC1 coupons −1.66 bp and −13.28 bp vs Bloomberg
  (total NPV −256.03). That reading is not consistent with Bloomberg's outputs.

**Tested curve variants (TC1; lookback 0, lockout 1, QuantLib 1.43):**

| Variant | What changes vs baseline | DF 28-May-27 − BBG | DF 30-Nov-27 − BBG | P1 coupon − BBG | P2 coupon − BBG | Total NPV − BBG |
|---|---|---:|---:|---:|---:|---:|
| Baseline: SME zeros, linear zero | — | −2.4e-7 | +2.6e-6 | −0.0004 bp | −0.054 bp | −0.71 |
| OIS bootstrap, linear zero | Input source only (same dates, same interpolation) | −2.8e-7 | +2.6e-6 | +0.0000 bp | −0.054 bp | −0.70 |
| OIS bootstrap, log-linear DF | Interpolation only (node DFs identical) | +3.0e-5 | +5.3e-5 | −0.326 bp | −0.498 bp | −23.35 |
| SME zeros, cubic zero | Interpolation only | −1.5e-5 | −7.7e-6 | +0.158 bp | −0.148 bp | +6.30 |
| SME zeros, monotone-cubic zero | Interpolation only | −3.0e-5 | −7.8e-6 | +0.315 bp | −0.447 bp | +10.54 |
| Supplied DFs, log-linear DF | Inputs and interpolation | +3.0e-5 | +5.3e-5 | −0.328 bp | −0.497 bp | −23.46 |
| OIS bootstrap, payment lag 2 (nodes at payment dates) | Payment lag and node placement together (confounded) | −2.0e-6 | −3.2e-8 | +0.017 bp | −0.036 bp | +0.43 |

Baseline here is the lockout-1 diagnostic (−7,955.71); the recorded production
baseline uses lockout 0 (−7,955.73). Cubic, monotone-cubic and supplied-DF rows
are from `IRS_TC1_RESIDUAL_RECON_DIAGNOSTIC.md` §3; the others are scratch
diagnostics run on 12-Oct-2026 outside the repository.

**Reading of the variants:**
- Every alternative interpolation moves the 28-May-2027 DF by 1.5e-5 to 3.0e-5
  (30–60× the display rounding), so none is consistent with Bloomberg's values.
- Payment-date nodes bring the 30-Nov-2027 DF into agreement but move the
  28-May-2027 DF to −2.0e-6 and Period 1 to +0.017 bp; the error shifts rather
  than disappears. Payment lag and node placement cannot be separated here, so
  this is not evidence for either.
- No result is used to select a method by fit to Bloomberg.

**Hypotheses (unconfirmed):**
- Bloomberg curve members between 18M (04-Oct-2027) and 2Y (03-Apr-2028) that the
  20-row export does not show.
- A segment-specific convention. This is the only checked segment spanning a
  year end (31-Dec-2027), but a typical positive turn premium would move the
  rate the other way.
- An interpolation method or time basis not among those tested.
- Node placement or member payment lag different from the baseline.

**Required from Bloomberg (curve 490, curve date 31-Mar-2026, same snapshot as SWPM):**
1. Complete member list: instrument type, tenor, effective date, maturity, quote and
   active status; whether the 20-row export is that list; what the Market Rate
   column holds.
2. Construction settings: the quantity solved by Goal Seek and its compounding and
   day count; interpolation method and time basis; node placement; member payment
   lag, schedule generation and stub rule; turn-of-year and meeting-date settings;
   Goal Seek tolerance.
3. Full-precision zero rate and DF at 30-Nov-2027 and 28-May-2027 (control),
   at 28-Apr-2028 (OI-7), and at the 02-Apr-2027, 04-Oct-2027, 03-Apr-2028 and
   02-Apr-2029 pillars.
4. Confirmation that the SWPM trades (TC1 and TC3) used curve 490 for both
   projection and discounting from that snapshot.
5. Only if items 1–4 do not settle it: a daily or weekly DF/zero grid from
   02-Apr-2027 to 02-Apr-2029, and SWPM daily projected SOFR for TC3 Periods 3–4.

**Rule:** do not change interpolation or add adjustments to match the two
cashflows. When the data arrives, re-run the analysis, then update the recorded
baseline and this entry together.

## OI-2: Rate cutoff vs lockout

Bloomberg TC1 has `rate_cut_off_days = 1`. The fresh floating leg keeps the cutoff
as contractual metadata and passes `lockoutDays = 0` to QuantLib. On TC1 the two
readings differ by about 0.001 bp, below Bloomberg's display precision, so TC1
cannot confirm the mapping. Needs a Bloomberg proof-out of the last observations
in a period, or a trade where the difference is material.

**JPY evidence (14-Oct-2026):** TC6 and TC10 also have `rate_cut_off_days = 1`.
Mapping the cutoff to `lockoutDays = 1` moves every TONA coupon further from
Bloomberg (TC6: −0.0005 → −0.0015, −0.0155 → −0.0163, −0.0076 → −0.0121 bp; TC10:
−0.0023 → −0.0041 bp). This supports the unmapped treatment but is below display
precision on its own, so the mapping stays unconfirmed.

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
- Input-driven workflow (command line, no FastAPI):
  `python scripts/price_irs.py --trade <trade.json> --market <market.json> [--output result.json]`.
  - Trade file: `{"schema_version": 1, "instrument_type": "ois", "params": {...}}`, with
    `params` exactly the `FreshOISTrade` parameters (Option B validation applies).
  - Market file: valuation date, curves (observations plus explicit conventions) and
    per-currency `discount` / `forecast` curve assignments, which may differ.
    Parsed and resolved by `market/curves/irs_market_snapshot.py`; curves are built
    with `build_zero_curve`.
  - `services/pricers/irs_valuation.py` (`price_irs`) builds the instrument through the
    registry (specific validation errors), resolves the environment, prices with
    `PricingService` and the discounting engine, and reads cashflows with
    `irs_cashflow_rows`.
  - It fails, never falls back, on: a missing assignment; a curve of another
    currency; a curve reference date or trade valuation date that differs from the
    market valuation date; an unsupported convention; or a floating benchmark that
    does not map to the forecast curve's benchmark.
  - Strict vocabularies (14-Oct-2026): market calendars `US-SOFR`, `US-FED`,
    `CH-SARON`, `IN-MIBOR`, `JP-TONA` (trade calendars: OI-8); benchmark map
    `SOFRRATE` → `SOFR`, `SF0006M` → `SARON`, `MUTKCALM` → `TONA`, `IRSWOF` →
    `MIBOR`. INR and JPY curves are bootstrapped from OIS par rates (OI-15, OI-16).
    Optional `fixings` section (OI-10).
  - TC1/TC3 inputs: `examples/irs/tc1_trade.json`, `examples/irs/tc3_trade.json`,
    `market_data/2026-03-31/USD/usd_sofr_2026-03-31.json`. Generated from the existing fixtures
    and checked against them by `test_irs_input_workflow.py`. Bloomberg-derived:
    local commits only (OI-6). Zero rates are stored as decimals, so NPVs agree with
    the fixture route to about 1e-10, within the 1e-6 baseline tolerance.

**Still open:**
- The curve observations are Bloomberg export values with inferred tenors (the
  export has no Tenor column), and the curve conventions in the market file are the
  ones established for TC1 (SOFR calendar, T+2, Modified Following, ACT/365F,
  continuous, linear zero, flat front). Both await confirmation of the Bloomberg
  tenor mapping and curve settings (OI-1).
- `MarketDataRequest` cannot carry zero curves, and `build_market_env_from_request`
  builds flat test curves only. The e2e test therefore builds the environment with
  the helper and uses the request for the instrument and the model/engine selection.
- `MarketEnvironment` keys curves by currency only. Discount and forecast curves can
  differ, but a currency can have only one forecast curve, so trades on two
  benchmarks in one currency would need a richer pricing context.
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
cannot confirm the mapping.

**Further mappings (14-Oct-2026, evidence-based, not SME-confirmed):**
- `SZ` → `ql.Switzerland` (TC2/TC7 accrual): reproduces every TC7 date, but TC7's
  dates do not distinguish it from other calendars.
- `EN` → `ql.UnitedKingdom` (term-rate fixing): TC7's source reset 27-Aug-2027 is one
  UK business day before 31-Aug-2027 (30-Aug-2027 UK holiday), and 28-Aug-2026 + 1 UK
  business day = 01-Sep-2026 (31-Aug-2026 UK holiday) is the TC7/TC2 rate-period start
  (OI-12).
- `JN` → `ql.Japan`, `RB` → `ql.India`: the OIS bootstraps on these calendars
  reproduce Bloomberg's JPY and INR trade DFs (OI-15, OI-16).
Any other code is rejected until confirmed.

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

## OI-10: Seasoned trades

**Implemented (14-Oct-2026).**
- `irs_cashflow_rows` excludes any coupon paying on or before the valuation date, as
  `ql.DiscountingSwapEngine` does (`includeReferenceDateEvents = False`), so the rows
  still sum to the engine NPV. `settled_cashflows` lists them and `price_irs`
  reports them (`IRSValuation.settled`). Bloomberg's tables also omit them (TC4).
- Fixings on or before the valuation date are market data: the optional `fixings`
  section of a market snapshot (`market_data/2026-03-31/fixings_2026-03-31.json`), each series
  with its source. Overnight fixings are put into QuantLib's index history only while
  a trade is priced and its cashflows read, then restored
  (`market/curves/irs_fixings.py`); term-rate fixings go to the leg directly.
- A coupon whose fixings precede the valuation date and are not supplied fails with a
  clear message (`CashflowExtractionError`, `TermRateFixingRequired`); the audit
  reports it as `MISSING_FIXINGS`. Nothing is inferred.

**Fixings in use:**
- SOFR 31-Mar-2026 = 3.68% (TC4's first floating period starts on the valuation
  date). Public sources stated in the file; equal to TC4's `latest_index`. With it
  TC4 reconciles (NPV +0.0033, PASS); without it Optima projects 3.651% and Period 2
  is −0.59. Confirm against the NY Fed release.
- TONA 31-Mar-2026 = 0.727% (TC10's first period starts on the valuation date):
  global-rates March 2026 last value; confirm the daily value against the Bank of
  Japan.
- IRSWOF 6M 27-Feb-2026 = 5.36% (TC8 Period 1): from the TC8 trade record; not
  independently sourced.
- Missing: SARON 29-Jan-2026 → 30-Mar-2026 for TC2 Period 1 (OI-11).

These are market observations, not Bloomberg model outputs. The SME's statement that
`latest_index` is not used concerns TC7's projected resets; for TC4 and TC10 the
value applied is the published fixing of the valuation date, from its own source.

## OI-11: TC2 (`SLLSL9SL`) notional and fixing dates

> **14-Oct-2026 (later):** TC2 is now priced with Method A (contractual accrual dates,
> no observation shift), a provisional operational default (OI-17). Everything below
> about the reset-date rule, P1's window, R3 and R8 describes **Method B**
> (`reset_date_fallback`), which is preserved unchanged and selectable.

**Notional: settled. Analysis notional = 20,000** (initial; amortising 2,500 per
quarter to 2,500 in the final period). Do not reopen this question unless new
evidence contradicts it.

Evidence:
- `tests/fixtures/bloomberg_irs/cases/TC2.json` records the trade notional as `20000`.
- Bloomberg cashflow notionals run 20,000 → 2,500, exactly 1/1,000 of the schedule
  balances in all eight periods.
- All eight Bloomberg fixed coupons equal notional × 1% × 30/360 on the 20,000 basis
  (Period 1: 20,000 × 1% × 90/360 = 50.00; Bloomberg 50.00).
- Bloomberg NPVs are on the same scale: total −158.91, fixed −220.60, floating 61.69.

**Conflicting source value: kept unchanged.** The leg notionals and amortisation
schedules in `source/TC2.json` (and the leg sections of `cases/TC2.json`) give
20,000,000 → 2,500,000. They are not edited. Any TC2 pricing must take 20,000 as an
explicit input rather than reading the schedule balances (`read_terms` returns the
schedule values, which are 1,000× too large).

**Fixing dates: established by evidence (14-Oct-2026).** Each quarterly coupon is the
SF0006M fallback fixed at the source `reset_date` of its period; the 6M IBOR period
starts 1 EN business day after the reset date (as for TC7, OI-12). On the SME CHF
curve the production fallback gives, for periods P2–P8, observation windows ending
exactly on Bloomberg's `effective_reset_date` (P1 differs by one day, below), and rates
within 0.15 bp of Bloomberg's coupons minus the 10 bp margin (−0.14 to +0.03 bp;
Bloomberg shows the coupon to 0.01 bp, so these are small projection residuals of the
same order as TC7's, OI-13). The earlier hypotheses (stated semiannual convention; 6M proxy at
the effective reset date; plain compounded SARON) all miss by 6–13 in NPV and are
superseded.

**Rule, step by step (current production convention, provisional; OI-12):**
1. IBOR period start = source reset date + 1 EN business day (trade fixing days and
   fixing calendar);
2. IBOR period end = start + 6M, Modified Following, Swiss calendar;
3. SARON observation start = IBOR start − 2 Swiss business days (observation shift);
4. SARON observation end = IBOR end − 2 Swiss business days.

Bloomberg shows one date per period, `effective_reset_date`, read here as the
observation end. It therefore confirms the end-date mapping only; the start dates
(including P1's 29-Jan-2026) follow from the same rule and are not directly shown.

**P1 observation end: one-day discrepancy, unresolved (14-Oct-2026; evidence request
R8).**

| | Date |
|---|---|
| Contractual accrual | 30-Apr-2026 → 31-Jul-2026 (does not set the window) |
| Reset date (source) | Fri 30-Jan-2026 |
| IBOR period | Mon 02-Feb-2026 → Mon 03-Aug-2026 (02-Feb + 6M = Sun 02-Aug, Modified Following) |
| SARON observation window (current rule) | Thu 29-Jan-2026 → Thu 30-Jul-2026 |
| Bloomberg `effective_reset_date` | Wed 29-Jul-2026 (one Swiss business day earlier) |

P1 is the only TC2 period whose unadjusted 6M end falls on a weekend that Modified
Following moves into the next month. A Modified Preceding roll (to Fri 31-Jul) would
give 29-Jul, but that has not been tested as a general rule and nothing in P7/P8
supports it, so the cause is open. **The production convention is not changed to force
a match.** The discrepancy concerns a future observation date only; it does not affect
the historical-fixing requirement below.

**Terminology.** Under the current rule P1's *full observation window* is 29-Jan-2026
→ 30-Jul-2026. Only the part before the valuation date (29-Jan → 30-Mar-2026) needs
*historical fixings*; observations from 31-Mar-2026 onwards are projected from the
curve. The end-of-window question (30-Jul vs 29-Jul, R8) and the fixing requirement
(R3) are separate items.

**Remaining dependency under Method B (R3; no longer blocks TC2, which is priced with
Method A, OI-17):** daily SARON fixings
29-Jan-2026 → 30-Mar-2026 (43 Swiss business days; no Swiss holidays in the range),
not in the market data and not found in public sources. Under Method B, TC2 cannot be
priced until they are supplied (`fixings.SARON`). The production path's
exact requirement is pinned by tests (`test_irs_inr_jpy.py`): with 29-Jan → 30-Mar it
prices; without 29-Jan it fails ("Missing SARON fixing for January 29th, 2026");
without 30-Mar it fails ("… March 30th, 2026"); an extra 28-Jan fixing is ignored.

## OI-12: TC7 (`SLLSL9SI`) SF0006M fallback projection — provisional

**Affected:** TC7 (CHF, SF0006M 6M, semiannual reset, annual payment, Flat
compounding, `ibor_fallback.opt_in = true`). Any future SF0006M trade (TC2 once
OI-11 is resolved) would use the same definition.

**Implementation (provisional):** `instruments/rates/irs/term_rate_leg.py`,
`TERM_BENCHMARKS["SF0006M"]`. Each reset rate is SARON compounded over the 6M
period starting on the sub-period start (Modified Following, Swiss calendar),
with a 2-business-day observation shift, plus 0.0741% (the published CHF LIBOR 6M
spread adjustment). Sub-period amounts are combined by flat compounding (spread
not compounded). The definition is labelled PROVISIONAL in the code.

**Evidence:**
- **Payment mechanics:** Bloomberg's own Resets-tab rates (SWPM screenshot,
  13-Oct-2026: 0.21366%, 0.33654%, 0.28763%) fed into the existing flat-compounding
  calculation reproduce both Bloomberg floating payments to the cent (251.29,
  117.98). `test_irs_tc7_term_rate.py::test_flat_compounding_with_bloomberg_reset_rates_reproduces_bloomberg_payments`.
  This supports the payment calculation. It does **not** confirm the fallback
  convention, because Bloomberg's rates are supplied as inputs.
- **Observation windows:** the last window of each payment period ends on
  24-Aug-2027 and 25-Feb-2028, exactly Bloomberg's `effective_reset_date` values.
  `test_irs_tc7_term_rate.py::test_observation_windows_end_on_bloomberg_effective_reset_dates`.
- **Reset rates:** the projected rates differ from the Resets tab by −0.18, −0.05
  and −0.01 bp (pinned in
  `test_irs_tc7_term_rate.py::test_provisional_fallback_against_resets_tab`). The
  first reset is OI-13.
- **Effect (before the rate-period-start rule below):** TC7 NPV −388.7062 vs Bloomberg −388.06 (−0.65); fixed leg +0.004,
  floating leg −0.64. The ten-case report classifies TC7 as FAIL.

**Spread-adjustment sensitivity (14-Oct-2026, scratch only, no code change).**
Same trade (`examples/irs/tc7_trade.json`), same SME curve 234
(`market_data/2026-03-31/CHF/chf_saron_2026-03-31.json`), same flat compounding and day counts;
only the reset-rate definition varied. M2–M4 are **sensitivity analyses, not
confirmed contractual conventions**. M3 is the EU Implementing Regulation
2021/1847 statutory replacement (3M SARON compound observed over the 3 months
preceding the period, + 0.0741%); M2 and M4 are not documented conventions.

| Method | Resets (bp vs Resets tab) | P1 / P2 vs BBG | Floating PV vs BBG | NPV vs BBG |
|---|---|---|---|---|
| M1 current: ISDA, 6M in arrears, 2bd shift, +0.0741% in the reset rate | −0.18 / −0.05 / −0.01 | −0.61 / −0.03 | −0.64 | −0.65 |
| M2 as M1, 0.0741% added with the margin (not compounded) | as M1 | −0.65 / −0.03 | −0.68 | −0.69 |
| M3 EU 2021/1847, 3M SARON in advance, +0.0741% | −16.20 / −6.24 / +8.06 | −58.75 / +19.49 | −39.23 | −39.23 |
| M4 as M1, no adjustment | −7.59 / −7.46 / −7.42 | −39.74 / −17.96 | −57.55 | −57.56 |

Fixed leg −756.3760 in all methods. Conclusions: the documented alternative (M3)
does not fit TC7; the 0.0741% is clearly included by Bloomberg (M4 is ~7.5 bp low
on every reset); compounding vs not compounding the adjustment moves NPV by 0.04
only. The remaining gap sits in the first reset (OI-13), not in the
spread-adjustment method. **Do not raise the 0.0741% question with the SME again**
unless new contradictory evidence appears.

**Rate-period start (14-Oct-2026):** the IBOR period starts 1 fixing-calendar (EN)
business day after the reset date (`term_rate_leg.rate_period_start`). For TC7 this
moves the first window to 28-Aug-2026 → 25-Feb-2027 (31-Aug-2026 is a UK holiday, so
28-Aug + 1 EN business day = 01-Sep-2026); the other two windows are unchanged. The
same rule reproduces TC2's effective reset dates for P2–P8; P1 differs by one day
(unresolved, OI-11, R8).
TC7 NPV −388.3752 (was −388.7062), Bloomberg −388.06.

**Not confirmed:** whether SWPM projects SF0006M with this fallback (compounding
period and observation shift). The 0.0741% adjustment is settled (sensitivity
below). The reset schedule is also
an explicit trade input (`examples/irs/tc7_trade.json`) because SWPM's rule for a
stub payment period is unknown: Bloomberg uses a single reset for the 11-month
second period.

**Status:** open, provisional.
**Required confirmation:** how SWPM generates resets for a stub payment period.
The spread adjustment (0.0741%, included in the reset rate) is no longer an SME
question (see the sensitivity above).
**End-to-end trace (14-Oct-2026):** the production path was traced for the first
reset through to the NPV; see OI-13. Every figure reproduces the report exactly
(NPV −388.7061541139417, floating 367.66987067492914, fixed −756.3760247888708).
**Next action:** resolve OI-13 first. Until then, keep the implementation and its
PROVISIONAL label unchanged.

## OI-13: TC7 reset-projection residuals (first reset 28-Aug-2026)

**Affected:** TC7 projected resets, mainly 28-Aug-2026 (first sub-period of
Period 1, 31-Aug-2026 → 26-Feb-2027).

**SME confirmation (14-Oct-2026):** Bloomberg's Resets-tab rates are provided for
inspection only, and `latest_index` is **not** used to determine them. The reset
rates are not Optima inputs; Optima projects them from the supplied CHF SARON data.
`latest_index` therefore stays out of the reset calculation, and no override logic
is to be introduced. (Its numerical equality with the first reset, 0.21366, is a
display of Bloomberg's projection, not an input.)

**Goal:** explain why Bloomberg's projected resets differ slightly from Optima's,
with evidence. Not to make the NPVs match by adjustment.

**Update (14-Oct-2026, later):** with the rate period starting 1 EN business day
after the reset date (OI-12; evidence from TC2), the first reset's window is
28-Aug-2026 → 25-Feb-2027 and its residual falls from −0.182 to −0.054 bp. Residuals
now −0.054 / −0.052 / −0.014 bp; NPV effects −0.138 / −0.140 / −0.033 (total −0.312 of
the −0.315 NPV difference). They equal 2.7e-6, 2.6e-6 and 0.7e-6 in the windows' DF
ratios (Optima 1.0006990 / 1.0013169 / 1.0010788 vs 1.0007017 / 1.0013195 /
1.0010795 implied by the Resets tab). The trace and candidate table below are for the
earlier window (31-Aug-2026 start) and are kept as history.

**Trace of the first reset (production path, QuantLib 1.43, 14-Oct-2026):**
- `fallback_rate` (`instruments/rates/irs/term_rate_leg.py:164-188`), from the
  sub-period start 31-Aug-2026. The 28-Aug-2026 reset date is only validated
  (`pricing_instrument.py:346`) and does not enter the rate.
  - 6M period: 31-Aug-2026 → 26-Feb-2027 (Modified Following, Swiss calendar).
  - Observation window, 2 Swiss business days earlier at each end: 27-Aug-2026 →
    24-Feb-2027, 181 days, 127 daily SARON values.
  - The compounded factor 1.000692547013455 equals DF(27-Aug-2026) / DF(24-Feb-2027)
    = 1.0001557829449323 / 0.9994636074085647 exactly (QuantLib telescopic forecast;
    the explicit daily product is identical). Compounded SARON 0.13774416%, plus
    0.0741% (`:216`), gives 0.21184416%.
  - Both DFs are linear-zero interpolations of curve 234:
    - 27-Aug-2026: 4M/5M pillars, weight 0.8, zero −0.038159%.
    - 24-Feb-2027: 10M/11M pillars, weight 0.785714, zero +0.059344%.
- **Payment P1 (31-Aug-2027)**, `flat_compounded_amount` (`:149-161`):
  - A1 = 52,000 × (0.21184416% + 0.20%) × 179/360 = 106.48459.
  - A2 = 144.01017 + cross term A1 × r2 × t2 = 0.18487, giving 144.19504.
  - P1 = 250.67964; equivalent coupon 0.4754724% over 365/360.
  - Sensitivity of P1 to the first reset: 2.590 per bp.
- **Discounting:** DF(31-Aug-2027) = 0.9980858973 gives PV 250.19981. The floating
  leg is 367.66987, the fixed leg −756.37602, NPV −388.70615. The engine and manual
  sums agree exactly.
- **Attribution of the NPV gap (−0.64615 vs Bloomberg −388.06).** Bloomberg's three
  resets were substituted in turn into the production compounding function, on
  Optima's DFs:

  | Reset | NPV effect |
  |---|---|
  | 28-Aug-2026 | −0.46941 |
  | 25-Feb-2027 | −0.14026 |
  | 27-Aug-2027 | −0.03311 |
  | **Total** | **−0.64278** |

  With all three Bloomberg resets the payments become 251.29048 and 117.97937
  (Bloomberg 251.29 and 117.98). The remainder, −0.00337, is within the 2-decimal
  display; it includes OI-14 (+0.0003).
- **In DF terms**, the first-reset gap is 9.13e-6 in DF(27-Aug-26) / DF(24-Feb-27):
  Optima 1.000692547 vs 1.000701677 implied by 0.21366%. The 5-decimal display
  bounds that implied ratio to ±2.5e-8.

**Candidates tested (scratch, 14-Oct-2026; hypothesis checks, not fits; no code
change).** Residual (Bloomberg − candidate, bp) for the resets 28-Aug-26 / 25-Feb-27
/ 27-Aug-27:

| Candidate | 28-Aug-26 | 25-Feb-27 | 27-Aug-27 |
|---|---|---|---|
| Current (6M from start, 2 Swiss bd shift, linear zero on spot + tenor pillars) | +0.18 | +0.05 | +0.01 |
| Window: shift 0 / 1 / 3 / 5 Swiss bd | −0.24 / +0.05 / +0.31 / +0.66 | −0.06 / −0.00 / +0.11 / +0.33 | +0.32 / +0.24 / −0.06 / −0.21 |
| Window: shift on UK calendar | +0.18 | +0.05 | −0.05 |
| Window: 6M anchored on the reset date | +0.26 | +0.11 | −0.12 |
| Window: 6M end unadjusted | +0.14 | +0.05 | +0.01 |
| Window: 2-day lookback without observation shift | +0.20 | +0.09 | +0.19 |
| Curve: log-linear DF, same pillars | +0.16 | −1.15 | +1.03 |
| Curve: linear zero, pillars at the file dates (reference + offset) | −0.59 | −1.23 | +1.47 |
| Curve: log-linear DF, pillars at the file dates | −0.59 | −2.19 | +2.25 |

No tested candidate removes the residual on all three resets; the current
definition is the closest overall. Neither explanation is excluded: an untested
window rule or an interpolation difference near the 4M-5M and 10M-11M segments
could still apply.

**What is not available:** Bloomberg's curve-234 DFs (or zero rates) at the
observation dates; Bloomberg's observation window for the first reset (the fixture
gives `effective_reset_date` only for the last reset of each period: 24-Aug-2027
and 25-Feb-2028, both of which match); unrounded reset rates.

**Status:** open. `latest_index` is not used and will not be introduced (SME,
14-Oct-2026).
**Required evidence (updated 14-Oct-2026):** curve-234 discount factors at
28-Aug-2026, 24-Feb-2027, 25-Feb-2027, 24-Aug-2027, 27-Aug-2027 and 25-Feb-2028, same
snapshot, at least 7 decimals (the remaining gaps are below 6-decimal display).
- Ratios equal to those implied by the Resets tab: the difference is in the curve
  between pillars.
- Ratios equal to Optima's: the curves agree; the difference is in compounding or in
  rounding of the published fallback rate.
The window question of the earlier request is answered by the TC2 evidence.

**Next action:** request the DFs (evidence register R1). No code change until the
evidence identifies the cause.

## OI-14: TC7 31-Jul-2028 discount factor

**Affected:** TC7 fixed and floating Period 2 (payment 31-Jul-2028).

**Observation:** Optima 0.9959637 vs Bloomberg 0.995966: −2.3e-6, outside the
5e-7 display tolerance. The 31-Aug-2027 DF agrees (0.9980859 vs 0.998086). The
date lies between the CHF 2Y pillar (3-Apr-2028) and the 3Y pillar (3-Apr-2029).
The curve is built from the supplied DFs (`scripts/build_chf_curve_snapshot.py`,
`market_data/2026-03-31/CHF/chf_saron_2026-03-31.json`) and reproduces curve 234's zero rates
within about ±0.02 bp at the pillars, so the residual is in the interpolation
between pillars, not at the pillars themselves.

**Related:** TC2's Bloomberg DFs past 18 months differ from the same curve by a
similar magnitude but the opposite sign (Optima − Bloomberg +2.5e-6 to +8.7e-6),
and USD has the comparable OI-1 and OI-7 residuals between the 18M and 3Y pillars.
Effect on TC7: under 0.001 on the Period 2 PVs (fixed −238.33, floating 117.95
payments × −2.3e-6).

**Status:** open; pinned as a known difference in
`test_irs_tc7_term_rate.py::test_payment_date_dfs_against_bloomberg` (3e-6 band).
**Required confirmation:** none from the SME yet; investigation first.
**Next action:** if the difference stays outside the agreed tolerance, investigate
the interpolation and pillar conventions between the 2Y and 3Y pillars (SWPM
"Piecewise Linear (Cont)" vs linear zero on ACT/365F; pillar dates) using
Bloomberg DFs at additional dates in that segment. Consider together with OI-1/OI-7.

## OI-15: INR curve and IRSWOF 6M (TC5, TC8, TC9)

**Curve (validated 14-Oct-2026).** `Market Rate` in
`market_data/2026-03-31/INR/market_data.json` is the OIS par rate (established).
Bootstrapped in QuantLib (`scripts/build_ois_curve_snapshots.py` →
`market_data/2026-03-31/INR/inr_mibor_2026-03-31.json`): T+0 on `ql.India` (spot 02-Apr-2026),
tenors up to 1Y a single payment, longer tenors semiannual, ACT/365F, linear zero.
It reproduces all ten of Bloomberg's TC5/TC8/TC9 payment-date DFs within 4.3e-7
(display 5e-7). Every other tested combination of settlement lag (T+0/1/2), calendar,
frequency and interpolation misses by at least 1.6e-5. The production curve equals the bootstrap to 2e-16 daily.

**Supplied DFs.** The file's `Discount Factor` column differs from that curve by
3.4e-4 to 1.5e-3 (e.g. 31-Mar-2027: supplied 0.940889, Bloomberg's trades 0.941231).
It is not the curve Bloomberg priced the trades with, and is not used; kept unchanged
as a reference. Used as an IRSWOF projection curve it is worse (up to 60 bp).

**IRSWOF 6M projection (provisional).** Simple ACT/365F forward over [reset + 2 India
business days, +6M Modified Following] on the INR OIS curve. Against Bloomberg's
fixture reset rates: TC8 28-Aug-2026 −0.0003 bp, TC9 29-Sep-2026 −0.20, 30-Mar-2027
−0.28, 29-Sep-2027 −0.0004 bp; TC5's Period 1 (two sub-resets, flat compounding)
reproduces Bloomberg's payment to the cent. Calendar `RB` → `ql.India`.

**Unresolved: reset periods shorter than 6M.** Bloomberg's rate is 23–39 bp below the
6M forward for every short reset period: TC5 P2 (3M, −22.8 bp), TC8 P3 (33 days,
−23.2), TC9 P1 (3M, −38.8; equal to TC9's `latest_index` 5.74185) and TC9 P8 (2M,
−28.2). A stub-length forward still misses by 10–24 bp. These account for the whole
TC5 (+1,963) and TC8 (+296) differences and almost all of TC9's (+1,876). With
Bloomberg's resets the production payment calculation reproduces Bloomberg's NPV
(TC8 within 0.05, TC9 within 0.013). No override is applied.

**Historical fixing:** TC8 Period 1 uses IRSWOF 27-Feb-2026 = 5.36% from the trade
record (OI-10); Periods 1 and 2 then match Bloomberg to the cent.

**Required:** SME — how SWPM sets IRSWOF for a reset period shorter than 6M, whether
TC9's first reset is projected or stored, and confirmation of the IRSWOF definition
(evidence register R6); an independent source for the TC8 fixing (R7).

## OI-16: JPY curve, +390-day row and TONA leg (TC6, TC10)

**Curve (validated 14-Oct-2026).** TONA OIS bootstrap from the par rates in
`market_data/2026-03-31/JPY/market_data.json` (`market_data/2026-03-31/JPY/jpy_tona_2026-03-31.json`):
T+2 on `ql.Japan`, single payment up to 1Y, annual above, ACT/365F, linear zero.

**+390-day row = 15M.** Read as 15M, the curve reproduces all five Bloomberg JPY
trade DFs within 1.0e-6; read as 13M/14M/16M/17M (or removed) it misses 30-Jun-2027
and 30-Jul-2027 by 9.6e-6 to 4.9e-4. The +21 and +630-day rows are 3W and 21M. The
supplied `Discount Factor` column again differs (up to 2.7e-3, at the +390-day row
itself; 6.5e-4 or less elsewhere) and is not used.

**TONA leg.** `MUTKCALM` 1D → `ql.Tonar`, daily compounding in arrears, lookback and
rate cutoff from the source (cutoff unmapped, OI-2), calendar `JN` → `ql.Japan`.
Coupons within 0.016 bp (TC6) and 0.002 bp (TC10). TC10's first period uses the
31-Mar-2026 TONA fixing 0.727% from market data (OI-10).

**Rounding.** Bloomberg shows whole-yen amounts (fixed amounts truncated:
−24,266.67 → −24,266, −12,333.33 → −12,333, −67,813.70 → −67,813), so the 0.05 payment
tolerance cannot be met on JPY cashflows; differences are within 3 yen per cashflow.

**Required:** confirm TONA 31-Mar-2026 against the Bank of Japan (R5); SME
confirmation of the `MUTKCALM` and `JN` mappings (low priority).

## OI-17: TC2 SARON observation-date method (Method A vs Method B)

**Status: Method A configured as a PROVISIONAL operational default (14-Oct-2026).** It is
not a Bloomberg- or SME-confirmed convention and has not been contractually validated.
Decision needed from management/SME: **R9**.

**Configuration:** trade input `floating_leg.term_rate.observation_dates`
(`instruments/rates/irs/term_rate_leg.py`):

| Value | Method | Observation window | Default |
|---|---|---|---|
| `contractual_accrual` | A | SARON over each contractual accrual sub-period [start, end), **no observation shift**; reset date and IBOR tenor not used | TC2 only (`scripts/build_trade_inputs.py`, `TC2_OBSERVATION_DATES`) |
| `reset_date_fallback` | B | IBOR period = reset + 1 EN business day, + 6M Modified Following (Swiss); SARON observed 2 Swiss business days earlier (OI-11, OI-12) | Used when the key is absent: TC7 and every other trade unchanged |

Both methods share the SARON fixing lookup (QuantLib index history from market data),
the compounding (`ql.OvernightIndexedCoupon`, compounded, ACT/360), the 0.0741% spread
adjustment and the 10 bp margin; only the observation dates differ. Benchmark (IBOR
period) fixings keyed by reset date apply to Method B only. Method A is accepted for
RFR-fallback benchmarks only (IRSWOF rejects it). Restoring Method B for TC2 is a
one-value change in the trade-input generator; no code change.

**Why no shift is an assumption.** TC2's trade data (`source/TC2.json`) has no
observation-shift, lookback or compounding term: its fallback terms are only
`ibor_fallback.opt_in: true`, `reset_type: "In Advance"`, index SF0006M 6M, the reset
dates, the SZ calculation calendar and Modified Following. The 2-day shift exists only
in Optima's provisional Method B definition. Method A's zero shift was chosen
operationally (user decision, 14-Oct-2026) because no shift is stated. Observing SARON in
arrears over the accrual period also sits uneasily with `reset_type: In Advance`.

**TC2 results (production; `scripts/irs_observation_methods.py`, report
`tc2_observation_methods.csv` and `cases/TC2.md`):**

| Measure | Method A | Method B | Bloomberg |
|---|---:|---:|---:|
| NPV | −153.3732 | not computable (needs SARON 29-Jan → 30-Mar-2026, R3) | −158.91 |
| NPV − Bloomberg | **+5.537** | – | – |
| Floating PV, P2–P8 | 60.3475 | 55.0119 | 55.18 |
| Coupons vs Bloomberg | −5.51 to +6.92 bp (all 8 differ) | P2–P8 within 0.14 bp | – |
| Observation end = Bloomberg effective reset date | 0 of 8 (A ends on the accrual end) | P2–P8 (7 of 7 computable); P1 differs by one day (R8) | – |

Fixed-leg PV −220.6027 vs −220.60 under both methods; four fixed-leg rows differ only
through CHF discount factors (5.5e-7 to 8.4e-6, PV ≤ 0.003 each; TC2-F4, not
investigated). Neither method is tuned to Bloomberg; tolerances are unchanged.

**Historical fixings:** Method A needs none (its earliest observation, 30-Apr-2026, is
after the valuation date). Method B needs SARON 29-Jan → 30-Mar-2026 for P1 (R3). No
fixings are fabricated; the synthetic SARON values in the tests are capability checks
only and never claim validation.

**Open:** R9 (convention decision, including Method A's shift if A is kept); R3 and R8
apply only if Method B is chosen.

