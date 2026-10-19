# TC1 Floating Rate Construction Trace

This is a read-only trace of the current fresh IRS path for TC1 / SLLSL9RR. The projection construction is explicitly provisional. No Bloomberg methodology is inferred, and Bloomberg values are used only as supplied reference data.

## 1. TC1 Period 1 Contractual Inputs

| Input | Value |
|---|---:|
| Trade / currency | SLLSL9RR / USD |
| Valuation and curve reference date | 2026-03-31 |
| Accrual period / payment date | 2026-05-31 to 2027-05-28 / 2027-05-28 |
| Period notional | 530,000 USD in the normalized case fixture and Optima coupon |
| Floating benchmark / tenor | SOFR / 1D (source benchmark ID: `SOFRRATE`) |
| Reset / payment frequency | Daily / Annual |
| Day count / actual accrual days | ACT/360 / 362 |
| Spread / gearing | 10 bp = 0.001 / 1.0 |
| Observation terms | 1-day Lookback, 1-day cutoff, In Arrears, `ExcludeSprd` |

The contract inputs are in [TC1.json](../tests/fixtures/bloomberg_irs/cases/TC1.json). The domain conversion normalizes 10 bps to a decimal spread of 0.001 and the percentage fixed/floating inputs to decimal rates in the baseline test helper.

## 2. Bloomberg Market Data Used

The USD SOFR market-data fixture has reference date 2026-03-31. Around the first QuantLib SOFR observation, the relevant quoted Market Rate nodes are:

| Quote date | Market Rate (displayed %) | Decimal rate used by provisional builder |
|---|---:|---:|
| 2026-04-30 | 3.66085% | 0.0366085 |
| 2026-05-30 | 3.67050% | 0.0367050 |
| 2026-06-29 | 3.67680% | 0.0367680 |

These are from [USD market_data.json](../market_data/2026-03-31/USD/market_data.json). The supplied Discount Factor values are **not** used to construct the projection curve; they belong to the separate discount curve.

The first fixing's SOFR value dates are 2026-05-29 to 2026-06-01. Its start date falls between the 2026-04-30 and 2026-05-30 synthetic projection pillars; its end date falls between the 2026-05-30 and 2026-06-29 pillars. Thus the first overnight rate depends on three adjacent quoted Market Rate nodes through those two interpolation segments. The entire annual coupon uses the curve for all 248 fixing dates, not only these initial nodes.

## 3. Current Optima Projection-Curve Construction

The implementation is in [irs_provisional_projection.py](../market/curves/irs_provisional_projection.py#L70-L87). For each quote at date `T`, it:

1. Divides the displayed percentage by 100 to obtain `R(T)`.
2. Calculates `tau = Actual/360(reference date, T)`.
3. Creates a **synthetic projection** discount factor `D(T) = 1 / (1 + R(T) * tau)`.
4. Adds the reference anchor `(2026-03-31, 1.0)` and constructs `ql.DiscountCurve(dates, discounts, Actual360())`.

For the three nodes above, the exact builder inputs and resulting synthetic factors are:

| Pillar | ACT/360 from 2026-03-31 | Synthetic projection DF |
|---|---:|---:|
| 2026-04-30 | 30/360 = 0.0833333333 | 0.9969585701819579 |
| 2026-05-30 | 60/360 = 0.1666666667 | 0.9939196962581408 |
| 2026-06-29 | 90/360 = 0.25 | 0.9908917232796137 |

This is the current provisional transformation, not a claim that it is Bloomberg's intended projection methodology.

## 4. QuantLib Forward-Rate Path

The current floating-leg path is in [floating_leg.py](../instruments/rates/irs/floating_leg.py#L43-L59) and [floating_leg.py](../instruments/rates/irs/floating_leg.py#L171-L222):

- It creates `ql.Sofr(forwarding_curve)`, with the provisional projection `YieldTermStructureHandle` passed by the baseline composition. The index is SOFR, not a separately supplied historical fixing series.
- It builds an `ql.OvernightLeg`, then wraps its period cashflows as `ql.OvernightIndexedCoupon` objects.
- The coupon uses compound averaging, 1-day lookback, `inArrears=True`, and `compoundSpreadDaily=False`.
- The fixture's 1-day cutoff is retained as contractual metadata, but the current mapping sets QuantLib `lockoutDays=0` and `cutoff_mapping=None`. Therefore the actual QuantLib coupon does **not** apply a one-day cutoff/lockout.
- `gearing=1.0`; spread is passed separately as `0.001`.
- The fixture's explicit payment date is retained and payment lag is zero.

QuantLib's actual first fixing date is 2026-05-29. The SOFR index maps that fixing to value dates 2026-05-29 through 2026-06-01, a three-calendar-day accrual over a Friday-to-Monday weekend. The observed first fixing-date sequence begins 2026-05-29, 2026-06-01, 2026-06-02, 2026-06-03, 2026-06-04; it ends 2027-05-20, 2027-05-21, 2027-05-24, 2027-05-25, 2027-05-26. The coupon contains 248 fixing dates.

For each overnight forecast, QuantLib obtains the SOFR index rate from the projection curve over that fixing's value-date interval. In the first interval:

- `D(2026-05-29) = 0.9940208426626224`, LogLinear-interpolated between synthetic pillars 2026-04-30 and 2026-05-30.
- `D(2026-06-01) = 0.9937175438372362`, LogLinear-interpolated between synthetic pillars 2026-05-30 and 2026-06-29.
- ACT/360 interval fraction = 3/360.
- The implied simple overnight forward is `(D(start)/D(end) - 1) / (3/360) = 0.03662596003468188`, or **3.662596003468188%**.

The matching QuantLib `ql.Sofr` forecast for the first fixing date is 0.03662596003468188. The projection curve's `ql.DiscountCurve` uses LogLinear interpolation of discount factors (linear interpolation of log discount factors in time); the supplied market-data Discount Factor column is not involved.

## 5. Numerical Trace

| Stage | Period 1 value |
|---|---:|
| First fixing date | 2026-05-29 |
| First fixing value dates | 2026-05-29 to 2026-06-01 |
| Projection DF at value-date start | 0.9940208426626224 |
| Projection DF at value-date end | 0.9937175438372362 |
| First projected SOFR rate, before spread | 3.662596003468188% |
| Overnight observations in full coupon | 248 fixing dates, daily compounded |
| Full-period compounded SOFR component, before spread | 3.6497404233424804% equivalent coupon |
| Gearing | 1.0 |
| Spread added outside daily compounding | 0.1000000000000000% (10 bp) |
| Final QuantLib coupon rate | 3.7497404233424805% |
| Notional | 530,000 USD |
| Accrual fraction | 362/360 = 1.0055555555555555 |
| Floating coupon amount | 19,984.03326729134 USD |

The 3.6497404233% figure is the whole-period compounded SOFR component inferred from the coupon's public `rate()`, after removing the separately applied spread and gearing. It is not the first daily fixing. The final cashflow follows the QuantLib coupon calculation: `nominal × coupon rate × accrual fraction`.

## 6. Bloomberg vs Optima Coupon

| Metric | Bloomberg reference | Current Optima | Optima minus Bloomberg |
|---|---:|---:|---:|
| Period 1 equivalent coupon | 3.785460000% | 3.749740423% | -0.035719577 percentage points (-3.571958 bp) |
| Period 1 floating payment | 20,174.40 | 19,984.033267 | -190.366733 |

The Bloomberg reference is in [TC1 reference fixture](../tests/fixtures/bloomberg_irs/references/TC1.json#L91-L101). The reference source's period notional is recorded as 530,000,000, while the normalized canonical case and current Optima coupon use 530,000; this known 1000x source artifact is not silently normalized in the raw oracle. Bloomberg's detailed cashflow also records payment date 2027-05-28, accrual 2026-05-31 through 2027-05-28, 362 days, and `effective_reset_date` 2027-05-27.

## 7. What We Can Establish

**Directly demonstrated by current implementation:**

- The provisional builder converts every displayed Market Rate quote to a synthetic reference-date discount factor using simple ACT/360 compounding, then creates a LogLinear `ql.DiscountCurve`.
- The floating leg uses that curve through `ql.Sofr`; QuantLib forecasts daily overnight rates, compounds them over 248 observations, applies gearing 1.0, and adds the 10 bp spread outside daily compounding.
- Although the domain has `cutoff_days=1`, the actual QuantLib leg uses `lockoutDays=0`; the current coupon therefore has no mapped one-day cutoff.
- Current period-1 coupon is 3.7497404233% and cashflow is 19,984.033267.

**Directly supplied by Bloomberg reference data:**

- Equivalent coupon 3.78546%, floating payment 20,174.40, payment date 2027-05-28, period dates, 362 days, and effective reset date 2027-05-27.
- No individual daily SOFR observations/fixings are listed in the reference row.

**Conclusion supported by comparing them:**

- The current Optima coupon is 3.571958 bp below the supplied Bloomberg equivalent coupon, and its receive cashflow is 190.366733 below the supplied Bloomberg payment on the normalized 530,000 notional basis.
- The current implementation's arithmetic path is explicit and reproducible. This comparison identifies a difference but does not establish which Bloomberg calculation convention or market-data transformation produces it.

## 8. What Remains Unknown

- The supplied Bloomberg simple Market Rate nodes do not by themselves expose the daily fixing/forecast sequence Bloomberg used for this coupon. Bloomberg's equivalent coupon and aggregate payment are outputs, not a complete observation history.
- The reference's `effective_reset_date=2027-05-27` is supplied, but individual observation dates, daily rates, and the detailed treatment of the 1-day cutoff are not supplied here. It cannot be used to infer Bloomberg's hidden daily compounding mechanics.
- The current Optima implementation does not map the fixture's one-day cutoff to QuantLib lockout; whether Bloomberg's “cutoff” has an equivalent QuantLib lockout interpretation is not established by this trace.
- The provisional projection conversion and interpolation are current implementation behavior only. This diagnostic does not establish that they represent Bloomberg's intended curve semantics.

Accordingly, the Bloomberg equivalent coupon cannot be independently reconstructed from the fields available in the reference fixture alone.
