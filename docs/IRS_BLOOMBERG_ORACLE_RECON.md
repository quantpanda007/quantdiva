# Bloomberg IRS TC1–TC10 Oracle Reconnaissance

## Scope and source handling

This report records source fields from `tests/fixtures/bloomberg_irs/source/TC1.json` through `TC10.json`. These are the byte-preserved Bloomberg JSON files; `source_manifest.json` records archive members and SHA-256 digests. The separated `cases/` and `references/` folders organize inputs and oracle outputs. No pricing, curve construction, or value reconciliation was performed.

TC1’s domain-facing case reflects the clarification: original/first-period notional 530000, second-period notional 265000, normalized benchmark `SOFR`, and schedule 2026-05-31 → 2027-05-28 → 2027-11-30. The raw source retains `SOFRRATE`, residual million-scale leg/amortization fields, and conflicting detail dates unchanged.

All displayed numeric values are source values without additional rounding. NPV entries with different source paths are kept distinct; no equivalence is assumed.

## 1. Case matrix

| Case / trade ID | Ccy | Valuation date | Effective → maturity | Trade notional (source; fixed-leg initial if absent) | Fixed pay freq | Float benchmark / tenor | Float reset / pay freq | Amortization rows and stated reductions | Detailed-cashflow fixed / float / total NPV |
|---|---|---|---|---:|---|---|---|---|---|
| TC1 / SLLSL9RR | USD | 2026-03-31 | 2026-05-31 → 2027-11-30 | 530000 | Annual | SOFRRATE / 1D | Daily / Annual | 0.0% / 0; 50.0% / 265000000; rows=2 | -31978.74 / 24023.74 / -7955.0 |
| TC2 / SLLSL9SL | CHF | 2026-03-31 | 2026-04-30 → 2028-02-29 | 20000 | Quarterly | SF0006M / 6M | SemiAnnual / Quarterly | 0.0% / 0.0; 12.5% / 2500000; 12.5% / 2500000; 12.5% / 2500000; 12.5% / 2500000; 12.5% / 2500000; 12.5% / 2500000; 12.5% / 2500000; rows=8 | -220.6 / 61.69 / -158.91 |
| TC3 / SLLSL90 | USD | 2026-03-31 | 2026-05-31 → 2028-04-30 | 790000 | SemiAnnual | SOFRRATE / 1D | Daily / SemiAnnual | 0.0% / 0.0; 25.0% / 197500; 25.0% / 197500; 25.0% / 197500; rows=4 | -18850.36 / 40653.83 / 21803.47 |
| TC4 / SLLSL9RX | USD | 2026-03-31 | 2026-01-01 → 2027-02-28 | 930000 | Quarterly | SOFRRATE / 1D | Daily / Quarterly | 0.0% / 0.0; 20.0% / 186000; 20.0% / 186000; 20.0% / 186000; 20.0% / 186000; rows=5 | -22362.49 / 17714.64 / -4647.85 |
| TC5 / SLLSL9S9 | INR | 2026-03-31 | 2026-06-30 → 2027-09-30 | 7500000 | Annual | IRSWOF / 6M | SemiAnnual / Annual | 0.0% / 0.0; 50.0% / 3750000; rows=2 | -702752.68 / 582952.71 / -119799.97 |
| TC6 / SLLSL9SC | JPY | 2026-03-31 | 2026-07-31 → 2028-01-31 | 7300000 | SemiAnnual | MUTKCALM / 1D | Daily / SemiAnnual | 0.0% / 0.0; 33.333333% / 2433333.33; 33.333333% / 2433333.33; rows=3 | -72020.0 / 116562.0 / 44542.0 |
| TC7 / SLLSL9SI | CHF | 2026-03-31 | 2026-08-31 → 2028-07-31 | 52000 | Annual | SF0006M / 6M | SemiAnnual / Annual | 0.0% / 0.0; 50.0% / 26000.0; rows=2 | -755.74 / 427.02 / -388.06 |
| TC8 / SLLSL9S6 | INR | 2026-03-31 | 2026-02-28 → 2027-03-31 | 4500000 | SemiAnnual | IRSWOF / 6M | SemiAnnual / SemiAnnual | 0.0% / 0.0; 33.333333% / 1500000.0; 33.333333% / 1500000.0; rows=3 | -373543.3 / 234028.32 / -139514.98 |
| TC9 / SLLSL9S3 | INR | 2026-03-31 | 2026-06-30 → 2028-05-31 | 1900000 | Quarterly | IRSWOF / 6M | SemiAnnual / Quarterly | 0.0% / 0.0; 12.5% / 237500.0; 12.5% / 237500.0; 12.5% / 237500.0; 12.5% / 237500.0; 12.5% / 237500.0; 12.5% / 237500.0; 12.5% / 237500.0; rows=8 | -198898.34 / 137077.59 / -61820.75 |
| TC10 / SLLSL9SF | JPY | 2026-03-31 | 2026-03-31 → 2027-06-30 | not supplied; fixed-leg initial 54400000.0 | Annual | MUTKCALM / 1D | Daily / Annual | 0.0% / 0.0; 50.0% / 27200000.0; rows=2 | -54324517.0 / 54581497.0 / 256979.0 |

TC2’s top-level trade notional is 20000 while both raw leg notionals and schedule balances are 20000000. This is reported as a source discrepancy without normalization. TC1’s raw leg scale is separately addressed by the SME clarification.

## 2. Fixed-leg matrix

| Case | Direction | Coupon as stated | Payment frequency | Day count | Amortization rows / fixed cashflow rows | Period start → end; payment date; balance; repayment |
|---|---|---|---|---|---:|---|
| TC1 | Pay | 5.0 % | Annual | ACT/360 | 2 / 2 | 2026-05-31→2027-05-28; pay 2027-05-28; balance 530000000; repayment 0<br>2027-05-28→2027-11-30; pay 2027-11-30; balance 265000000; repayment 265000000 |
| TC2 | Pay | 1.0 % | Quarterly | 30/360 | 8 / 8 | 2026-04-30→2026-07-31; pay 2026-07-31; balance 20000000; repayment 0.0<br>2026-07-31→2026-10-30; pay 2026-10-30; balance 17500000; repayment 2500000<br>2026-10-30→2027-01-29; pay 2027-01-29; balance 15000000; repayment 2500000<br>2027-01-29→2027-04-30; pay 2027-04-30; balance 12500000; repayment 2500000<br>2027-04-30→2027-07-30; pay 2027-07-30; balance 10000000; repayment 2500000<br>2027-07-30→2027-10-29; pay 2027-10-29; balance 7500000; repayment 2500000<br>2027-10-29→2028-01-31; pay 2028-01-31; balance 5000000; repayment 2500000<br>2028-01-31→2028-02-29; pay 2028-02-29; balance 2500000; repayment 2500000 |
| TC3 | Pay | 2.0 % | SemiAnnual | ACT/360 | 4 / 4 | 2026-05-31→2026-11-30; pay 2026-11-30; balance 790000; repayment 0.0<br>2026-11-30→2027-05-28; pay 2027-05-28; balance 592500; repayment 197500<br>2027-05-28→2027-11-30; pay 2027-11-30; balance 395000; repayment 197500<br>2027-11-30→2028-04-28; pay 2028-04-28; balance 197500; repayment 197500 |
| TC4 | Pay | 5.0 % | Quarterly | ACT/360 | 5 / 4 | 2026-01-01→2026-03-31; pay 2026-03-31; balance 930000; repayment 0.0<br>2026-03-31→2026-06-30; pay 2026-06-30; balance 744000; repayment 186000<br>2026-06-30→2026-09-30; pay 2026-09-30; balance 558000; repayment 186000<br>2026-09-30→2026-12-31; pay 2026-12-31; balance 372000; repayment 186000<br>2026-12-31→2027-02-26; pay 2027-02-26; balance 186000; repayment 186000 |
| TC5 | Pay | 9.0 % | Annual | ACT/365 | 2 / 2 | 2026-06-30→2027-06-30; pay 2027-06-30; balance 7500000; repayment 0.0<br>2027-06-30→2027-09-30; pay 2027-09-30; balance 3750000; repayment 3750000 |
| TC6 | Pay | 1.0 (unit field absent) | SemiAnnual | ACT/365 | 3 / 3 | 2026-07-31→2027-01-29; pay 2027-01-29; balance 7300000.0; repayment 0.0<br>2027-01-29→2027-07-30; pay 2027-07-30; balance 4866666.67; repayment 2433333.33<br>2027-07-30→2028-01-31; pay 2028-01-31; balance 2433333.34; repayment 2433333.33 |
| TC7 | Pay | 1.0 (unit field absent) | Annual | 30/360 | 2 / 2 | 2026-08-31→2027-08-31; pay 2027-08-31; balance 52000.0; repayment 0.0<br>2027-08-31→2028-07-31; pay 2028-07-31; balance 26000.0; repayment 26000.0 |
| TC8 | Pay | 10.0 (unit field absent) | SemiAnnual | ACT/365 | 3 / 3 | 2026-02-28→2026-08-31; pay 2026-08-31; balance 4500000.0; repayment 0.0<br>2026-08-31→2027-02-26; pay 2027-02-26; balance 3000000.0; repayment 1500000.0<br>2027-02-26→2027-03-31; pay 2027-03-31; balance 1500000.0; repayment 1500000.0 |
| TC9 | Pay | 10.0 (unit field absent) | Quarterly | ACT/365 | 8 / 8 | 2026-06-30→2026-09-30; pay 2026-09-30; balance 1900000.0; repayment 0.0<br>2026-09-30→2026-12-31; pay 2026-12-31; balance 1662500.0; repayment 237500.0<br>2026-12-31→2027-03-31; pay 2027-03-31; balance 1425000.0; repayment 237500.0<br>2027-03-31→2027-06-30; pay 2027-06-30; balance 1187500.0; repayment 237500.0<br>2027-06-30→2027-09-30; pay 2027-09-30; balance 950000.0; repayment 237500.0<br>2027-09-30→2027-12-31; pay 2027-12-31; balance 712500.0; repayment 237500.0<br>2027-12-31→2028-03-31; pay 2028-03-31; balance 475000.0; repayment 237500.0<br>2028-03-31→2028-05-31; pay 2028-05-31; balance 237500.0; repayment 237500.0 |
| TC10 | Pay | 1.0% (source coupon_rate_pct) | Annual | ACT/365 | 2 / 2 | 2026-03-31→2027-03-31; pay 2027-03-31; balance 54400000.0; repayment 0.0<br>2027-03-31→2027-06-30; pay 2027-06-30; balance 27200000.0; repayment 27200000.0 |

TC6–TC9 source fixed legs do not include a separate coupon-unit field; the numeric coupon value is preserved without adding a unit.

## 3. Floating-leg matrix

| Case | Direction | Benchmark / tenor | Spread / leverage | Reset / pay frequency | Day count | Reset timing | Lookback, cutoff, compounding, and other observation fields as supplied | Amortization rows / floating cashflow rows |
|---|---|---|---|---|---|---|---|---:|
| TC1 | Receive | SOFRRATE / 1D | 10.0 bp / 1.0 | Daily / Annual | ACT/360 | In Arrears | {"days_before_accrual":0,"days_before_type":"Lookback","rate_cut_off_days":1,"reset_type":"In Arrears","compounding":"ExcludeSprd"} | 2 / 2 |
| TC2 | Receive | SF0006M / 6M | 10.0 bp / 1.0 | SemiAnnual / Quarterly | ACT/360 | In Advance | {"days_before_accrual":1,"reset_type":"In Advance","fixing_calendar":"EN"} | 8 / 8 |
| TC3 | Receive | SOFRRATE / 1D | 70.0 bp / 1.0 | Daily / SemiAnnual | ACT/360 | In Arrears | {"days_before_accrual":0,"days_before_type":"Lookback","rate_cut_off_days":1,"reset_type":"In Arrears","compounding":"ExcludeSprd"} | 4 / 4 |
| TC4 | Receive | SOFRRATE / 1D | 30.0 bp / 1.0 | Daily / Quarterly | ACT/360 | In Arrears | {"days_before_accrual":0,"days_before_type":"Lookback","rate_cut_off_days":1,"reset_type":"In Arrears","compounding":"ExcludeSprd"} | 5 / 4 |
| TC5 | Receive | IRSWOF / 6M | 100.0 bp / 1.0 | SemiAnnual / Annual | ACT/365 | In Advance | {"days_before_accrual":1,"reset_type":"In Advance","compounding":"Flat"} | 2 / 2 |
| TC6 | Receive | MUTKCALM / 1D | 30.0 bp / unit not stated / 1.0 | Daily / SemiAnnual | ACT/365 | In Arrears | {"days_before_accrual":0,"days_before_type":"Lookback","rate_cutoff_days":1,"reset_type":"In Arrears","compounding":"ExcludeSprd","fixing_calendar":"JN","calculation_calendar":"JN"} | 3 / 3 |
| TC7 | Receive | SF0006M / 6M | 20.0 bp / unit not stated / 1.0 | SemiAnnual / Annual | ACT/360 | In Advance | {"days_before_accrual":1,"reset_type":"In Advance","compounding":"Flat","fixing_calendar":"SZ","calculation_calendar":"SZ"} | 2 / 2 |
| TC8 | Receive | IRSWOF / 6M | 50.0 bp / unit not stated / 1.0 | SemiAnnual / SemiAnnual | ACT/365 | In Advance | {"days_before_accrual":1,"reset_type":"In Advance","fixing_calendar":"RB","calculation_calendar":"RB"} | 3 / 3 |
| TC9 | Receive | IRSWOF / 6M | 50.0 bp / unit not stated / 1.0 | SemiAnnual / Quarterly | ACT/365 | In Advance | {"days_before_accrual":1,"reset_type":"In Advance","fixing_calendar":"RB","calculation_calendar":"RB"} | 8 / 8 |
| TC10 | Receive | MUTKCALM / 1D | 30.0 bps / unit not stated / 1.0 | Daily / Annual | ACT/365 | In Arrears | {"rate_cutoff_days":1,"reset_type":"In Arrears","compounding":"ExcludeSprd","lookback":true,"lookback_days":0} | 2 / 2 |

Equivalent coupon source keys vary (`equivalent_coupon`, `equiv_coupon`, `equivalent_coupon_pct`). TC8 floating cashflow rows have reset-rate data but no equivalent-coupon field. Raw field names are retained in each reference fixture.

## 4. Cashflow structure

| Case | Net / fixed / floating rows | Net source fields | Fixed cashflow fields | Floating cashflow fields | Equivalent coupon present |
|---|---:|---|---|---|---|
| TC1 | 2 / 2 / 2 | pay_date, payments_receive, payments_pay, net_payment, discount_factor, pv | pay_date, accrual_start, accrual_end, days, notional, principal, payment, discount_factor, pv | pay_date, accrual_start, accrual_end, days, notional, principal, effective_reset_date, equivalent_coupon, payment, discount_factor, pv | equivalent_coupon |
| TC2 | 8 / 8 / 8 | pay_date, payments_receive, payments_pay, net_payment, discount_factor, pv | pay_date, accrual_start, accrual_end, days, notional, principal, equivalent_coupon, payment, discount_factor, pv | pay_date, accrual_start, accrual_end, days, notional, principal, effective_reset_date, equivalent_coupon, payment, discount_factor, pv | equivalent_coupon |
| TC3 | 4 / 4 / 4 | pay_date, payments_receive, payments_pay, net_payment, discount_factor, pv | pay_date, accrual_start, accrual_end, days, notional, principal, equivalent_coupon, payment, discount_factor, pv | pay_date, accrual_start, accrual_end, days, notional, principal, effective_reset_date, equivalent_coupon, payment, discount_factor, pv | equivalent_coupon |
| TC4 | 4 / 4 / 4 | pay_date, payments_receive, payments_pay, net_payment, discount_factor, pv | pay_date, accrual_start, accrual_end, days, notional, principal, equivalent_coupon, payment, discount_factor, pv | pay_date, accrual_start, accrual_end, days, notional, principal, effective_reset_date, equivalent_coupon, payment, discount_factor, pv | equivalent_coupon |
| TC5 | 2 / 2 / 2 | pay_date, payments_receive, payments_pay, net_payment, discount_factor, pv | pay_date, accrual_start, accrual_end, days, notional, principal, equivalent_coupon, payment, discount_factor, pv | pay_date, accrual_start, accrual_end, days, notional, principal, effective_reset_date, equivalent_coupon, payment, discount_factor, pv | equivalent_coupon |
| TC6 | 3 / 3 / 3 | pay_date, payments_receive, payments_pay, net_payment, discount, pv | pay_date, accrual_start, accrual_end, days, notional, principal, payment, discount, pv | pay_date, accrual_start, accrual_end, days, notional, principal, effective_reset_date, equivalent_coupon, payment, discount, pv | equivalent_coupon |
| TC7 | 2 / 2 / 2 | pay_date, payments_receive, payments_pay, net_payment, discount, pv | pay_date, accrual_start, accrual_end, days, notional, principal, equiv_coupon, payment, discount, pv | pay_date, accrual_start, accrual_end, days, notional, principal, effective_reset_date, equiv_coupon, payment, discount, pv | equiv_coupon |
| TC8 | 3 / 3 / 3 | pay_date, payments_receive, payments_pay, net_payment, discount, pv | pay_date, accrual_start, accrual_end, days, notional, principal, payment, discount, pv | pay_date, accrual_start, accrual_end, days, notional, principal, reset_date, reset_rate, payment, discount, pv | No |
| TC9 | 8 / 8 / 8 | pay_date, payments_receive, payments_pay, net_payment, discount, pv | pay_date, accrual_start, accrual_end, days, notional, principal, equiv_coupon, payment, discount, pv | pay_date, accrual_start, accrual_end, days, notional, principal, reset_date, reset_rate, equiv_coupon, payment, discount, pv | equiv_coupon |
| TC10 | 2 / 2 / 2 | pay_date, receive_amount, pay_amount, net_amount, discount_factor, pv | pay_date, accrual_start, accrual_end, days, notional, coupon_rate_pct, payment, discount_factor, pv | pay_date, accrual_start, accrual_end, days, notional, effective_reset_date, equivalent_coupon_pct, payment, discount_factor, pv | equivalent_coupon_pct |

Every source provides net, fixed, and floating cashflow detail. The discount field is named `discount_factor` or `discount`; TC6–TC9 use `discount`. Net rows include payment date, receive/pay amounts, net amount, discount value, and PV (names vary by source).

## 5. Pricing oracle matrix

| Case | Detailed fixed-leg NPV | Detailed floating-leg NPV | Total NPV fields | Separate leg-summary NPV fields (fixed / floating) |
|---|---:|---:|---|---|
| TC1 | -31978.74 | 24023.74 | cashflow.npv=-7955.0; valuation_results.npv=-7955.0 | -8594.58 / 639.58 |
| TC2 | -220.6 | 61.69 | cashflow.npv=-158.91; valuation_results.npv=-158.91 | -192.33 / 33.42 |
| TC3 | -18850.36 | 40653.83 | cashflow.npv=21803.47; valuation_results.npv=21803.47 | 15205.84 / 6597.63 |
| TC4 | -22362.49 | 17714.64 | cashflow.npv=-4647.85; valuation_results.npv=-4647.85 | -749990.2 / 745342.34 |
| TC5 | -702752.68 | 582952.71 | cashflow.npv=-119799.97; valuation_results.npv=-119799.97 | -198319.21 / 78519.24 |
| TC6 | -72020.0 | 116562.0 | valuation_results.npv=44542.0; cashflows.net_npv=44542.0 | 22936.0 / 21606.0 |
| TC7 | -755.74 | 427.02 | valuation_results.npv=-388.06; cashflows.net_npv=-328.72 | -593.58 / 205.51 |
| TC8 | -373543.3 | 234028.32 | valuation_results.npv=-139514.98; cashflows.net_npv=-139514.98 | -4670125.07 / 4530610.09 |
| TC9 | -198898.34 | 137077.59 | valuation_results.npv=-61820.75; cashflows.net_npv=-61820.75 | -72220.1 / 10399.35 |
| TC10 | -54324517.0 | 54581497.0 | valuation.trade_npv=256979.0 | -54324517.0 / 54581497.0 |

The “detailed” NPVs are the NPVs inside the cashflow sections. The separate leg-summary values come from `leg_1.market`/`leg_2.market` (TC1–TC5), `trade.legs` (TC6–TC9), or `leg_valuation` (TC10). These source paths are not collapsed.

### Other supplied valuation and risk fields

| Case | Additional valuation fields | Risk fields |
|---|---|---|
| TC1 | `{"par_coupon":3.756205,"premium":-1.50094,"principal":-7955.0,"bp_value":-150.09436,"accrued":0.0}` | `{"pv01":-63.96,"dv01":-64.67,"gamma_1bp":-0.02}` |
| TC2 | `{"par_coupon":0.279664,"premium":-0.79454,"principal":-158.91,"bp_value":-7.945395,"accrued":0.0}` | `{"pv01":-2.21,"dv01":-2.08,"gamma_1bp":0.0}` |
| TC3 | `{"par_coupon":4.313322,"premium":2.75993,"principal":21803.47,"bp_value":275.99331,"accrued":0.0}` | `{"pv01":-94.25,"dv01":-90.06,"gamma_1bp":-0.02}` |
| TC4 | `{"par_coupon":3.960793,"premium":-0.62471,"principal":-4647.85,"bp_value":-62.47114,"accrued":0.0}` | `{"pv01":-44.72,"dv01":-44.01,"gamma_1bp":-0.01}` |
| TC5 | `{"par_coupon":7.465748,"premium":-1.59733,"principal":-119799.97,"bp_value":-159.73329,"accrued":0.0}` | `{"pv01":-780.84,"dv01":-797.9,"gamma_1bp":-0.19}` |
| TC6 | `{"par_coupon":1.618467,"premium":0.61017,"principal":44542.0,"bp_value":61.0166,"accrued":0.0}` | `{"pv01":-720.0,"dv01":-710.0,"gamma_1bp":-0.2}` |
| TC7 | `{"par_coupon":0.486944,"premium":-0.74628,"principal":-388.06,"bp_value":-74.62,"accrued":0.0}` | `{"pv01":-7.56,"dv01":-7.75,"gamma_1bp":0.0}` |
| TC8 | `{"par_coupon":6.311263,"premium":-2.74872,"principal":-123692.24,"bp_value":-310.03328,"accrued":-15822.74}` | `{"pv01":-373.54,"dv01":-151.78,"gamma_1bp":-0.04}` |
| TC9 | `{"par_coupon":6.891842,"premium":-3.25372,"principal":-61820.75,"bp_value":-325.37235,"accrued":0.0}` | `{"pv01":-198.9,"dv01":-201.5,"gamma_1bp":-0.05}` |
| TC10 | `{"accrued":0.0,"par_coupon":1.424756,"premium":0.47239,"principal":256979.0,"bp_value":47.23881}` | `{"pv01":-6050.0,"dv01":-6007.0,"gamma_1bp":-1.22}` |

### Net cashflow rows

| Case | Pay date | Receive | Pay | Net | DF / discount | PV |
|---|---|---:|---:|---:|---:|---:|
| TC1 | 2027-05-28 | 20174.4 | -26647.22 | -6472.82 | 0.958306 | -6202.94 |
| TC1 | 2027-11-30 | 4984.11 | -6845.83 | -1861.73 | 0.941092 | -1752.06 |
| TC2 | 2026-07-31 | 6.53 | -50.0 | -43.47 | 1.000147 | -43.48 |
| TC2 | 2026-10-30 | 7.61 | -43.75 | -36.14 | 1.000052 | -36.14 |
| TC2 | 2027-01-29 | 10.48 | -37.08 | -26.6 | 0.999618 | -26.59 |
| TC2 | 2027-04-30 | 11.76 | -31.6 | -19.84 | 0.999049 | -19.82 |
| TC2 | 2027-07-30 | 10.65 | -25.0 | -14.35 | 0.998367 | -14.33 |
| TC2 | 2027-10-29 | 8.62 | -18.54 | -9.92 | 0.997635 | -9.9 |
| TC2 | 2028-01-31 | 5.34 | -12.78 | -7.44 | 0.997171 | -7.42 |
| TC2 | 2028-02-29 | 0.78 | -2.01 | -1.23 | 0.997023 | -1.23 |
| TC3 | 2026-11-30 | 17572.15 | -8031.67 | 9540.48 | 0.975591 | 9307.61 |
| TC3 | 2027-05-28 | 12749.4 | -5892.08 | 6857.32 | 0.958306 | 6571.41 |
| TC3 | 2027-11-30 | 8653.64 | -4081.67 | 4571.97 | 0.941092 | 4302.65 |
| TC3 | 2028-04-28 | 3393.74 | -1645.83 | 1747.91 | 0.927854 | 1621.81 |
| TC4 | 2026-06-30 | 7479.18 | -9403.33 | -1924.15 | 0.990792 | -1906.43 |
| TC4 | 2026-09-30 | 5641.01 | -7130.0 | -1488.99 | 0.981621 | -1461.63 |
| TC4 | 2026-12-31 | 3754.92 | -4753.33 | -998.42 | 0.97255 | -971.01 |
| TC4 | 2027-02-26 | 1153.18 | -1472.5 | -319.32 | 0.967014 | -308.78 |
| TC5 | 2027-06-30 | 559485.34 | -675000.0 | -115514.66 | 0.92629 | -107000.05 |
| TC5 | 2027-09-30 | 71019.84 | -85068.49 | -14048.65 | 0.911114 | -12799.92 |
| TC6 | 2027-01-29 | 52085.0 | -36400.0 | 15685.0 | 0.99148 | 15551.0 |
| TC6 | 2027-07-30 | 41862.0 | -24266.0 | 17596.0 | 0.984484 | 17323.0 |
| TC6 | 2028-01-31 | 24284.0 | -12333.0 | 11951.0 | 0.976226 | 11667.0 |
| TC7 | 2027-08-31 | 224.02 | -520.0 | -295.98 | 0.998415 | -295.51 |
| TC7 | 2028-07-31 | 204.88 | -238.33 | -33.45 | 0.992575 | -33.21 |
| TC8 | 2026-08-31 | 132933.7 | -226849.32 | -93915.62 | 0.976313 | -91691.02 |
| TC8 | 2027-02-26 | 100848.85 | -147123.29 | -46274.44 | 0.946844 | -43814.66 |
| TC8 | 2027-03-31 | 9302.01 | -13561.64 | -4259.63 | 0.941231 | -4009.3 |
| TC9 | 2026-09-30 | 29892.46 | -47890.41 | -17997.95 | 0.971633 | -17487.4 |
| TC9 | 2026-12-31 | 29265.96 | -41904.11 | -12638.15 | 0.956418 | -12087.35 |
| TC9 | 2027-03-31 | 24539.78 | -35136.99 | -10597.2 | 0.941231 | -9974.42 |
| TC9 | 2027-06-30 | 21008.18 | -29606.16 | -8597.99 | 0.92629 | -7964.23 |
| TC9 | 2027-09-30 | 16991.23 | -23945.21 | -6953.97 | 0.911114 | -6335.86 |
| TC9 | 2027-12-31 | 13267.92 | -17958.9 | -4690.98 | 0.895864 | -4202.48 |
| TC9 | 2028-03-31 | 8749.14 | -11842.47 | -3093.33 | 0.880719 | -2724.35 |
| TC9 | 2028-05-31 | 2769.84 | -3969.18 | -1199.34 | 0.871026 | -1044.66 |
| TC10 | 2027-03-31 | 753656.0 | -544000.0 | 209656.0 | 0.989262 | 207404.0 |
| TC10 | 2027-06-30 | 118106.0 | -67813.0 | 50292.0 | 0.98572 | 49574.0 |

## 6. Amortisation / repayment inventory

| Case | Fixed schedule periods (start → end; pay; balance; repayment amount) | Floating schedule | Comparison |
|---|---|---|---|
| TC1 | 2026-05-31→2027-05-28; pay 2027-05-28; balance 530000000; repayment 0<br>2027-05-28→2027-11-30; pay 2027-11-30; balance 265000000; repayment 265000000 | 2026-05-31→2027-05-28; pay 2027-05-28; balance 530000000; repayment 0<br>2027-05-28→2027-11-30; pay 2027-11-30; balance 265000000; repayment 265000000 | same dates and balances |
| TC2 | 2026-04-30→2026-07-31; pay 2026-07-31; balance 20000000; repayment 0.0<br>2026-07-31→2026-10-30; pay 2026-10-30; balance 17500000; repayment 2500000<br>2026-10-30→2027-01-29; pay 2027-01-29; balance 15000000; repayment 2500000<br>2027-01-29→2027-04-30; pay 2027-04-30; balance 12500000; repayment 2500000<br>2027-04-30→2027-07-30; pay 2027-07-30; balance 10000000; repayment 2500000<br>2027-07-30→2027-10-29; pay 2027-10-29; balance 7500000; repayment 2500000<br>2027-10-29→2028-01-31; pay 2028-01-31; balance 5000000; repayment 2500000<br>2028-01-31→2028-02-29; pay 2028-02-29; balance 2500000; repayment 2500000 | 2026-04-30→2026-07-31; pay 2026-07-31; balance 20000000; repayment 0.0<br>2026-07-31→2026-10-30; pay 2026-10-30; balance 17500000; repayment 2500000<br>2026-10-30→2027-01-29; pay 2027-01-29; balance 15000000; repayment 2500000<br>2027-01-29→2027-04-30; pay 2027-04-30; balance 12500000; repayment 2500000<br>2027-04-30→2027-07-30; pay 2027-07-30; balance 10000000; repayment 2500000<br>2027-07-30→2027-10-29; pay 2027-10-29; balance 7500000; repayment 2500000<br>2027-10-29→2028-01-31; pay 2028-01-31; balance 5000000; repayment 2500000<br>2028-01-31→2028-02-29; pay 2028-02-29; balance 2500000; repayment 2500000 | same dates and balances |
| TC3 | 2026-05-31→2026-11-30; pay 2026-11-30; balance 790000; repayment 0.0<br>2026-11-30→2027-05-28; pay 2027-05-28; balance 592500; repayment 197500<br>2027-05-28→2027-11-30; pay 2027-11-30; balance 395000; repayment 197500<br>2027-11-30→2028-04-28; pay 2028-04-28; balance 197500; repayment 197500 | 2026-05-31→2026-11-30; pay 2026-11-30; balance 790000; repayment 0.0<br>2026-11-30→2027-05-28; pay 2027-05-28; balance 592500; repayment 197500<br>2027-05-28→2027-11-30; pay 2027-11-30; balance 395000; repayment 197500<br>2027-11-30→2028-04-28; pay 2028-04-28; balance 197500; repayment 197500 | same dates and balances |
| TC4 | 2026-01-01→2026-03-31; pay 2026-03-31; balance 930000; repayment 0.0<br>2026-03-31→2026-06-30; pay 2026-06-30; balance 744000; repayment 186000<br>2026-06-30→2026-09-30; pay 2026-09-30; balance 558000; repayment 186000<br>2026-09-30→2026-12-31; pay 2026-12-31; balance 372000; repayment 186000<br>2026-12-31→2027-02-26; pay 2027-02-26; balance 186000; repayment 186000 | 2026-01-01→2026-03-31; pay 2026-03-31; balance 930000; repayment 0.0<br>2026-03-31→2026-06-30; pay 2026-06-30; balance 744000; repayment 186000<br>2026-06-30→2026-09-30; pay 2026-09-30; balance 558000; repayment 186000<br>2026-09-30→2026-12-31; pay 2026-12-31; balance 372000; repayment 186000<br>2026-12-31→2027-02-26; pay 2027-02-26; balance 186000; repayment 186000 | same dates and balances |
| TC5 | 2026-06-30→2027-06-30; pay 2027-06-30; balance 7500000; repayment 0.0<br>2027-06-30→2027-09-30; pay 2027-09-30; balance 3750000; repayment 3750000 | 2026-06-30→2027-06-30; pay 2027-06-30; balance 7500000; repayment 0.0<br>2027-06-30→2027-09-30; pay 2027-09-30; balance 3750000; repayment 3750000 | same dates and balances |
| TC6 | 2026-07-31→2027-01-29; pay 2027-01-29; balance 7300000.0; repayment 0.0<br>2027-01-29→2027-07-30; pay 2027-07-30; balance 4866666.67; repayment 2433333.33<br>2027-07-30→2028-01-31; pay 2028-01-31; balance 2433333.34; repayment 2433333.33 | 2026-07-31→2027-01-29; pay 2027-01-29; balance 7300000.0; repayment 0.0<br>2027-01-29→2027-07-30; pay 2027-07-30; balance 4866666.67; repayment 2433333.33<br>2027-07-30→2028-01-31; pay 2028-01-31; balance 2433333.34; repayment 2433333.33 | same dates and balances |
| TC7 | 2026-08-31→2027-08-31; pay 2027-08-31; balance 52000.0; repayment 0.0<br>2027-08-31→2028-07-31; pay 2028-07-31; balance 26000.0; repayment 26000.0 | 2026-08-31→2027-08-31; pay 2027-08-31; balance 52000.0; repayment 0.0<br>2027-08-31→2028-07-31; pay 2028-07-31; balance 26000.0; repayment 26000.0 | same dates and balances |
| TC8 | 2026-02-28→2026-08-31; pay 2026-08-31; balance 4500000.0; repayment 0.0<br>2026-08-31→2027-02-26; pay 2027-02-26; balance 3000000.0; repayment 1500000.0<br>2027-02-26→2027-03-31; pay 2027-03-31; balance 1500000.0; repayment 1500000.0 | 2026-02-28→2026-08-31; pay 2026-08-31; balance 4500000.0; repayment 0.0<br>2026-08-31→2027-02-26; pay 2027-02-26; balance 3000000.0; repayment 1500000.0<br>2027-02-26→2027-03-31; pay 2027-03-31; balance 1500000.0; repayment 1500000.0 | same dates and balances |
| TC9 | 2026-06-30→2026-09-30; pay 2026-09-30; balance 1900000.0; repayment 0.0<br>2026-09-30→2026-12-31; pay 2026-12-31; balance 1662500.0; repayment 237500.0<br>2026-12-31→2027-03-31; pay 2027-03-31; balance 1425000.0; repayment 237500.0<br>2027-03-31→2027-06-30; pay 2027-06-30; balance 1187500.0; repayment 237500.0<br>2027-06-30→2027-09-30; pay 2027-09-30; balance 950000.0; repayment 237500.0<br>2027-09-30→2027-12-31; pay 2027-12-31; balance 712500.0; repayment 237500.0<br>2027-12-31→2028-03-31; pay 2028-03-31; balance 475000.0; repayment 237500.0<br>2028-03-31→2028-05-31; pay 2028-05-31; balance 237500.0; repayment 237500.0 | 2026-06-30→2026-09-30; pay 2026-09-30; balance 1900000.0; repayment 0.0<br>2026-09-30→2026-12-31; pay 2026-12-31; balance 1662500.0; repayment 237500.0<br>2026-12-31→2027-03-31; pay 2027-03-31; balance 1425000.0; repayment 237500.0<br>2027-03-31→2027-06-30; pay 2027-06-30; balance 1187500.0; repayment 237500.0<br>2027-06-30→2027-09-30; pay 2027-09-30; balance 950000.0; repayment 237500.0<br>2027-09-30→2027-12-31; pay 2027-12-31; balance 712500.0; repayment 237500.0<br>2027-12-31→2028-03-31; pay 2028-03-31; balance 475000.0; repayment 237500.0<br>2028-03-31→2028-05-31; pay 2028-05-31; balance 237500.0; repayment 237500.0 | same dates and balances |
| TC10 | 2026-03-31→2027-03-31; pay 2027-03-31; balance 54400000.0; repayment 0.0<br>2027-03-31→2027-06-30; pay 2027-06-30; balance 27200000.0; repayment 27200000.0 | same shared amortization_schedule | one shared source schedule |

TC1–TC9 source amortization periods have matching dates and balances across the two legs. TC10 provides one shared schedule. TC4 has five amortization rows but four detailed fixed, floating, and net cashflow rows. TC1 raw source balances are residual-scale values; canonical TC1 uses the confirmed 530000 and 265000 amounts.

## 7. Market-data references

| Case | Currency / benchmark | Curve-family label in raw source, if any | Currency market-data fixture present |
|---|---|---|---|
| TC1 | USD / SOFRRATE (1D) | not labeled in raw source | Yes: `market_data/2026-03-31/USD/market_data.json` |
| TC2 | CHF / SF0006M (6M) | CHF OIS SARON | Yes: `market_data/2026-03-31/CHF/market_data.json` |
| TC3 | USD / SOFRRATE (1D) | USD SOFR | Yes: `market_data/2026-03-31/USD/market_data.json` |
| TC4 | USD / SOFRRATE (1D) | USD SOFR | Yes: `market_data/2026-03-31/USD/market_data.json` |
| TC5 | INR / IRSWOF (6M) | INR OIS | Yes: `market_data/2026-03-31/INR/market_data.json` |
| TC6 | JPY / MUTKCALM (1D) | not labeled in raw source | Yes: `market_data/2026-03-31/JPY/market_data.json` |
| TC7 | CHF / SF0006M (6M) | not labeled in raw source | Yes: `market_data/2026-03-31/CHF/market_data.json` |
| TC8 | INR / IRSWOF (6M) | not labeled in raw source | Yes: `market_data/2026-03-31/INR/market_data.json` |
| TC9 | INR / IRSWOF (6M) | not labeled in raw source | Yes: `market_data/2026-03-31/INR/market_data.json` |
| TC10 | JPY / MUTKCALM (1D) | discount_curve=JPY OIS, forward_curve=JPY OIS | Yes: `market_data/2026-03-31/JPY/market_data.json` |

The currency market-data JSON fixtures exist for USD, CHF, INR, and JPY. This inventory does not assign or construct a curve when the source lacks an explicit curve label.

## 8. Cross-case observations

- Currencies/benchmarks: USD/SOFRRATE (TC1, TC3, TC4); CHF/SF0006M (TC2, TC7); INR/IRSWOF (TC5, TC8, TC9); JPY/MUTKCALM (TC6, TC10).
- Reset timing: In Arrears for TC1, TC3, TC4, TC6, TC10; In Advance for TC2, TC5, TC7, TC8, TC9.
- Floating reset cadence differs from floating payment cadence in TC2 (SemiAnnual reset / Quarterly pay), TC5 (SemiAnnual / Annual), TC7 (SemiAnnual / Annual), and TC9 (SemiAnnual / Quarterly).
- Fixed and floating day-count labels differ in TC2 (30/360 vs ACT/360) and TC7 (30/360 vs ACT/360); they match in the other source cases.
- `Flat` appears as floating compounding in TC5 and TC7. `ExcludeSprd` appears in TC1, TC3, TC4, TC6, and TC10. The raw source has null/absent compounding for TC2, TC8, and TC9.
- Lookback/cutoff fields appear most explicitly in TC1, TC3, TC4, TC6, TC10: zero days before accrual/lookback and one cutoff day. TC2, TC5, TC7, TC8, TC9 report `days_before_accrual: 1` but do not supply a consistent lookback type/cutoff pair.
- The raw schedules include short or irregular boundary periods in TC1, TC2, TC3, TC4, TC5, TC7, TC8, TC9, and TC10. TC6 shows three semiannual amortization periods; no separate stub is identified here. Dates are preserved verbatim in source and reference files.
- TC4 and TC8 effective dates precede valuation date 2026-03-31. TC4 has a 2026-01-01→2026-03-31 amortization row; its detailed cashflows start later.

## 9. Unknown / unresolved items

- Source schemas differ by case family: TC1–TC5 use root-level trade/leg/output sections; TC6–TC9 put legs and outputs inside `trade`; TC10 uses separate fixed/floating/valuation sections.
- TC1 source `trade.notional` is 530000 but leg notional and amortization fields retain residual 1000× values; SME clarification establishes canonical 530000 → 265000. TC2 source also has top-level trade notional 20000 and leg notional 20000000; no normalization was supplied for TC2.
- TC1 `contract_detail` first/next-last payment dates differ from the detailed amortization and cashflow dates. The established canonical schedule is 2026-05-31 → 2027-05-28 → 2027-11-30.
- Source NPVs under separate labels differ in several cases. TC1–TC5 market-summary leg NPVs differ from detailed cashflow-leg NPVs. TC6–TC9 direct leg-summary NPVs differ from detailed cashflow-leg NPVs. TC7 also has `valuation_results.npv = -388.06` versus `cashflows.net_npv = -328.72`; no source rule resolves this. TC8 has leg summary NPVs -4670125.07 / 4530610.09 versus detailed cashflow-leg NPVs -373543.3 / 234028.32.
- Coupon-unit fields are absent on TC6–TC9 fixed legs. Observation fields such as lookback type, cutoff, and compounding are absent or null in some cases. Missing fields do not establish defaults.
- Some market labels are explicit in source (e.g. CHF OIS SARON, USD SOFR, INR OIS, JPY OIS); others are represented only by currency and benchmark. The existence of a currency market-data fixture does not establish a curve mapping for each leg.
- Values for fees, accrued amounts, risk, premium, par coupon, principal, PV01/DV01, cashflow discounts, reset information, and equivalent coupons are retained where source sections provide them. The report does not establish their calculation meaning beyond source field names.
