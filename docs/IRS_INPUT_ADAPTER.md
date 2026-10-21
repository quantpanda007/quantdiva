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
| | `benchmark`, `index_tenor` | SOFR 1D (USD), TONAR 1D (JPY) |
| | `spread_bp` | **basis points** (10 means 0.001) |
| | `leverage` | multiplier |
| | `reset_frequency` | Daily |
| | `payment_frequency`, `day_count`, `business_day_convention`, `calendar` | as the fixed leg |
| | `rate_timing` | In Arrears, In Advance |
| | `lookback_days`, `rate_cutoff_days` | whole days |
| | `lookback_type` | Lookback |
| | `compounding` | Daily Compounded |
| | `spread_treatment` | Exclude Spread |
| `notional` | `principal_exchange` | Never |
| | `amortisation_type` | Custom Schedule, Bullet / No Amortisation |
| | `schedule` | list of {`period`, `accrual_start`, `accrual_end`, `payment_date`, `notional`, `amortisation_percent`, `amortisation_amount`, `action`} |
| `market_data` | `curve` | USD SOFR, CHF SARON, JPY TONAR, INR OIS |
| | `snapshot_folder` | optional; must be `market_data/<valuation date>/<CCY>/` |
| | `curve_source_file` | prepared snapshot file name |
| | `fixings_source_file` | file name in `market_data/<valuation date>/`; required when, and only when, the trade needs a fixing |
| | `reference_date` | optional; must equal the snapshot's |
| | `interpolation` | optional; must equal the snapshot's |

`NormalizedIRSTrade.trade_document` is the existing engine trade document (schema of
`instruments/rates/irs/pricing_instrument.py`; the same format as `examples/irs/*_trade.json`),
so anything that already prices a trade file can price it.

## Options: supported, rejected, or semantics pending

Every option in the workbook's drop-down lists falls in exactly one group (a test enforces
this):

- **Supported**: listed in the table above.
- **Rejected, not supported by the engine** (error with the reason): SARON / INR OIS and
  index tenors 3M/6M/1Y (term-rate legs need explicit resets this contract does not carry);
  non-daily reset; Simple compounding; Compound Spread; principal exchange other than Never.
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

- v3 plus four floating-leg rows: Leverage, Business Day Convention, Calendar, Lookback Type.
- Guidance text clarifies three existing fields: Amortisation Type, Fixings Source File and
  Interpolation. No other field was added, and no drop-down option was removed.
- One worksheet per test case: `TC001`, `TC003`, `TC004`, `TC006`, `TC010` (the overnight-leg
  cases). Each is filled from `examples/irs/tc<N>_trade.json`, and its normalized trade equals
  that file exactly. `--sheet` is required, because the workbook has several worksheets.
- The term-rate cases (TC2, TC5, TC7, TC8, TC9) are not in the workbook yet: they need
  reset-schedule inputs that this contract does not have.
- Expected results are not in the workbook. They are the approved baselines
  `tests/fixtures/irs_expected_outputs/TC<N>.json`.
- The reader rejects the v3 layout, because it lacks the four rows.
- "Fixed Rate" must be a percentage-formatted cell, and "Amortisation (%)" is read as a
  percentage.
- "Snapshot Folder" is a formula. It is read as last calculated by Excel; if it holds no
  calculated value, it is treated as not stated.

Tests: `tests/unit/test_irs/test_irs_excel_input_adapter.py`.
