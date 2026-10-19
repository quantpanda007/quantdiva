# Current IRS Pricing Baseline — TC1–TC10

Diagnostic baseline for the existing fresh IRS component path. No production pricing code, fixture, market data, or reference values were changed. The supported cases are composed from the repository's fixed/floating leg builders, discount curve, explicitly provisional projection curve, QuantLib swap, and discounting engine. There is not yet a general IRS PricingService adapter for these fixtures.

Projection inputs use the existing provisional projection-curve builder. This report records current behavior; it does not validate that methodology against Bloomberg.

## 1. Execution status

| TC | Currency | Trade ID | Status | Reason when unsupported |
|---|---|---|---|---|
| TC1 | USD | SLLSL9RR | priced | — |
| TC2 | CHF | SLLSL9SL | unsupported | unsupported mapping (CHF, SF0006M, 6M, SemiAnnual); fresh floating-index builder supports only SOFRRATE/1D/USD/Daily; no alternate currency/benchmark mapping is implemented |
| TC3 | USD | SLLSL90 | priced | — |
| TC4 | USD | SLLSL9RX | priced | — |
| TC5 | INR | SLLSL9S9 | unsupported | unsupported mapping (INR, IRSWOF, 6M, SemiAnnual); fresh floating-index builder supports only SOFRRATE/1D/USD/Daily; no alternate currency/benchmark mapping is implemented |
| TC6 | JPY | SLLSL9SC | unsupported | unsupported mapping (JPY, MUTKCALM, 1D, Daily); fresh floating-index builder supports only SOFRRATE/1D/USD/Daily; no alternate currency/benchmark mapping is implemented |
| TC7 | CHF | SLLSL9SI | unsupported | unsupported mapping (CHF, SF0006M, 6M, SemiAnnual); fresh floating-index builder supports only SOFRRATE/1D/USD/Daily; no alternate currency/benchmark mapping is implemented |
| TC8 | INR | SLLSL9S6 | unsupported | unsupported mapping (INR, IRSWOF, 6M, SemiAnnual); fresh floating-index builder supports only SOFRRATE/1D/USD/Daily; no alternate currency/benchmark mapping is implemented |
| TC9 | INR | SLLSL9S3 | unsupported | unsupported mapping (INR, IRSWOF, 6M, SemiAnnual); fresh floating-index builder supports only SOFRRATE/1D/USD/Daily; no alternate currency/benchmark mapping is implemented |
| TC10 | JPY | SLLSL9SF | unsupported | unsupported mapping (JPY, MUTKCALM, 1D, Daily); fresh floating-index builder supports only SOFRRATE/1D/USD/Daily; no alternate currency/benchmark mapping is implemented |

## 2. NPV comparison

Differences are Optima minus Bloomberg. Bloomberg NPVs are taken from the detailed cashflow NPV fields in each reference fixture; separate market-summary/leg-summary NPVs are retained in the oracle reconnaissance report and are not substituted here.

| TC | Currency | Bloomberg Fixed NPV | Optima Fixed NPV | Diff | Bloomberg Float NPV | Optima Float NPV | Diff | Bloomberg Total NPV | Optima Total NPV | Diff | Status |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| TC1 | USD | -31978.740000 | -31952.358846 | 26.381154 | 24023.740000 | 23648.554027 | -375.185973 | -7955.000000 | -8303.804820 | -348.804820 | priced |
| TC2 | CHF | — | — | — | — | — | — | — | — | — | unsupported |
| TC3 | USD | -18850.360000 | -18836.991911 | 13.368089 | 40653.830000 | 40042.087503 | -611.742497 | 21803.470000 | 21205.095591 | -598.374409 | priced |
| TC4 | USD | -22362.490000 | -22351.023091 | 11.466909 | 17714.640000 | 17705.579346 | -9.060654 | -4647.850000 | -4645.443746 | 2.406254 | priced |
| TC5 | INR | — | — | — | — | — | — | — | — | — | unsupported |
| TC6 | JPY | — | — | — | — | — | — | — | — | — | unsupported |
| TC7 | CHF | — | — | — | — | — | — | — | — | — | unsupported |
| TC8 | INR | — | — | — | — | — | — | — | — | — | unsupported |
| TC9 | INR | — | — | — | — | — | — | — | — | — | unsupported |
| TC10 | JPY | — | — | — | — | — | — | — | — | — | unsupported |

## 3. Cashflow comparison

Payment-date matching is used. Bloomberg source notionals, payment amounts, and PVs retain their supplied signs; QuantLib leg coupon amounts are signed as Pay negative / Receive positive for comparison. A dash means the reference has no detailed cashflow for that date, a historical fixing is missing, or the engine excludes a cashflow paid on the valuation date. Optima discount factors are queried from the current direct discount curve. Accrual dates are those exposed by the QuantLib coupon objects.

| TC | Leg | Accrual start | Accrual end | Pay date | Bloomberg signed notional | Optima nominal | Bloomberg equivalent coupon | Optima coupon | Bloomberg signed amount | Optima signed amount | Bloomberg DF | Optima DF | Bloomberg signed PV | Optima signed PV |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| TC1 | Fixed (Pay) | 2026-05-31 | 2027-05-28 | 2027-05-28 | -530000000.000000 | 530000.000000 | — | 0.050000 | -26647.220000 | -26647.222222 | 0.958306 | 0.957510 | -25536.190000 | -25514.975815 |
| TC1 | Fixed (Pay) | 2027-05-28 | 2027-11-30 | 2027-11-30 | -265000000.000000 | 265000.000000 | — | 0.050000 | -6845.830000 | -6845.833333 | 0.941092 | 0.940336 | -6442.560000 | -6437.383031 |
| TC1 | Floating (Receive) | 2026-05-31 | 2027-05-28 | 2027-05-28 | 530000000.000000 | 530000.000000 | 3.785460 | 0.037497 | 20174.400000 | 19984.033267 | 0.958306 | 0.957510 | 19333.240000 | 19134.907243 |
| TC1 | Floating (Receive) | 2027-05-28 | 2027-11-30 | 2027-11-30 | 265000000.000000 | 265000.000000 | 3.640250 | 0.035058 | 4984.110000 | 4800.036514 | 0.941092 | 0.940336 | 4690.500000 | 4513.646784 |
| TC3 | Fixed (Pay) | 2026-05-31 | 2026-11-30 | 2026-11-30 | -790000.000000 | 790000.000000 | 2.000000 | 0.020000 | -8031.670000 | -8031.666667 | 0.975591 | 0.974962 | -7835.620000 | -7830.570162 |
| TC3 | Fixed (Pay) | 2026-11-30 | 2027-05-28 | 2027-05-28 | -592500.000000 | 592500.000000 | 2.000000 | 0.020000 | -5892.080000 | -5892.083333 | 0.958306 | 0.957510 | -5646.420000 | -5641.727400 |
| TC3 | Fixed (Pay) | 2027-05-28 | 2027-11-30 | 2027-11-30 | -395000.000000 | 395000.000000 | 2.000000 | 0.020000 | -4081.670000 | -4081.666667 | 0.941092 | 0.940336 | -3841.220000 | -3838.137807 |
| TC3 | Fixed (Pay) | 2027-11-30 | 2028-04-28 | 2028-04-28 | -197500.000000 | 197500.000000 | 2.000000 | 0.020000 | -1645.830000 | -1645.833333 | 0.927854 | 0.927528 | -1527.090000 | -1526.556542 |
| TC3 | Floating (Receive) | 2026-05-31 | 2026-11-30 | 2026-11-30 | 790000.000000 | 790000.000000 | 4.375720 | 0.043555 | 17572.150000 | 17490.805660 | 0.975591 | 0.974962 | 17143.230000 | 17052.871664 |
| TC3 | Floating (Receive) | 2026-11-30 | 2027-05-28 | 2027-05-28 | 592500.000000 | 592500.000000 | 4.327640 | 0.042739 | 12749.400000 | 12591.059452 | 0.958306 | 0.957510 | 12217.830000 | 12056.062532 |
| TC3 | Floating (Receive) | 2027-05-28 | 2027-11-30 | 2027-11-30 | 395000.000000 | 395000.000000 | 4.240250 | 0.041053 | 8653.640000 | 8378.139224 | 0.941092 | 0.940336 | 8143.870000 | 7878.265311 |
| TC3 | Floating (Receive) | 2027-11-30 | 2028-04-28 | 2028-04-28 | 197500.000000 | 197500.000000 | 4.124040 | 0.040023 | 3393.740000 | 3293.580261 | 0.927854 | 0.927528 | 3148.900000 | 3054.887996 |
| TC4 | Fixed (Pay) | 2026-01-01 | 2026-03-31 | 2026-03-31 | — | 930000.000000 | — | 0.050000 | — | -11495.833333 | — | 1.000000 | — | — |
| TC4 | Fixed (Pay) | 2026-03-31 | 2026-06-30 | 2026-06-30 | -744000.000000 | 744000.000000 | 5.000000 | 0.050000 | -9403.330000 | -9403.333333 | 0.990792 | 0.990484 | -9316.750000 | -9313.850577 |
| TC4 | Fixed (Pay) | 2026-06-30 | 2026-09-30 | 2026-09-30 | -558000.000000 | 558000.000000 | 5.000000 | 0.050000 | -7130.000000 | -7130.000000 | 0.981621 | 0.981115 | -6998.960000 | -6995.353278 |
| TC4 | Fixed (Pay) | 2026-09-30 | 2026-12-31 | 2026-12-31 | -372000.000000 | 372000.000000 | 5.000000 | 0.050000 | -4753.330000 | -4753.333333 | 0.972550 | 0.971687 | -4622.850000 | -4618.753449 |
| TC4 | Fixed (Pay) | 2026-12-31 | 2027-02-26 | 2027-02-26 | -186000.000000 | 186000.000000 | 5.000000 | 0.050000 | -1472.500000 | -1472.500000 | 0.967014 | 0.966428 | -1423.930000 | -1423.065787 |
| TC4 | Floating (Receive) | 2026-01-01 | 2026-03-31 | 2026-03-31 | — | 930000.000000 | — | — | — | — | — | 1.000000 | — | — |
| TC4 | Floating (Receive) | 2026-03-31 | 2026-06-30 | 2026-06-30 | 744000.000000 | 744000.000000 | 3.976880 | 0.039769 | 7479.180000 | 7479.142339 | 0.990792 | 0.990484 | 7410.320000 | 7407.970315 |
| TC4 | Floating (Receive) | 2026-06-30 | 2026-09-30 | 2026-09-30 | 558000.000000 | 558000.000000 | 3.955820 | 0.039560 | 5641.010000 | 5641.196949 | 0.981621 | 0.981115 | 5537.330000 | 5534.665577 |
| TC4 | Floating (Receive) | 2026-09-30 | 2026-12-31 | 2026-12-31 | 372000.000000 | 372000.000000 | 3.949770 | 0.039505 | 3754.920000 | 3755.623337 | 0.972550 | 0.971687 | 3651.840000 | 3649.291355 |
| TC4 | Floating (Receive) | 2026-12-31 | 2027-02-26 | 2027-02-26 | 186000.000000 | 186000.000000 | 3.915740 | 0.039129 | 1153.180000 | 1152.337953 | 0.967014 | 0.966428 | 1115.150000 | 1113.652099 |

## 4. Notional/amortisation comparison

Period notionals below are QuantLib coupon nominals and are compared against the signed Bloomberg source nominal. Pay-leg QuantLib nominals are positive coupon bases while Bloomberg stores Pay-side notionals as negative. TC3/TC4 absolute period notionals agree for matched future payment dates. TC1 raw oracle cashflow notionals remain at the residual 1000x scale (530000000 / 265000000), while the normalized case and current QuantLib coupon bases are 530000 / 265000; the source oracle was not altered. No separate principal exchange cashflows are generated by this path.

## 5. Market-data / benchmark limitations

The current floating-index builder supports only `('SOFRRATE', '1D', 'USD', Daily)`. TC2 and TC5–TC10 cannot be constructed through this builder because their currencies and/or benchmarks differ. TC3 and TC4 match the USD SOFR mapping. TC1 is measured through the existing TC1 pattern, which supplies the Bloomberg source identifier `SOFRRATE` to the builder; the normalized domain case field is `SOFR` and is not accepted by the current mapping directly.

The curve module has a stable direct discount-factor builder. The confirmed forward-curve builder still raises `ProjectionCurveMethodologyUnspecified`; supported-case pricing therefore uses the separately named provisional projection builder already used by the TC1 pricing test. TC4's already-due 2026-03-31 floating coupon cannot expose a coupon amount or rate because the market inputs contain no historical SOFR fixing for its accrual; this did not prevent calculation of the swap NPV at the valuation date.

## 6. Observed discrepancy patterns

- TC1: fixed difference 26.381154; floating difference -375.185973; total difference -348.804820. Period counts are 2 fixed and 2 floating.
- TC3: fixed difference 13.368089; floating difference -611.742497; total difference -598.374409. Period counts are 4 fixed and 4 floating.
- TC4: fixed difference 11.466909; floating difference -9.060654; total difference 2.406254. Period counts are 5 fixed and 5 floating.

## 7. Baseline conclusion

3 of 10 cases priced through the current fresh IRS component path; 7 were unsupported by the current floating benchmark mapping.
TC1 remains a discrepancy, and the measured TC3 and TC4 results show additional discrepancies. This baseline does not diagnose or correct them.
