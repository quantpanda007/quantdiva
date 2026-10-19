# Floating-Leg Forensics — TC1 and TC3

## Scope and comparison conventions

This is a read-only comparison of the frozen Bloomberg references and the current fresh IRS component path. No pricing code, test, fixture, reference value, curve, or QuantLib convention was changed. Optima minus Bloomberg is used for all differences.

Bloomberg coupon values are stated in percent and are divided by 100 for rate arithmetic. Optima's `OvernightIndexedCoupon.rate()` is already a decimal rate. Floating cashflows and PVs are shown Receive-positive. TC1 uses the normalized canonical notional schedule, 530,000 then 265,000; its raw Bloomberg cashflow `notional` fields still contain the known residual 530,000,000 and 265,000,000 values. TC1's raw notionals are therefore not used to infer its economic coupon basis. The Bloomberg payments and NPVs are left unchanged.

For cashflow-rate decomposition, the rate component is `N * (Optima rate - Bloomberg equivalent coupon) * actual days / 360`, using the shared canonical notional and accrual period. Any remaining payment difference is shown as source coupon/payment precision residual. The PV decomposition is described in Section 3.

## 1. TC1 period comparison

| Pay date | Accrual start → end | Days | Period notional used | Bloomberg equivalent coupon | Optima coupon | Rate diff (bp) | Bloomberg cashflow | Optima cashflow | Cashflow diff | Bloomberg DF | Optima DF | DF diff | Bloomberg PV | Optima PV | PV diff |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2027-05-28 | 2026-05-31 → 2027-05-28 | 362 | 530,000 | 3.78546% | 3.749740423% | -3.571958 | 20,174.40 | 19,984.033267 | -190.366733 | 0.958306 | 0.957509777 | -0.000796223 | 19,333.24 | 19,134.907243 | -198.332757 |
| 2027-11-30 | 2027-05-28 → 2027-11-30 | 186 | 265,000 | 3.64025% | 3.505808775% | -13.444123 | 4,984.11 | 4,800.036514 | -184.073486 | 0.941092 | 0.940335927 | -0.000756073 | 4,690.50 | 4,513.646784 | -176.853216 |

Dates, period notionals, and day counts agree with the normalized TC1 contractual schedule. The raw reference cashflow notional field has the scale conflict described above; the cashflow amounts and canonical schedule support the 530,000 → 265,000 notional basis used in this arithmetic comparison.

## 2. TC3 period comparison

| Pay date | Accrual start → end | Days | Period notional | Bloomberg equivalent coupon | Optima coupon | Rate diff (bp) | Bloomberg cashflow | Optima cashflow | Cashflow diff | Bloomberg DF | Optima DF | DF diff | Bloomberg PV | Optima PV | PV diff |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-11-30 | 2026-05-31 → 2026-11-30 | 183 | 790,000 | 4.37572% | 4.355461048% | -2.025895 | 17,572.15 | 17,490.805660 | -81.344340 | 0.975591 | 0.974962045 | -0.000628955 | 17,143.23 | 17,052.871664 | -90.358336 |
| 2027-05-28 | 2026-11-30 → 2027-05-28 | 179 | 592,500 | 4.32764% | 4.273890487% | -5.374951 | 12,749.40 | 12,591.059452 | -158.340548 | 0.958306 | 0.957509777 | -0.000796223 | 12,217.83 | 12,056.062532 | -161.767468 |
| 2027-11-30 | 2027-05-28 → 2027-11-30 | 186 | 395,000 | 4.24025% | 4.105254009% | -13.499599 | 8,653.64 | 8,378.139224 | -275.500776 | 0.941092 | 0.940335927 | -0.000756073 | 8,143.87 | 7,878.265311 | -265.604689 |
| 2028-04-28 | 2027-11-30 → 2028-04-28 | 150 | 197,500 | 4.12404% | 4.002325380% | -12.171462 | 3,393.74 | 3,293.580261 | -100.159739 | 0.927854 | 0.927528025 | -0.000325975 | 3,148.90 | 3,054.887996 | -94.012004 |

TC3 accrual dates, payment dates, notionals, and ACT/360 day counts match the detailed Bloomberg periods by payment date.

## 3. Difference decomposition

### A. Rate difference

Optima's equivalent coupon is lower than Bloomberg's for every compared period. The differences range from **-2.025895 bp** (TC3 period 1) to **-13.499599 bp** (TC3 period 3). The Optima coupon is the overnight coupon's public `rate()` result, including the floating spread.

### B–C. Cashflow difference: rate versus notional/accrual

| Case / period | Optima − Bloomberg cashflow | Rate-only cashflow effect | Remaining source precision residual | Notional/accrual effect from supplied period terms |
|---|---:|---:|---:|---:|
| TC1 P1 | -190.366733 | -190.365499 | -0.001233 | 0 under normalized schedule |
| TC1 P2 | -184.073486 | -184.072444 | -0.001042 | 0 under normalized schedule |
| TC3 P1 | -81.344340 | -81.356573 | +0.012233 | 0 |
| TC3 P2 | -158.340548 | -158.348306 | +0.007758 | 0 |
| TC3 P3 | -275.500776 | -275.504318 | +0.003542 | 0 |
| TC3 P4 | -100.159739 | -100.160989 | +0.001250 | 0 |

The rate-only amount uses the shared notional, actual-day count, and ACT/360. The small residuals are the differences between the Bloomberg payment values and the amount implied by its displayed equivalent coupon at the displayed precision. No notional/accrual contribution appears for the normalized TC1 schedule or TC3. The raw TC1 oracle nominal field is inconsistent in scale, so it cannot be used as a second economic notional without contradicting the confirmed canonical case.

### D. Discount-factor difference

Optima's current discount curve returns a lower DF than Bloomberg at all six matched payment dates. The absolute DF differences range from **-0.000325975** to **-0.000796223**. These are payment-date values from the current curve; no interpolation methodology was changed for this analysis.

### E. PV difference

| Case / period | PV diff | Coupon-rate contribution at Bloomberg DF | Discounting contribution using Optima cashflow | Source cashflow precision contribution | Bloomberg PV field residual |
|---|---:|---:|---:|---:|---:|
| TC1 P1 | -198.332757 | -182.428400 | -15.911741 | -0.001182 | +0.008566 |
| TC1 P2 | -176.853216 | -173.229105 | -3.629180 | -0.000980 | +0.006048 |
| TC3 P1 | -90.358336 | -79.370740 | -11.000921 | +0.011935 | +0.001391 |
| TC3 P2 | -161.767468 | -151.746132 | -10.025288 | +0.007435 | -0.003484 |
| TC3 P3 | -265.604689 | -259.274910 | -6.334488 | +0.003333 | +0.001375 |
| TC3 P4 | -94.012004 | -92.934774 | -1.073623 | +0.001160 | -0.004766 |

The decomposition is additive, subject to displayed precision. “Coupon-rate contribution” is the rate-only cashflow effect multiplied by Bloomberg's DF. “Discounting contribution” is Optima's cashflow multiplied by `(Optima DF - Bloomberg DF)`. The two source-precision terms account for the displayed Bloomberg coupon/payment and PV rounding. Thus both lower Optima coupons and lower Optima DFs contribute to the lower Optima PVs; the rate contribution is larger in each period.

## 4. Current QuantLib construction

The findings below describe the code in `instruments/rates/irs/floating_leg.py`, `instruments/rates/irs/quantlib_schedule.py`, `market/curves/irs_provisional_projection.py`, `market/curves/irs_market_data.py`, and `instruments/rates/irs/engine.py`.

- **Index:** `build_floating_index` accepts only `('SOFRRATE', '1D', 'USD', Frequency.DAILY)` and constructs `ql.Sofr(forwarding_curve)`. QuantLib reports the index as `SOFRON Actual/360`, currency USD, zero fixing days, and its SOFR fixing calendar. TC1 uses the raw Bloomberg benchmark identifier in this current mapping; the normalized case value `SOFR` is not accepted directly.
- **Projection handle:** the diagnostic path uses the explicitly provisional builder. It divides displayed rates by 100, derives synthetic projection DFs as `1 / (1 + rate * Actual/360(reference, pillar))`, then uses `ql.DiscountCurve` and a `YieldTermStructureHandle`. This handle is supplied to the SOFR index. This report does not endorse or change that methodology.
- **Discount handle:** supplied discount-factor observations are passed to a separate `ql.DiscountCurve` with `Actual360`; the handle is attached through `ql.DiscountingSwapEngine`. The current three-argument `DiscountCurve` uses its LogLinear interpolation default.
- **Schedule and cashflows:** `translate_leg_schedule` constructs an explicit-date `ql.Schedule` from the contractual accrual boundaries using `NullCalendar` and `Unadjusted`. `build_floating_leg` passes per-period notionals, explicit payment dates, zero payment lag, `NullCalendar`, and `Unadjusted` to `ql.OvernightLeg`. The assembled instrument is a `ql.Swap` of explicit fixed and floating `ql.Leg` objects, not an `OvernightIndexedSwap` generated from one shared schedule.
- **Observation settings:** current TC1 settings are lookback 1 day, `inArrears=True`; TC3 settings are lookback 0 days, `inArrears=True`. Both record cutoff 1 day but map it to `lockoutDays=0` (`cutoff_mapping=None`). `applyObservationShift=False`.
- **Compounding/spread:** averaging is `ql.RateAveraging.Compound`. `compoundSpreadDaily=False`, so the spread is excluded from daily compounding. Gearing is 1.0; spread is 10 bp for TC1 and 70 bp for TC3. The resulting public coupon `rate()` includes the spread.
- **Observed date counts:** TC1 has 248 and 125 fixing dates across its two periods. TC3 has 124, 124, 125, and 104 fixing dates. The dates below are the first and last five `fixingDates()` from the actual constructed coupons. The final value-date endpoint is also shown.

| Case / period | Fixing-date first five | Fixing-date last five | First → last value date |
|---|---|---|---|
| TC1 P1 | 2026-05-29, 2026-06-01, 2026-06-02, 2026-06-03, 2026-06-04 | 2027-05-20, 2027-05-21, 2027-05-24, 2027-05-25, 2027-05-26 | 2026-05-29 → 2027-05-27 |
| TC1 P2 | 2027-05-27, 2027-05-28, 2027-06-01, 2027-06-02, 2027-06-03 | 2027-11-19, 2027-11-22, 2027-11-23, 2027-11-24, 2027-11-26 | 2027-05-27 → 2027-11-29 |
| TC3 P1 | 2026-06-01, 2026-06-02, 2026-06-03, 2026-06-04, 2026-06-05 | 2026-11-20, 2026-11-23, 2026-11-24, 2026-11-25, 2026-11-27 | 2026-06-01 → 2026-11-30 |
| TC3 P2 | 2026-11-30, 2026-12-01, 2026-12-02, 2026-12-03, 2026-12-04 | 2027-05-21, 2027-05-24, 2027-05-25, 2027-05-26, 2027-05-27 | 2026-11-30 → 2027-05-28 |
| TC3 P3 | 2027-05-28, 2027-06-01, 2027-06-02, 2027-06-03, 2027-06-04 | 2027-11-22, 2027-11-23, 2027-11-24, 2027-11-26, 2027-11-29 | 2027-05-28 → 2027-11-30 |
| TC3 P4 | 2027-11-30, 2027-12-01, 2027-12-02, 2027-12-03, 2027-12-06 | 2028-04-21, 2028-04-24, 2028-04-25, 2028-04-26, 2028-04-27 | 2027-11-30 → 2028-04-28 |

## 5. Common pattern between TC1 and TC3

- Both use USD SOFR 1D, a QuantLib SOFR index, distinct projection and discount handles, daily overnight coupons, in-arrears observation, compound averaging, 1.0 gearing, and spread excluded from daily compounding.
- Every compared Optima equivalent coupon is below the Bloomberg equivalent coupon.
- Every matched Optima payment-date DF is below the Bloomberg DF.
- Contractual accrual/payment dates and period-notional magnitudes match for the compared periods. TC1's raw oracle notional fields are the known scale exception; TC3 source cashflow notionals match period notionals by magnitude.
- The cashflow amount difference is almost entirely accounted for by the coupon-rate difference, with only small residuals at the precision supplied in Bloomberg's coupons/payments.
- Both coupon-rate and discount-factor differences reduce Optima floating-leg PV relative to the Bloomberg detailed cashflow PV.

## 6. What the evidence rules out

- A period-date mismatch does not explain the measured TC1/TC3 floating differences: the detailed accrual and payment dates agree.
- A period-notional magnitude or ACT/360 accrual-day mismatch does not explain the TC3 amounts, nor the normalized TC1 amounts. The raw TC1 cashflow-notional fields are inconsistent in scale with the confirmed trade and cashflow amount; they are preserved as an oracle-source discrepancy, not used as the applied notional.
- Discounting alone cannot explain the cashflow differences: coupon amounts already differ before discounting, and the computed rate-only cashflow effect accounts for nearly all of each cashflow difference.
- Coupon rates alone cannot explain the PV differences: payment-date DFs also differ, and their calculated contribution is nonzero in every compared period.
- The same discrepancy direction appears in both TC1 and TC3 despite their different spreads, accrual frequencies, notionals, and lookback settings. Therefore, the evidence does not isolate the issue to TC1's single trade terms.

## 7. What remains unresolved

- The fixtures provide Bloomberg equivalent coupons and payments, but do not provide the daily Bloomberg SOFR fixings/forwards used for each overnight observation. The supplied period-end or curve observations do not establish those daily coupon inputs.
- The current mapping retains the one-day cutoff but does not apply it as a QuantLib lockout (`lockoutDays=0`). This documents the implementation behavior; the comparison alone does not establish how Bloomberg's cutoff was applied.
- The projection construction used here is explicitly provisional. This comparison measures its output but does not determine the intended Bloomberg projection-curve conversion.
- Bloomberg's TC1 raw cashflow notional fields remain at the residual million-scale values while the clarified canonical trade is 530,000 → 265,000. The source fields were not normalized here.
- The supplied Bloomberg cashflow PVs are rounded and do not always equal the displayed cashflow multiplied by the displayed DF at full precision. The small PV residuals are reported separately; their unrounded source calculation is unavailable.

