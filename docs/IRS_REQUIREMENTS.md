# Optima IRS Requirements Baseline

This document records the IRS requirements established by stakeholder feedback and the canonical test case. Repository behavior is cited as evidence where useful, but an existing implementation default is not treated as a stakeholder requirement unless confirmed.

## A. Confirmed Requirements

1. **[CONFIRMED] Independent payment frequencies.** The fixed and floating legs each have a configurable payment frequency. Observed values include Quarterly, Semiannual, and Annual.

2. **[CONFIRMED] Independent floating reset frequency.** Floating reset frequency is a separate trade input and must not be inferred from floating payment frequency. Observed combinations are Daily reset / Annual payment; Daily / Semiannual; Semiannual / Annual; Semiannual / Quarterly; and Semiannual / Semiannual.

3. **[CONFIRMED] Separate principal repayment schedules.** Each leg has its own repayment schedule. The input concept includes Payment Date, Principal Repayment — Pay, and Principal Repayment — Receive.

4. **[CONFIRMED] Repayment is an amount input.** Principal repayment amounts are the underlying input. A percentage is not required as the principal repayment representation.

5. **[CONFIRMED] Independent Pay and Receive schedules.** The schedules may have different row counts and dates. They must not be forced into matching lengths.

6. **[CONFIRMED] Repayment and principal exchange are distinct.** A principal repayment changes outstanding notional for subsequent periods. It does not, by itself, create a separate principal-exchange cashflow. Principal Exchange is a separate trade term.

7. **[CONFIRMED] Fixed coupon is contractual input.** It is supplied with the trade, remains constant across periods, and is not derived from market data. Percentage and basis-point representations may be accepted at input; the pricing core receives a normalized rate.

8. **[CONFIRMED] Fixed-leg cashflow relationship.** For each coupon period, the fixed coupon amount is based on `Period Notional × Fixed Coupon × Accrual Fraction`.

9. **[CONFIRMED] Fixed-leg day-count labels.** ACT/360, ACT/365, and 30/360 are required/observed labels. The existing IRS implementation maps `30/360` to QuantLib `Thirty360(BondBasis)` and `ACT/365` to `Actual365Fixed`; these mappings are **CONFIRMED repository behavior** for the current path. Any requirement for a different variant is **OPEN** and must not be inferred.

10. **[CONFIRMED] Configurable floating benchmark.** Observed benchmark identifiers include SOFRRATE 1D, SF0006M 6M, IRSWOF 6M, and MUTKCALM 1D. The selected benchmark and tenor are trade inputs.

11. **[CONFIRMED] Configurable floating spread.** Spread is supplied in basis points at the input layer and normalized for pricing. A fixed +10 bp is not a general IRS requirement.

12. **[CONFIRMED] Separate observation conventions.** Lookback, cutoff, and In Advance / In Arrears are distinct concepts and inputs; one must not be substituted for another.

13. **[CONFIRMED] Valuation date does not define the contractual schedule.** Schedule generation is based on trade terms. Valuation date supplies valuation context and must not silently redefine contractual dates.

14. **[CONFIRMED] Correct schedule dates and stub support.** Accrual start/end dates and payment dates must follow the trade terms, including required stub periods.

15. **[CONFIRMED] No silent convention selection.** Unconfirmed stub rules, business-day conventions, day-count variants, and unresolved Bloomberg/SME behavior must not be silently assumed.

## B. Observed Test-Case Evidence

1. **[CONFIRMED — canonical fixture/test]** SLLSL9RR is a USD swap with original notional 530,000 and a 50% reduction to 265,000. Its repayment schedule is represented by coupon-period notionals 530,000 then 265,000, with principal exchange set to Never.

2. **[CONFIRMED — canonical fixture/test]** The schedule is 2026-05-31 to 2027-05-28, then 2027-05-28 to 2027-11-30. The first accrual start remains 2026-05-31; payment dates are 2027-05-28 and 2027-11-30.

3. **[CONFIRMED — canonical fixture/test]** The fixed leg is payer at 5%, Annual, ACT/360. Its calculated coupon amounts are approximately 26,647.22 and 6,845.83.

4. **[CONFIRMED — canonical fixture/test]** The floating leg is receiver SOFR 1D, Daily reset, Annual payment, ACT/360, 10 bp spread, leverage 1, In Arrears, one-day lookback, one-day cutoff, and ExcludeSprd. These values describe this case; they are not defaults for other IRS trades.

5. **[CONFIRMED — canonical test evidence]** The existing focused schedule test checks accrual boundaries, payment dates, coupon-period notionals, and fixed coupon amounts independently of floating-rate calculation.

6. **[CONFIRMED — repository observation, not a Bloomberg convention]** The current USD discount-curve builder passes supplied discount-factor pillars to QuantLib `DiscountCurve`, adds a reference-date DF of 1.0, and uses QuantLib's default LogLinear interpolation. This records current implementation behavior only; it does not establish a Bloomberg interpolation requirement.

## C. Explicitly Excluded / Rejected Requirements

1. **[CONFIRMED — EXCLUDED]** Pay and Receive principal repayment schedules do not need the same number of rows.

2. **[CONFIRMED — REJECTED]** Percentage amortization is not required as the underlying repayment input when the trade input is principal-repayment amounts. A percentage shown in a test-case description may be descriptive or derived.

3. **[CONFIRMED — REJECTED]** Principal repayment/amortization does not automatically require a separate principal-exchange cashflow.

4. **[CONFIRMED — REJECTED]** Floating reset frequency must not be assumed equal to floating payment frequency.

5. **[CONFIRMED — REJECTED]** Fixed coupon must not be inferred from a market curve or other market data.

6. **[CONFIRMED — REJECTED]** The canonical case's 10 bp spread, Daily reset, Annual payment, SOFR index, conventions, or amortization percentage must not be hard-coded as universal IRS behavior.

## D. Open Questions / SME Confirmation Required

1. **[OPEN] Stub policy.** The supported first/last stub types, long/short behavior, explicit stub-date inputs, and generation direction for trades other than cases with supplied schedule dates are not fully specified.

2. **[OPEN] Business-day rules.** The business-day convention, calendar, termination-date convention, and any distinction between adjusting accrual dates and payment dates must be specified for each applicable trade or convention set.

3. **[OPEN] Day-count variants.** Confirm which 30/360 variant is intended where that label is used. Confirm the intended ACT/365 variant if the distinction matters to a trade.

4. **[OPEN] Repayment amount semantics.** Confirm sign conventions, currency/units, whether each dated amount applies at the start or end of its effective period, and how same-date Pay and Receive amounts are represented. The Pay and Receive schedules remain independent regardless of row count.

5. **[OPEN] Principal exchange choices.** The canonical case specifies Never. The supported exchange choices and how they coexist with independent repayment schedules are not established here.

6. **[OPEN] Reset and observation details.** Confirm the unit/calendar for lookback and cutoff counts, the exact cutoff/lockout behavior, fixing-date generation, and the precise In Advance / In Arrears mapping for each supported benchmark.

7. **[OPEN] Benchmark mapping.** Confirm how each observed identifier and tenor maps to an index, calendar, fixing convention, and projection input. Identifiers listed in section A are observed labels, not a complete mapping specification.

8. **[OPEN] Floating coupon mechanics.** The canonical case records ExcludeSprd, but the full supported set of compounding/averaging conventions and the interpretation of each benchmark's quoted market data are not established for all trades. Do not infer unresolved Bloomberg behavior from one case.

9. **[OPEN] Input representation details.** Percentage and bps inputs are permitted, with a normalized pricing-core rate. The exact field names, validation rules, and how an input declares its unit remain to be specified.

10. **[OPEN] Valuation and fixing data.** Missing-fixing policy, historic fixing sources, curve selection per leg, and approved valuation tolerances are not defined by this requirements baseline.

## E. Design Principles

1. **[CONFIRMED]** Keep fixed-leg, floating-leg, reset, principal-repayment, principal-exchange, and observation terms distinct.

2. **[CONFIRMED]** Preserve independent Pay and Receive leg parameters and schedules throughout request parsing, instrument construction, and cashflow generation.

3. **[CONFIRMED]** Represent principal repayment by dated amounts and apply repayments to subsequent outstanding notional as specified by the trade.

4. **[CONFIRMED]** Normalize supported coupon input units before pricing while preserving the contractual fixed coupon as a trade input.

5. **[CONFIRMED]** Keep contractual schedule generation independent from valuation-date setup.

6. **[CONFIRMED]** Require explicit convention inputs or approved mappings where the requirement is open; do not rely on silent defaults for economically material terms.

## F. Requirements Not Yet Specified

1. **[OPEN]** Full supported frequency sets and any frequency-specific restrictions beyond the observed examples.

2. **[OPEN]** Per-leg calendars, business-day conventions, end-of-month behavior, payment delays, and termination-date adjustment rules.

3. **[OPEN]** Exact schedule-generation and stub inputs when a trade does not supply coupon-period dates.

4. **[OPEN]** Complete principal-repayment schema, including amount signs, date application, and the treatment of repayments on non-business dates.

5. **[OPEN]** Complete principal-exchange schema and its permitted combinations with amortization.

6. **[OPEN]** Complete index registry and index-specific conventions for the observed benchmark identifiers.

7. **[OPEN]** Complete floating-rate observation, compounding, averaging, spread treatment, and fixing-source rules by benchmark.

8. **[OPEN]** API serialization, validation, backward compatibility, and error behavior for IRS-specific inputs.

## Implementation Guardrails

- No pricing implementation should begin from assumptions not marked **CONFIRMED**.
- Pay and Receive leg parameters must remain independently configurable.
- Payment, reset, principal-repayment, and observation schedules must remain conceptually separate.
- Percentage amortization seen in test-case descriptions must not be hard-coded as the underlying representation when the actual input model is principal-repayment amounts.
