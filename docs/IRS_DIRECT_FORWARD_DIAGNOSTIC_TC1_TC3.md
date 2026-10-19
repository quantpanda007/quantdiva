# IRS Direct-Forward Diagnostic — TC1 and TC3

Read-only numerical comparison of (A) the current provisional projection-curve / QuantLib overnight-coupon path and (B) a direct simple-forward diagnostic. No production method is changed or selected here. Market Rate inputs are read from the USD market-data fixture, Bloomberg coupon/payment values from the case reference fixtures, and current Optima outputs from the existing baseline composition.

## 1. Methodology

For each contractual floating period, approach B uses the accrual-end/payment date as the interpolation target. It takes the two adjacent dated USD Market Rate observations surrounding that target and applies date-linear interpolation:

`R(T) = R0 + ((T - T0) / (T1 - T0)) * (R1 - R0)`

The fraction is elapsed calendar days divided by calendar days between the quoted dates, matching the Excel-style date interpolation previously inspected. The displayed rates are percentages. The diagnostic all-in coupon is:

`direct coupon (%) = interpolated Market Rate (%) + spread (bp) / 100`

Gearing is 1.0 in all these periods. The diagnostic cashflow is:

`notional * (direct coupon (%) / 100) * actual accrual days / 360`

This applies one interpolated simple rate to the entire contractual accrual period under ACT/360. It does not create daily fixings, daily compounding, or synthetic projection discount factors. It is an explicit comparison assumption, not a claim about Bloomberg's coupon calculation.

Approach A values below are the current coupon and cashflow from the existing QuantLib floating coupon using the provisional projection curve. The Bloomberg values are the recorded reference outputs. Coupon differences are in basis points; cashflow differences are absolute currency amounts. `Diff` means the stated approach minus Bloomberg.

## 2. TC1 period-by-period results

TC1 uses USD, ACT/360, 10 bp spread, and 1.0 gearing. Its normalized notional schedule is 530,000 then 265,000.

| Payment | Accrual | Notional | Market Rate brackets (%): lower → upper | Fraction | Interpolated Market Rate | Spread | Direct coupon | Bloomberg coupon | Direct − Bloomberg (bp) | Direct cashflow | Bloomberg cashflow | Direct − Bloomberg cashflow |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2027-05-28 | 2026-05-31 → 2027-05-28 | 530,000 | 2027-03-26: 3.70095 → 2027-09-22: 3.66000 | 0.350000 | 3.6866175% | 10 bp | 3.7866175% | 3.78546% | +0.115750 | 20,180.567599 | 20,174.40 | +6.167599 |
| 2027-11-30 | 2027-05-28 → 2027-11-30 | 265,000 | 2027-09-22: 3.66000 → 2028-03-30: 3.62105 | 0.363158 | 3.6458550% | 10 bp | 3.7458550% | 3.64025% | +10.560500 | 5,128.699804 | 4,984.11 | +144.589804 |

## 3. TC3 period-by-period results

TC3 uses USD, ACT/360, 70 bp spread, and 1.0 gearing. The period notionals are taken from the floating leg's Bloomberg schedule in the case fixture.

| Payment | Accrual | Notional | Market Rate brackets (%): lower → upper | Fraction | Interpolated Market Rate | Spread | Direct coupon | Bloomberg coupon | Direct − Bloomberg (bp) | Direct cashflow | Bloomberg cashflow | Direct − Bloomberg cashflow |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-11-30 | 2026-05-31 → 2026-11-30 | 790,000 | 2026-11-26: 3.69125 → 2026-12-26: 3.69490 | 0.133333 | 3.6917367% | 70 bp | 4.3917367% | 4.37572% | +1.601667 | 17,636.482497 | 17,572.15 | +64.332497 |
| 2027-05-28 | 2026-11-30 → 2027-05-28 | 592,500 | 2027-03-26: 3.70095 → 2027-09-22: 3.66000 | 0.350000 | 3.6866175% | 70 bp | 4.3866175% | 4.32764% | +5.897750 | 12,923.157931 | 12,749.40 | +173.757931 |
| 2027-11-30 | 2027-05-28 → 2027-11-30 | 395,000 | 2027-09-22: 3.66000 → 2028-03-30: 3.62105 | 0.363158 | 3.6458550% | 70 bp | 4.3458550% | 4.24025% | +10.560500 | 8,869.165746 | 8,653.64 | +215.525746 |
| 2028-04-28 | 2027-11-30 → 2028-04-28 | 197,500 | 2028-03-30: 3.62105 → 2029-03-30: 3.57805 | 0.079452 | 3.6176336% | 70 bp | 4.3176336% | 4.12404% | +19.359356 | 3,553.052618 | 3,393.74 | +159.312618 |

## 4. Current vs direct-forward comparison

| TC | Period / payment | Bloomberg coupon | Current Optima coupon | Direct-forward coupon | Current diff (bp) | Direct diff (bp) |
|---|---|---:|---:|---:|---:|---:|
| TC1 | P1 / 2027-05-28 | 3.785460% | 3.749740% | 3.786618% | -3.571958 | +0.115750 |
| TC1 | P2 / 2027-11-30 | 3.640250% | 3.505809% | 3.745855% | -13.444123 | +10.560500 |
| TC3 | P1 / 2026-11-30 | 4.375720% | 4.355461% | 4.391737% | -2.025895 | +1.601667 |
| TC3 | P2 / 2027-05-28 | 4.327640% | 4.273890% | 4.386618% | -5.374951 | +5.897750 |
| TC3 | P3 / 2027-11-30 | 4.240250% | 4.105254% | 4.345855% | -13.499599 | +10.560500 |
| TC3 | P4 / 2028-04-28 | 4.124040% | 4.002325% | 4.317634% | -12.171462 | +19.359356 |

## 5. Cashflow comparison

| TC | Period / payment | Bloomberg | Current Optima | Direct-forward diagnostic | Current − Bloomberg | Direct − Bloomberg | Direct − current |
|---|---|---:|---:|---:|---:|---:|---:|
| TC1 | P1 / 2027-05-28 | 20,174.40 | 19,984.033267 | 20,180.567599 | -190.366733 | +6.167599 | +196.534331 |
| TC1 | P2 / 2027-11-30 | 4,984.11 | 4,800.036514 | 5,128.699804 | -184.073486 | +144.589804 | +328.663290 |
| TC3 | P1 / 2026-11-30 | 17,572.15 | 17,490.805660 | 17,636.482497 | -81.344340 | +64.332497 | +145.676837 |
| TC3 | P2 / 2027-05-28 | 12,749.40 | 12,591.059452 | 12,923.157931 | -158.340548 | +173.757931 | +332.098478 |
| TC3 | P3 / 2027-11-30 | 8,653.64 | 8,378.139224 | 8,869.165746 | -275.500776 | +215.525746 | +491.026522 |
| TC3 | P4 / 2028-04-28 | 3,393.74 | 3,293.580261 | 3,553.052618 | -100.159739 | +159.312618 | +259.472357 |

## 6. What the diagnostic demonstrates

- For TC1 period 1, direct end-date interpolation plus the contractual 10 bp spread gives 3.7866175%, only 0.11575 bp above the displayed Bloomberg coupon. Its diagnostic payment is 6.17 above the Bloomberg payment.
- That close TC1 period-1 result does not repeat across the periods. Direct-forward coupons exceed Bloomberg in all six periods, by +0.11575 to +19.35936 bp. The largest gaps are the later TC3 periods and TC1 period 2.
- The current provisional QuantLib coupons are below Bloomberg for all six periods; the direct calculation is above Bloomberg for all six. Direct interpolation is numerically closer to Bloomberg in some periods, but not a general reproduction.
- Every direct diagnostic cashflow is above the corresponding Bloomberg payment. The first TC1 period is close; the other periods have larger positive differences.

## 7. What it does NOT demonstrate

- It does not establish that applying a reference-date-to-end-date simple forward directly across a coupon accrual period is the correct floating-leg convention.
- It does not model daily SOFR fixings, lookback, cutoff/lockout, in-arrears observation mechanics, or daily compounding. Those conventions are not represented by the one-rate ACT/360 diagnostic.
- It does not show that the current provisional projection curve is correct or incorrect beyond recording its current outputs.
- The close TC1 period-1 match is not evidence that Bloomberg used this formula. The period 2 and TC3 results show that the same procedure does not match the other displayed coupons.
- Bloomberg's supplied equivalent coupons and cashflows do not provide the daily observations needed to independently reconstruct the Bloomberg overnight coupon. For direct calculation, we assume the end date/payment date is the rate-interpolation target and apply the simple rate over the whole period; the source data do not uniquely establish that mapping from a reference-date forward to a coupon-period accrual.

## 8. Recommendation for the next investigation

Keep both calculations diagnostic. The next useful evidence is the Bloomberg/source-owner definition of `Equivalent Coupon` for these SOFR legs: specifically, whether it is a daily compounded overnight coupon, a forward-rate-derived simple coupon, or another measure; which date is the rate target; and exactly how spread, lookback, cutoff, and in-arrears settings enter. Until that is established, neither the near TC1 period-1 match nor the broader direct-forward differences justify selecting a production methodology.
