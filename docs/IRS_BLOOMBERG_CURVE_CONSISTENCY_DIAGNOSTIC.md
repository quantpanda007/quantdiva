# Bloomberg Curve Consistency Diagnostic — USD TC1 / TC3

Read-only numerical comparison of the USD market-data columns in `market_data/2026-03-31/USD/market_data.json`. No production code, fixture, reference data, or test was changed. Market rates and discount factors are treated as separate supplied inputs; no Bloomberg coupon is used to construct or tune either curve.

## Diagnostic conventions and limits

For a diagnostic comparison, the reference date is 2026-03-31 and the year fraction is ACT/360. The simple zero rate implied by each supplied DF is calculated as:

`z_simple(T) = (1 / DF(T) - 1) / tau(reference, T)`

This uses `DF(T) = 1 / (1 + z * tau)`. Difference is implied simple zero minus the supplied Market Rate, in percentage points. This is one explicit standard interpretation, not a claim about Bloomberg's zero-rate convention.

For each adjacent pair of supplied DF pillars, the simple forward implied by those DFs is:

`f_simple(T0,T1) = (DF(T0) / DF(T1) - 1) / tau(T0,T1)`

The reference-date anchor `2026-03-31 → DF 1.0` is used for the first interval only. This diagnostic does not interpolate DFs at dates between the observed pillars.

## 1. Discount-factor implied rates

All rates below are percent per annum. The supplied Market Rate values are displayed as percentages in the source fixture.

| Date | Market Rate (%) | Supplied DF | ACT/360 tau from reference | Implied simple zero (%) | Difference (pp) | Current provisional synthetic DF | Synthetic − supplied DF |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-04-07 | 3.652400 | 0.999088 | 0.019444 | 4.694567 | +1.042167 | 0.999290315 | +0.000202315 |
| 2026-04-14 | 3.653700 | 0.998379 | 0.038889 | 4.175053 | +0.521353 | 0.998581133 | +0.000202133 |
| 2026-04-21 | 3.654050 | 0.997671 | 0.058333 | 4.001892 | +0.347842 | 0.997873005 | +0.000202005 |
| 2026-04-30 | 3.660850 | 0.996554 | 0.083333 | 4.149499 | +0.488649 | 0.996958570 | +0.000404570 |
| 2026-05-30 | 3.670500 | 0.993617 | 0.166667 | 3.854403 | +0.183903 | 0.993919696 | +0.000302696 |
| 2026-06-29 | 3.676800 | 0.990591 | 0.250000 | 3.799348 | +0.122548 | 0.990891723 | +0.000300723 |
| 2026-07-29 | 3.679450 | 0.987384 | 0.333333 | 3.833159 | +0.153709 | 0.987883770 | +0.000499770 |
| 2026-08-28 | 3.680300 | 0.984400 | 0.416667 | 3.803332 | +0.123032 | 0.984897015 | +0.000497015 |
| 2026-09-27 | 3.683000 | 0.981423 | 0.500000 | 3.785727 | +0.102727 | 0.981917980 | +0.000494980 |
| 2026-10-27 | 3.687500 | 0.978352 | 0.583333 | 3.793201 | +0.105701 | 0.978942538 | +0.000590538 |
| 2026-11-26 | 3.691250 | 0.975394 | 0.666667 | 3.784009 | +0.092759 | 0.975982693 | +0.000588693 |
| 2026-12-26 | 3.694900 | 0.972159 | 0.750000 | 3.818443 | +0.123543 | 0.973035484 | +0.000876484 |
| 2027-01-25 | 3.697500 | 0.969332 | 0.833333 | 3.796594 | +0.099094 | 0.970108531 | +0.000776531 |
| 2027-02-24 | 3.698500 | 0.966628 | 0.916667 | 3.766270 | +0.067770 | 0.967208801 | +0.000580801 |
| 2027-03-26 | 3.700950 | 0.963638 | 1.000000 | 3.773409 | +0.072459 | 0.964311320 | +0.000673320 |
| 2027-09-22 | 3.660000 | 0.946232 | 1.500000 | 3.788218 | +0.128218 | 0.947957152 | +0.001725152 |
| 2028-03-30 | 3.621050 | 0.930085 | 2.027778 | 3.707041 | +0.085991 | 0.931595854 | +0.001510854 |
| 2029-03-30 | 3.578050 | 0.898410 | 3.041667 | 3.717618 | +0.139568 | 0.901849586 | +0.003439586 |
| 2030-03-30 | 3.585250 | 0.866701 | 4.055556 | 3.792340 | +0.207090 | 0.873056071 | +0.006355071 |
| 2031-03-30 | 3.621550 | 0.834704 | 5.069444 | 3.906335 | +0.284785 | 0.844885406 | +0.010181406 |

Under this simple ACT/360 calculation, every DF-implied zero is higher than its same-date Market Rate, by 0.067770 to 1.042167 percentage points.

## 2. Adjacent DF-implied forwards

For the first row, the start is the reference-date anchor with DF 1.0 and no Market Rate quote. For later rows, the start/end Market Rate columns show the quotes at those two pillars; per the settled SME description, those quotes are reference-date forward rates, not interval forwards. They are shown for numerical context only.

| Start | End | DF(start) | DF(end) | ACT/360 days | Implied simple forward (%) | Market Rate at start (%) | Market Rate at end (%) |
|---|---|---:|---:|---:|---:|---:|---:|
| 2026-03-31 | 2026-04-07 | 1.000000 | 0.999088 | 7 | 4.694567 | — | 3.652400 |
| 2026-04-07 | 2026-04-14 | 0.999088 | 0.998379 | 7 | 3.652206 | 3.652400 | 3.653700 |
| 2026-04-14 | 2026-04-21 | 0.998379 | 0.997671 | 7 | 3.649643 | 3.653700 | 3.654050 |
| 2026-04-21 | 2026-04-30 | 0.997671 | 0.996554 | 9 | 4.483450 | 3.654050 | 3.660850 |
| 2026-04-30 | 2026-05-30 | 0.996554 | 0.993617 | 30 | 3.547041 | 3.660850 | 3.670500 |
| 2026-05-30 | 2026-06-29 | 0.993617 | 0.990591 | 30 | 3.665690 | 3.670500 | 3.676800 |
| 2026-06-29 | 2026-07-29 | 0.990591 | 0.987384 | 30 | 3.897572 | 3.676800 | 3.679450 |
| 2026-07-29 | 2026-08-28 | 0.987384 | 0.984400 | 30 | 3.637546 | 3.679450 | 3.680300 |
| 2026-08-28 | 2026-09-27 | 0.984400 | 0.981423 | 30 | 3.640021 | 3.680300 | 3.683000 |
| 2026-09-27 | 2026-10-27 | 0.981423 | 0.978352 | 30 | 3.766742 | 3.683000 | 3.687500 |
| 2026-10-27 | 2026-11-26 | 0.978352 | 0.975394 | 30 | 3.639145 | 3.687500 | 3.691250 |
| 2026-11-26 | 2026-12-26 | 0.975394 | 0.972159 | 30 | 3.993174 | 3.691250 | 3.694900 |
| 2026-12-26 | 2027-01-25 | 0.972159 | 0.969332 | 30 | 3.499730 | 3.694900 | 3.697500 |
| 2027-01-25 | 2027-02-24 | 0.969332 | 0.966628 | 30 | 3.356824 | 3.697500 | 3.698500 |
| 2027-02-24 | 2027-03-26 | 0.966628 | 0.963638 | 30 | 3.723390 | 3.698500 | 3.700950 |
| 2027-03-26 | 2027-09-22 | 0.963638 | 0.946232 | 180 | 3.679013 | 3.700950 | 3.660000 |
| 2027-09-22 | 2028-03-30 | 0.946232 | 0.930085 | 190 | 3.289411 | 3.660000 | 3.621050 |
| 2028-03-30 | 2029-03-30 | 0.930085 | 0.898410 | 365 | 3.477376 | 3.621050 | 3.578050 |
| 2029-03-30 | 2030-03-30 | 0.898410 | 0.866701 | 365 | 3.608468 | 3.578050 | 3.585250 |
| 2030-03-30 | 2031-03-30 | 0.866701 | 0.834704 | 365 | 3.780823 | 3.585250 | 3.621550 |

The adjacent implied forwards range from 3.289411% to 4.694567%. They need not equal either endpoint's reference-date Market Rate: they describe a different interval quantity under this diagnostic formula.

## 3. TC1 relevant dates

This table identifies the supplied pillars bracketing each TC1 accrual boundary. Each pillar's Market Rate, DF, and simple ACT/360 zero rate are observed/calculated node quantities from Section 1. The implied-forward column is the simple ACT/360 forward between the two bracket pillars, from Section 2. No DF is interpolated to the contractual date.

| TC1 boundary | Accrual period | Lower pillar: date / Market Rate / DF / implied zero | Upper pillar: date / Market Rate / DF / implied zero | Adjacent DF-implied forward over bracket (%) |
|---|---|---|---|---:|
| 2026-05-31 | P1 start | 2026-05-30 / 3.67050% / 0.993617 / 3.854403% | 2026-06-29 / 3.67680% / 0.990591 / 3.799348% | 3.665690 |
| 2027-05-28 | P1 end; P2 start | 2027-03-26 / 3.70095% / 0.963638 / 3.773409% | 2027-09-22 / 3.66000% / 0.946232 / 3.788218% | 3.679013 |
| 2027-11-30 | P2 end | 2027-09-22 / 3.66000% / 0.946232 / 3.788218% | 2028-03-30 / 3.62105% / 0.930085 / 3.707041% | 3.289411 |

## 4. TC3 relevant dates

As above, “adjacent DF-implied forward” describes only the forward over the surrounding observed-pillar interval; it is not asserted to be the rate at the contractual boundary or the coupon.

| TC3 boundary | Accrual period | Lower pillar: date / Market Rate / DF / implied zero | Upper pillar: date / Market Rate / DF / implied zero | Adjacent DF-implied forward over bracket (%) |
|---|---|---|---|---:|
| 2026-05-31 | P1 start | 2026-05-30 / 3.67050% / 0.993617 / 3.854403% | 2026-06-29 / 3.67680% / 0.990591 / 3.799348% | 3.665690 |
| 2026-11-30 | P1 end; P2 start | 2026-11-26 / 3.69125% / 0.975394 / 3.784009% | 2026-12-26 / 3.69490% / 0.972159 / 3.818443% | 3.993174 |
| 2027-05-28 | P2 end; P3 start | 2027-03-26 / 3.70095% / 0.963638 / 3.773409% | 2027-09-22 / 3.66000% / 0.946232 / 3.788218% | 3.679013 |
| 2027-11-30 | P3 end; P4 start | 2027-09-22 / 3.66000% / 0.946232 / 3.788218% | 2028-03-30 / 3.62105% / 0.930085 / 3.707041% | 3.289411 |
| 2028-04-28 | P4 end | 2028-03-30 / 3.62105% / 0.930085 / 3.707041% | 2029-03-30 / 3.57805% / 0.898410 / 3.717618% | 3.477376 |

## 5. Relationship to Bloomberg Equivalent Coupons

The supplied coupon values below are displayed Bloomberg reference outputs. “End-date Market Rate” is the previously calculated date-linear interpolation of Market Rate at the contractual accrual end. “Bracket DF forward” is the adjacent-pillar DF-implied forward above. These are different mathematical quantities; the table is a numerical comparison, not an assertion that either rate is the Bloomberg Equivalent Coupon.

| Case / period | Bloomberg Equivalent Coupon (%) | End-date interpolated Market Rate (%) | Spread (bp) | End-date Market Rate + spread (%) | Bracket DF-implied forward (%) |
|---|---:|---:|---:|---:|---:|
| TC1 P1, end 2027-05-28 | 3.78546 | 3.6866175 | 10 | 3.7866175 | 3.679013 |
| TC1 P2, end 2027-11-30 | 3.64025 | 3.6458550 | 10 | 3.7458550 | 3.289411 |
| TC3 P1, end 2026-11-30 | 4.37572 | 3.6917367 | 70 | 4.3917367 | 3.993174 |
| TC3 P2, end 2027-05-28 | 4.32764 | 3.6866175 | 70 | 4.3866175 | 3.679013 |
| TC3 P3, end 2027-11-30 | 4.24025 | 3.6458550 | 70 | 4.3458550 | 3.289411 |
| TC3 P4, end 2028-04-28 | 4.12404 | 3.6176336 | 70 | 4.3176336 | 3.477376 |

The numbers show no identity between the Bloomberg coupons and either displayed comparison series. The adjacent-pillar forward is not a period coupon; Market Rate is documented as a reference-date forward, and the table does not infer a coupon transformation from it.

## 6. Comparison with current Optima synthetic projection DFs

The current provisional builder, `market/curves/irs_provisional_projection.py`, transforms each displayed Market Rate `R(T)` into `1 / (1 + (R(T)/100) * ACT/360(reference,T))`, anchors the curve at reference DF 1.0, and supplies those synthetic DFs to QuantLib `DiscountCurve`. The supplied Bloomberg DF column is not used by that projection builder. Section 1 compares the two values at every supplied node:

- Current synthetic projection DF exceeds the Bloomberg-supplied DF at all 20 nodes.
- The node difference is +0.000202315 at 2026-04-07 and grows overall to +0.010181406 at 2031-03-30 (not strictly monotonically at every node).
- For example, at 2027-09-22, Market Rate 3.66000% produces synthetic DF 0.947957152, versus supplied DF 0.946232000, a +0.001725152 difference.
- At the TC1/TC3 surrounding pillars: 2027-03-26 synthetic 0.964311320 vs supplied 0.963638; 2027-09-22 synthetic 0.947957152 vs 0.946232; 2028-03-30 synthetic 0.931595854 vs 0.930085; 2029-03-30 synthetic 0.901849586 vs 0.898410.

This shows that the current provisional projection transformation does not reproduce the separate supplied DFs at their nodes. It does not establish which curve the supplied DF column is intended to construct, or what interpolation should be used between its nodes.

## 7. Consistency conclusion (A–D)

**A. Are Market Rate and Discount Factor mathematically consistent under a simple standard curve interpretation?**

Under the explicitly tested simple ACT/360 reference-date zero interpretation, no: the DF-implied simple zero differs from Market Rate at every node. The adjacent DF-implied forwards also differ from the endpoint Market Rate quotes, which is not itself a contradiction because those are distinct forward horizons. Whether the columns are consistent under Bloomberg's actual zero-rate day count, compounding, and construction conventions cannot be determined from the current data alone.

**B. Do the supplied Discount Factors provide enough information to derive the Bloomberg Equivalent Coupon?**

Cannot determine/derive the Bloomberg coupon from the DFs alone using the supplied evidence. The observations provide node discount factors, but the data do not establish the projection interpolation/forecast convention and coupon-level mapping, nor provide daily Bloomberg SOFR observations. The separate Market Rate data and trade observation conventions still do not disclose the source's full equivalent-coupon calculation.

**C. Is there evidence that the supplied Discount Factors are intended for discounting rather than projection?**

There is evidence for a discounting role: the SME describes the column as discount factors from the USD SOFR zero-rate curve, and case market-curve metadata identifies USD SOFR discount curves. However, TC3 metadata also names USD SOFR as its floating forward curve, and the supplied observations do not label a column as exclusively discount-only. Thus the discounting role is supported, but exclusivity and the precise Bloomberg curve semantics cannot be established from these files alone.

**D. Is there sufficient evidence to select a production projection methodology?**

No. The comparison demonstrates that the current synthetic-DF conversion differs from supplied DFs and that simple ACT/360 DF-implied rates do not equal the quoted Market Rates. It does not establish the correct mapping of Bloomberg's reference-date Market Rate quotes into daily SOFR forecasts/coupon calculations.

## 8. Precise SME questions

1. For the supplied DF column, what are the zero curve's day-count convention, compounding convention, and interpolation convention, and are these DFs specifically the discounting curve inputs for the IRS valuation?
2. For the Market Rate column, what exact mathematical definition/horizon does each quoted value use (including units and day count), and what is the intended transformation from those reference-date forward quotes to daily SOFR projection rates?
3. What is the exact Bloomberg definition of the displayed floating `Equivalent Coupon`: daily compounded realized/projected SOFR, a simple period rate, or another measure? Which date/horizon anchors it?
4. How are lookback and one-day rate cutoff applied in Bloomberg's daily observation sequence, and is spread excluded from daily compounding as the case field states?
5. Can Bloomberg provide the period's observation dates and daily SOFR fixing/forward values used to produce the displayed Equivalent Coupon, for TC1 and TC3?
