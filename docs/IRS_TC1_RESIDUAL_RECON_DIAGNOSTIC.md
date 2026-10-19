# TC1 / SLLSL9RR — Bloomberg Residual Reconciliation Diagnostic

**Status:** Diagnostic only. No production code, fixtures, or reference values changed.
**Update (09-Oct-2026, 15:07):** re-run in the Optima environment (QuantLib 1.41) — see §8. Results below are QuantLib 1.43 unless stated.
**Date:** 09-Oct-2026 · **QuantLib (diagnostic env):** 1.43 · **Script:** `scripts/diag_tc1_bloomberg_recon.py`

## 1. Conclusion

With the reconstructed SOFR curve (T+2 spot + tenor, Mod Following, continuous ACT/365F zeros, linear-in-zero) and Bloomberg's source observation terms (**lookback 0**, cutoff 1, spread outside compounding), Optima's production QuantLib builders reproduce Bloomberg to:

| | Optima (V3) | Bloomberg | Diff |
|---|---:|---:|---:|
| P1 coupon | 3.785456% | 3.78546% | −0.000 bp |
| P2 coupon | 3.639715% | 3.64025% | −0.053 bp |
| Floating PV | 24,023.05 | 24,023.74 | −0.69 |
| Fixed PV | −31,978.76 | −31,978.74 | −0.02 |
| **NPV** | **−7,955.71** | **−7,955.00** | **−0.71** |

The whole remaining residual is traced to **one number**: the curve DF at **30-Nov-2027**. Optima gives 0.9410946. Bloomberg's displayed payment DF is 0.941092, and its P2 coupon independently implies a projection DF of 0.9410922, so Bloomberg's two outputs agree with each other. The gap of 2.4e-6 equals a zero-rate difference of about **+0.16 bp** at that date (3.63871% vs 3.63887%). Input rounding does not explain it. Its cause **cannot be identified from the data supplied**; see §5.

## 2. Confirmed findings

1. **Lookback must be 0, but the case fixture has 1.** `source/TC1.json` gives `days_before_accrual: 0`, while `cases/TC1.json` has `lookback_days: 1`. Using lookback 1 shifts P1 by +0.045 bp and the floating PV by +2.78 (V1). Using lookback 0 reproduces P1 to 0.0005 bp (V2/V3). **The fixture needs correcting. It was not changed here.**
2. **Spread is added outside compounding (`ExcludeSprd` → `compoundSpreadDaily=False`).** V3 matches P1 within display precision (±0.0005 bp). Compounding the spread daily would move P1 by roughly +0.19 bp, an arithmetic estimate flagged as such.
3. **Single curve.** The same curve for projection and discounting reproduces both payment DFs and P1. Fixed-leg PV is within 0.02 of Bloomberg.
4. **Linear interpolation of zero rates is required.** Cubic, monotone-cubic and log-linear DF schemes all break the exact P1 / 28-May-27 match by 0.16–0.33 bp (V5–V7).
5. **Bloomberg's displays are internally consistent.** N × coupon × τ equals the payment to within 0.01 in both periods, and the P2 coupon and payment DF imply the same DF at 30-Nov-27 (0.9410922 vs 0.941092).
6. **Residual decomposition (V3):** the P2 coupon (projection) effect is −0.690. All discount-factor effects are below 0.02 in absolute terms. So the residual comes through projection, at the P2 end date.

## 3. Variant results

All variants use Optima's `build_fixed_leg`, `build_floating_leg`, `translate_leg_schedule`, `assemble_quantlib_irs` and `attach_discounting_engine`. Only the curve handles change, plus, for the cutoff and spread variants, the single `ql.OvernightLeg` argument named. All values are QuantLib outputs.

| Variant | P1 cpn (bp vs BBG) | P2 cpn (bp) | P1 / P2 pay diff | P1 / P2 DF diff | Float PV | Fixed PV | NPV | dNPV |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| V0 Production curves, fixture conventions (lb 1, lockout 0) | −2.523 | −13.444 | −134.45 / −184.07 | −8.0e-4 / −7.6e-4 | 23,702.09 | −31,952.36 | −8,250.27 | −295.27 |
| V1 Reconstructed curve, lb 1, lockout 0 | +0.045 | +0.035 | +2.41 / +0.48 | −2.4e-7 / +2.6e-6 | 24,026.52 | −31,978.76 | −7,952.24 | +2.76 |
| V2 Reconstructed, **lb 0**, lockout 0 | −0.000 | −0.054 | −0.03 / −0.74 | same | 24,023.04 | −31,978.76 | −7,955.73 | −0.73 |
| **V3 Reconstructed, lb 0, lockout 1** | **−0.000** | **−0.053** | **−0.02 / −0.73** | same | **24,023.05** | **−31,978.76** | **−7,955.71** | **−0.71** |
| V4 V3 + compoundSpreadDaily=True | −9.943 | −9.999 | −529.91 / −136.90 | same | 23,387.11 | −31,978.76 | −8,591.66 | −636.66 |
| V5 V3, cubic zero | +0.158 | −0.148 | +8.44 / −2.02 | −1.5e-5 / −7.7e-6 | 24,029.59 | −31,978.29 | −7,948.70 | +6.30 |
| V6 V3, monotone-cubic zero | +0.315 | −0.447 | +16.79 / −6.12 | −3.0e-5 / −7.8e-6 | 24,033.44 | −31,977.90 | −7,944.46 | +10.54 |
| V7 V3, log-linear on supplied DFs | −0.328 | −0.497 | −17.50 / −6.81 | +3.0e-5 / +5.3e-5 | 24,001.44 | −31,979.90 | −7,978.46 | −23.46 |
| V8 V3, zeros implied from 6dp DFs | −0.003 | −0.052 | −0.15 / −0.72 | −4.2e-7 / +2.3e-6 | 24,022.94 | −31,978.76 | −7,955.82 | −0.82 |
| V9 V3, 18M/2Y zeros ±0.5e-5% (4 corners) | −0.001…0.000 | −0.055…−0.052 | ≤0.03 / −0.75…−0.72 | +2.5e-6…+2.6e-6 | 24,023.03….08 | −31,978.76 | −7,955.74…−7,955.69 | −0.74…−0.69 |

Bloomberg: coupons 3.78546% / 3.64025%; payments 20,174.40 / 4,984.11; DFs 0.958306 / 0.941092; Float +24,023.74; Fixed −31,978.74; NPV −7,955.00.

Observation schedule under V3 (QL `Sofr` index, US SOFR calendar):
- P1: 249 fixings, first fixing 29-May-26, last fixing 26-May-27, repeated for 27→28-May.
- P2: 125 fixings, 28-May-27 → 26-Nov-27, last value date 30-Nov-27.

The accrual start falls on Sunday 31-May-26, and QuantLib still accrues from 31-May. P1 matches to 0.0005 bp, which a 29-May start would break by about 2 bp.

## 4. Hypotheses tested and rejected

| Hypothesis | Evidence | Verdict |
|---|---|---|
| Residual from 30-Nov DF *discounting* | DF effect +0.013 on floating, −0.018 on fixed | Rejected as the main driver; immaterial |
| Zero-rate input rounding (5 dp) | V9 envelope moves DF(30-Nov) by ≤1e-7; the gap is 2.4e-6 | Rejected |
| DF-column precision (6 dp) instead of Zero column | V8: residual unchanged (−0.82) | Rejected |
| Non-linear zero interpolation | V5/V6 break the P1 exact match | Rejected |
| Log-linear DF interpolation | V7: P1 off 0.33 bp, NPV off 23 | Rejected |
| Linear in simple or annual-compounded zero | Same DFs as continuous to 7 dp | Not a differentiator |
| Lookback 1 (as in case fixture) | V1: P1 +0.045 bp; contradicts the source's `days_before_accrual: 0` | Rejected |
| Bloomberg coupon/payment/DF internally inconsistent | Consistent to within 0.01 / 2e-7 | Rejected |

## 5. Hypotheses still open

1. **Bloomberg curve shape between 18M (04-Oct-27) and 2Y (03-Apr-28).** 28-May-27, between the 12M and 18M pillars, matches exactly; 30-Nov-27, between 18M and 2Y, is 0.16 bp high in zero. Candidates, none testable with current data:
   - (a) Bloomberg curve 490 has members not in the 20-row export, such as futures or a 21M swap.
   - (b) A different interpolation rule applies in that segment only.
   - (c) An off-pillar zero is computed differently.
2. **Cutoff = QL lockout?** V2 and V3 differ by only 0.001 bp, below Bloomberg's display precision. They can't be told apart from TC1. Bloomberg's `effective_reset_date` (27-May-27 / 29-Nov-27) is the business day before period end under both readings, so it doesn't discriminate either. **Immaterial here, but still unconfirmed.**
3. ~~Production baseline not reproduced~~ — **resolved in §8**: it is a QuantLib version effect.
4. **QL `compoundSpreadDaily=True` output (V4) appears to drop the spread.** The coupon falls by about 10 bp instead of rising by about 0.2 bp. This doesn't affect the conclusion, since production uses False, but it's worth a QL check before relying on that flag for any currency.

## 6. Additional evidence required

1. **From Bloomberg (SWPM / ICVS for curve 490, 31-Mar-2026):**
   - The full curve member list, with instrument, tenor and maturity, to confirm or exclude hidden pillars between 18M and 2Y.
   - The zero rate and DF at 30-Nov-2027 at full precision, as a single off-pillar proof point.
   - Optionally, Bloomberg's projected daily SOFR for P2's last 3 business days, to settle the cutoff mapping.
2. **From the Optima environment:** run `python scripts/diag_tc1_bloomberg_recon.py` and record the QuantLib version and V0 output. This resolves open item 3.
3. **Fixture decision (owner review):** correct `cases/TC1.json` `observation.lookback_days` from 1 to 0, citing `source/TC1.json` `days_before_accrual: 0`.

## 7. Reproducibility record

- **Command:** `python scripts/diag_tc1_bloomberg_recon.py` (run from the `quantlib-pricing` root).
- **Files added:**
  - `scripts/diag_tc1_bloomberg_recon.py`
  - `docs/IRS_TC1_RESIDUAL_RECON_DIAGNOSTIC.md`
- **Files changed:** none.
- **Inputs:**
  - `market_data/2026-03-31/USD/market_data.json` (DF and Market Rate).
  - The Zero Rate column, supplied in chat and embedded in the script because it isn't in the repo fixture.
  - Trade terms from `cases/TC1.json`, with lookback varied as stated.
- **Assumptions:**
  - Tenor list 1W–3W, 1M–12M, 18M, 2Y–5Y, inferred blind and validated on all 20 rows.
  - First zero flat-extrapolated back to the reference date.
  - Evaluation date 31-Mar-26; no historical fixings needed.
- **No hardcoded adjustments:** every coupon, payment, DF and PV is QuantLib output. Bloomberg values are used only for comparison. The one exception is the implied-DF inversion in §1, which is an explicitly labelled arithmetic check.

## 8. Optima environment cross-check (QuantLib 1.41)

The same script run in the Optima environment reproduces the documented production baseline **exactly** (V0 NPV −8,303.80, 248 fixings). That confirms the script is faithful to production. One result changes materially between versions:

| V3 (lb 0, lockout 1) | QL 1.43 | QL 1.41 | Bloomberg |
|---|---:|---:|---:|
| P1 first fixing (accrual starts Sun 31-May-26) | 29-May-26, 249 fixings | **01-Jun-26**, 248 fixings | — |
| P1 coupon | 3.785456% (−0.000 bp) | 3.774949% (**−1.051 bp**) | 3.78546% |
| P1 payment | 20,174.38 | 20,118.38 (−56.02) | 20,174.40 |
| P2 coupon / DFs / fixed PV | identical | identical | — |
| NPV | −7,955.71 | −8,009.37 (−54.37) | −7,955.00 |

- **Confirmed:** In QL 1.41 the overnight coupon whose accrual starts on a non-business day begins compounding at the next business day (01-Jun) but still accrues over 362 days, so the interest for Sun 31-May is lost. One day at about 3.7% / 362 ≈ 1.02 bp matches the −1.05 bp. QL 1.43 applies the preceding business day's fixing (29-May) to 31-May→01-Jun, which is what Bloomberg's P1 coupon reflects (match to 0.0005 bp).
- **Not established:** which release between 1.41 and 1.43 changed this behaviour; 1.42 was not tested.
- The V4 `compoundSpreadDaily=True` anomaly (spread appears dropped) is present in both versions.

**Implication for the production change (for review, not implemented):** the methodology fix needs QuantLib ≥ 1.43, or a verified equivalent. Pin the version, and add a TC1 Period-1 coupon regression test (tolerance 0.1 bp) so a version change cannot silently reintroduce the 1 bp / $54 error.
