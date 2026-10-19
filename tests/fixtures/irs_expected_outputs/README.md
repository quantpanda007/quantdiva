# IRS expected outputs: Optima regression baseline

`TC1.json` … `TC10.json` hold the expected outputs for the internal expected-output suite
(`scripts/irs_expected_output_suite.py`, `tests/unit/test_irs/test_irs_expected_outputs.py`).

## Provenance

- **Source:** Optima's own production pricing, the same implementation the suite tests:
  `price_irs_engine` → `FreshOISInstrument` → `PricingService` → `ql.DiscountingSwapEngine`
  → production cashflow extraction.
- **When:** captured at the `validation_phase1` checkpoint on 15-Oct-2026, on Linux with
  Python 3.11.17 and QuantLib 1.43. Each file records the exact capture time, environment,
  input files and their SHA-256 under `provenance`.
- **Independent?** No (`"independent": false`). These values are **not** independent
  expected results and **not** Bloomberg values. A PASS means the implementation still
  reproduces its validation_phase1 outputs; it says nothing about whether those outputs
  are correct.
- **Bloomberg:** comparison with Bloomberg stays in `scripts/irs_reconciliation_report.py`
  and `tests/fixtures/bloomberg_irs/`, both unchanged. The suite does not read the Bloomberg fixtures.
- **TC2:** priced with the provisional default Method A (SARON over the contractual
  accrual dates, no shift; OI-17, R9). If the SME confirms Method B, the TC2 baseline must
  be re-captured with a stated reason.

## Changing a baseline

Never edit these files by hand to make a test pass. A deliberate pricing change is recorded
by re-capturing, with the reason stored in the file:

    python -m scripts.irs_expected_output_suite capture --case TC2 --overwrite --reason "SME confirmed Method B"

## Fields

- Expected: `npv`, `fixed_leg_npv`, `floating_leg_npv`.
- Each cashflow: `leg`, `side`, `period`, accrual dates, `payment_date`, `notional`,
  `day_count_fraction`, `rate`, `amount`, `discount_factor`, `present_value`.
- `settled` coupons.
- Not included, because production doesn't compute them: par rate, PV01/DV01, accrued.
