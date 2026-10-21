# IRS input adapter: Excel (today), UI (later), one pricing path

```
Excel worksheet ──► excel_reader ──► TradeInputs ──► normalizer ──► NormalizedIRSTrade ──► pricing ──► price_irs_engine
(UI form, later) ─────────────────► TradeInputs ┘                     (engine trade doc     (resolve, check     (merge_market,
                                    (dict, analyst                     + market request)     reference)          price: PricingService,
                                     units/labels)                                                               DiscountingSwapEngine)
```

| Module | Responsibility | Knows Excel? |
|---|---|---|
| `services/irs_inputs/excel_reader.py` | Find fields by section and label; Excel dates to `date`; %-formatted cells to percent numbers; the amortisation table | Yes (only module) |
| `services/irs_inputs/contract.py` | Field names of `TradeInputs`; `NormalizedIRSTrade`, `MarketDataRequest`, `InputValidationError` | No |
| `services/irs_inputs/normalizer.py` | Required fields, types, units, enumerations, schedule, market reference; builds the engine trade document and has the engine parse it | No |
| `services/irs_inputs/pricing.py` | Resolve market data with the existing resolver, check the reference against it, call the existing engine | No |
| `scripts/price_irs_workbook.py` | Command line: workbook → cashflow statement | (uses the reader) |

No module here prices, builds a curve, or chooses a default.

## Running it

```
python -m scripts.price_irs_workbook --workbook examples/irs/Optima_IRS_Test_Case_Inputs_v4.xlsx --sheet TC001 [--show-trade]
```

Exit code 0 priced; 2 input or market-data problem (every problem is listed); 1 pricing error.

## The interface a UI adapter implements

A UI adapter builds a `TradeInputs` dictionary and calls the same two functions:

```python
from services.irs_inputs.normalizer import normalize
from services.irs_inputs.pricing import price_normalized

normalized = normalize(trade_inputs, source="UI")   # InputValidationError lists all problems
priced = price_normalized(normalized)               # PricedTrade: npv, legs, cashflows, settled
```

`TradeInputs` (all keys required; an empty field is `None`):

| Section | Field | Unit / values |
|---|---|---|
| `trade` | `trade_id` | text |
| | `currency` | USD, CHF, JPY, INR |
| | `notional` | initial notional, currency units; equals period 1 notional |
| | `effective_date`, `maturity_date`, `valuation_date` | date or `YYYY-MM-DD` (effective date unadjusted) |
| `fixed_leg` | `direction` | Pay, Receive |
| | `rate_percent` | **percent** (5 means 5% = 0.05) |
| | `payment_frequency` | Annual, Semiannual, Quarterly, Monthly |
| | `day_count` | ACT/360, ACT/365, 30/360 |
| | `business_day_convention` | Modified Following, Following, Preceding, Unadjusted |
| | `calendar` | FD, SZ, JN, RB |
| `floating_leg` | `direction` | opposite of the fixed leg |
| | `benchmark`, `index_tenor` | overnight: SOFR 1D (USD) → SOFRRATE, TONAR 1D (JPY) → MUTKCALM; term rate: SF0006M (SARON fallback) 6M (CHF) → SF0006M, INR OIS 6M (INR) → IRSWOF |
| | `spread_bp` | **basis points** (10 means 0.001) |
| | `leverage` | multiplier (term-rate legs: 1 only, engine rule) |
| | `reset_frequency` | Daily for 1D indices; Semiannual for 6M indices only |
| | `payment_frequency`, `day_count`, `business_day_convention`, `calendar` | as the fixed leg |
| | `rate_timing` | *1D only:* In Arrears, In Advance |
| | `lookback_days`, `rate_cutoff_days` | *1D only:* whole days |
| | `lookback_type` | *1D only:* Lookback |
| | `compounding` | *1D only:* Daily Compounded |
| | `spread_treatment` | *1D only:* Exclude Spread |
| | `fixing_calendar` | *6M only:* EN, SZ, RB |
| | `fixing_lag_days` | *6M only:* business days from reset to rate start |
| | `term_compounding` | *6M only:* None (exactly one reset per payment period), Flat |
| | `observation_method` | *SF0006M only, required:* "Method A: contractual accrual (PROVISIONAL R9)", "Method B: reset-date fallback" |
| `notional` | `principal_exchange` | Never |
| | `amortisation_type` | Custom Schedule, Bullet / No Amortisation |
| | `schedule` | list of {`period`, `accrual_start`, `accrual_end`, `payment_date`, `notional`, `amortisation_percent`, `amortisation_amount`, `action`} |
| `resets` | `schedule` | *6M only* (empty list for 1D legs): list of {`payment_period`, `reset_date`, `rate_start`, `rate_end`} |
| `market_data` | `curve` | USD SOFR, CHF SARON, JPY TONAR, INR OIS |
| | `snapshot_folder` | optional; must be `market_data/<valuation date>/<CCY>/` |
| | `curve_source_file` | prepared snapshot file name |
| | `fixings_source_file` | file name in `market_data/<valuation date>/`; required when, and only when, the trade needs a fixing |
| | `reference_date` | optional; must equal the snapshot's |
| | `interpolation` | optional; must equal the snapshot's |

Fields marked *1D only* must be empty for a 6M leg, and *6M only* fields must be empty for
a 1D leg. Leaving a field empty never means a default.

**Reset schedule (6M legs).** Each payment period needs at least one reset. Its resets must
run contiguously from the period's accrual start to its accrual end: several resets in one
period are sub-periods, e.g. TC5 and TC7 have annual payments with semiannual resets. Term
Compounding "None" allows exactly one reset per period. A reset fixes on or before its rate
start, and the engine checks that the reset date is a fixing-calendar business day. Reset
dates are inputs, never derived. TC2 and TC9 use source reset dates that no simple rule
produces: in TC9, quarterly periods share semiannual resets.

**SF0006M observation method (OI-17, R9).** It must be selected explicitly; an empty value
is an error and is never defaulted.
- Method A is written to the trade as `observation_dates: contractual_accrual`. It is
  **provisional pending SME decision R9**: every pricing that uses it returns a note saying
  so, and the price script prints that note.
- Method B is written in the engine's documented form, with no `observation_dates` key,
  which is how the existing trade files hold it (TC7). A test checks that the engine's
  default is still Method B, so this form cannot silently change meaning.

`NormalizedIRSTrade.trade_document` is the existing engine trade document (schema of
`instruments/rates/irs/pricing_instrument.py`; the same format as `examples/irs/*_trade.json`),
so anything that already prices a trade file can price it.

## Options: supported, rejected, or semantics pending

Every option in the workbook's drop-down lists falls in exactly one group (a test enforces
this):

- **Supported**: listed in the table above.
- **Rejected, not supported by the engine** (error with the reason):
  - plain SARON (there is no overnight SARON leg; the CHF 6M fallback is "SF0006M (SARON
    fallback)");
  - index tenors 3M and 1Y;
  - Monthly, Quarterly and Annual reset;
  - Simple compounding and Compound Spread;
  - principal exchange other than Never;
  - any benchmark, tenor and currency combination not listed above.
- **Rejected, semantics not yet defined** (error until agreed and implemented):
  - *Amortisation Type: Percentage per Period.* Whether the percentage is of the original
    or of the outstanding notional is not defined. It is not mapped to Custom Schedule.
    For the same reason a non-zero `amortisation_percent` is rejected in any schedule;
    the notional and amortisation amount are used. `action` has no defined meaning and
    must be empty.
  - *Interpolation: Linear, Log Linear.* Not defined against the snapshot conventions.

### Interpolation is metadata, never an instruction

The prepared snapshot fixes its curve's conventions (for USD: linear in continuously
compounded zero rate, `linear_zero`). The workbook field only describes that snapshot and is
checked against it: a mismatch is an error, and the curve is never rebuilt or changed to
match the input. "Piecewise Linear (Cont)" maps to `linear_zero`. This is Bloomberg's label
for curve 234, which the CHF snapshot implements as linear zero (continuous, ACT/365F). For
USD it describes Optima's snapshot; Bloomberg's own interpolation for curve 490 is not known
(OI-1). Left empty, nothing is checked and the snapshot's convention applies (reported as a
note).

## Market data

`pricing.price_normalized` uses `price_irs_engine.resolve_market_files` with the canonical
layout (`market/market_data_layout.py`, `market_data/README.md`):

- the prepared snapshot `market_data/<date>/<CCY>/<ccy>_<curve>_<date>.json`;
- the shared fixings file `market_data/<date>/fixings_<date>.json` only if the trade needs it.

The stated curve file, fixings file, reference date and interpolation must agree with that
selection.

## Workbook v4 (`examples/irs/Optima_IRS_Test_Case_Inputs_v4.xlsx`)

- v3 plus eight floating-leg rows:
  - Leverage, Business Day Convention, Calendar, Lookback Type;
  - for 6M legs: Fixing Calendar, Fixing Lag, Term Compounding, SARON Observation Method.
- A **RESET SCHEDULE** section: Payment Period, Reset Date, Rate Start, Rate End, 30 rows.
- Benchmark list: "SARON" became "SF0006M (SARON fallback)", the CHF LIBOR 6M fallback
  (compounded SARON + 0.0741%, OI-12).
- Guidance text marks the 1D-only and 6M-only rows and explains the benchmark labels,
  Amortisation Type, Fixings Source File and Interpolation.
- One worksheet per test case: `TC001` to `TC010`.
  - Each is filled from `examples/irs/tc<N>_trade.json`, and its normalized trade equals that
    file exactly.
  - `--sheet` is required, because the workbook has several worksheets.
- Expected results are not in the workbook. They are the approved baselines
  `tests/fixtures/irs_expected_outputs/TC<N>.json`.
- The reader rejects earlier layouts, which lack these rows and the reset section.
- "Fixed Rate" must be a percentage-formatted cell, and "Amortisation (%)" is read as a
  percentage.
- "Snapshot Folder" is a formula. It is read as last calculated by Excel; if it holds no
  calculated value, it is treated as not stated.

Tests: `tests/unit/test_irs/test_irs_excel_input_adapter.py`.
