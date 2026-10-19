# Fresh QuantLib-Native IRS Implementation Design

## Scope

This design uses `docs/IRS_REQUIREMENTS.md` as the requirement baseline. It treats the existing IRS implementation as legacy and does not use its implementation choices as a design template. Open economic conventions remain open; this document proposes software boundaries, not market assumptions.

## 1. Current Optima Architecture Relevant to a New IRS

The current generic path is:

```text
PricingRequest
  → build_instrument_from_request
  → build_market_env_from_request
  → PricingService.price
  → registered model and engine
  → QuantLib instrument with QuantLib pricing engine
  → PricingResult
```

- `api/v1/schemas.py` defines `InstrumentRequest` as a type string plus a parameter dictionary. `PricingRequest` carries the instrument, market data, model key, engine key, and engine parameters.
- `api/v1/helpers.py` resolves instrument classes through `instrument_registry`, calls `from_dict()` when available, and constructs the market environment.
- `core/interfaces/base.py` defines `BaseInstrument`, `BaseModel`, `BaseEngine`, and `MarketEnvironment`.
- `registry/` contains separate registries for instruments, models, engines, pricer defaults, and curves. `registry/bootstrap.py` imports modules so their registration decorators run.
- `services/pricers/pricing_service.py` resolves a model and engine, attaches a QuantLib pricing engine to the built QuantLib instrument, calls `NPV()`, and returns `PricingResult`.
- `MarketEnvironment` holds discount and forecast curve handles keyed by currency, fixings keyed by name/date, and other market objects.

The current request market-data builder requires an underlying and constructs flat test curves for standard requests. `MarketDataRequest.extra_data` is an untyped extension point, but the helper does not turn it into dated IRS curve inputs.

## 2. Clean Integration Points

1. **Instrument request and factory:** retain the instrument type/params dispatch and add a validated IRS request-to-domain conversion. Do not place schedule or valuation calculations in the API endpoint.
2. **Market-data request and environment:** use a typed IRS market-data payload or a typed builder extension to construct the market objects required by the model. Preserve `MarketEnvironment` as the runtime container or introduce a typed pricing context alongside it.
3. **Instrument registry:** `InstrumentType.IRS` already exists. The active registry entry is loaded by `registry/bootstrap.py`; a fresh implementation must become the registered implementation for that key without registering a competing duplicate.
4. **Model registry:** use a dedicated model/context builder for IRS market objects rather than relying on the API's default Black-Scholes model.
5. **Engine registry:** register the IRS engine under the `(instrument_type, engine_type)` key pattern used by `BaseEngine` implementations.
6. **Pricing service:** preserve central orchestration and result construction. Add the smallest typed context/build hook needed for the IRS model's market objects to reach both instrument construction and engine construction.

`PricingRequest` currently defaults to `black_scholes` / `analytic`, and `PricingService` has no default `PricerConfig` for IRS. IRS requests therefore need an explicit approved model/engine selection or a deliberate IRS default registration; they must not inherit an equity model accidentally.

## 3. Existing QuantLib Infrastructure We Can Reuse

- **Base contracts and result types:** `BaseInstrument`, `BaseModel`, `BaseEngine`, `MarketEnvironment`, `PricingDate`, `PricingResult`, and registry abstractions.
- **Instrument pattern:** `instruments/equity/vanilla_option.py` constructs a QuantLib instrument and leaves engine attachment to the pricing flow. `instruments/rates/fixed_rate_bond.py` illustrates a rates instrument returning a QuantLib instrument and a QuantLib `Schedule`.
- **Model pattern:** `models/equity/black_scholes.py` builds QuantLib process inputs from market-environment objects. It is an architectural example only; its equity model is not an IRS model.
- **Engine pattern:** registered `BaseEngine.build(...)` implementations return QuantLib pricing engines. The repository already wraps QuantLib's native discounting and option engines.
- **Curve machinery:** `market/curves/yield_curve.py` can build a `YieldTermStructureHandle` from supplied dated discount-factor pillars, including the reference-date anchor. The existing builder also has other curve paths, but their inputs and interpretations must be used only when confirmed for the new IRS market-data contract.
- **Registration and integration tests:** `tests/unit/test_engines/test_fx_forward_ql_pattern.py` shows factory-built instruments and service-level architecture tests; `tests/unit/test_services/test_fx_forward_service.py` exercises request helpers through `PricingService`.
- **Canonical domain evidence:** `tests/fixtures/bloomberg_irs_case.json` and `docs/IRS_REQUIREMENTS.md` provide confirmed trade and schedule inputs. They do not settle the open conventions listed in the requirements baseline.

## 4. Infrastructure That Is Missing or Needs an IRS-Specific Extension

1. `MarketDataRequest` has generic underlyings, flat rates, a simple rate-curve list, foreign rate, and arbitrary `extra_data`; it has no typed representation for the IRS market curves, benchmark/index inputs, or fixing data needed by the confirmed trade requirements.
2. `build_market_env_from_request` currently requires an underlying and routes ordinary requests to flat test curves. It does not construct the canonical dated curve inputs as a typed IRS market environment.
3. `MarketEnvironment` stores curves by currency, not by leg or benchmark, and has no typed IRS market context. Whether a selected trade requires multiple forecast curves or another mapping is governed by the still-open market-data requirements.
4. `BaseModel.build_process()` expresses a QuantLib process but does not define a typed contract for model-built indexes, curve roles, and other deterministic IRS market objects.
5. `PricingService` builds the engine before it builds the QuantLib instrument. `BaseInstrument.build()` receives only `MarketEnvironment`. An IRS model context therefore needs an explicit route to both instrument and engine construction; implicit mutation or hidden fallback selection would obscure curve/index ownership.
6. The model registry has general equity and rates/credit model keys but no dedicated IRS market-context builder. The existing `HullWhiteModel` is a stochastic model entry, not a substitute for an IRS market-data builder.
7. The pricer default registry has no IRS configuration. A deliberate model/engine selection must be added when those choices are settled.
8. There is no shared IRS schedule/domain package that represents independent fixed, floating, reset, repayment, exchange, and observation schedules.
9. The current API factory catches exceptions from `from_dict()` and can fall back to constructor filtering. The new IRS request conversion should preserve validation errors so malformed leg or schedule data is not silently accepted.

## 5. Proposed New IRS Module Boundaries

The repository already separates instruments, models, engines, market data, and pricers at the top level. Follow those boundaries rather than placing all IRS behavior under `services/irs/`:

```text
instruments/rates/irs/
    __init__.py
    domain.py          # immutable trade, leg, repayment, and convention inputs
    schedule.py        # contractual leg schedules and period mapping
    instrument.py      # BaseInstrument wrapper; builds QuantLib instrument(s)

models/rates/
    irs_market_model.py  # builds typed IRS QuantLib market context

engines/analytic/
    irs_engine.py      # BaseEngine wrapper; builds QuantLib pricing engine

market/curves/
    ...                # existing curve package; extend only for confirmed inputs

api/v1/
    schemas.py         # typed IRS request/market-data schema as needed
    helpers.py         # parse domain request and build market context

tests/unit/irs/
tests/integration/irs/
```

The module names are proposed boundaries, not a commitment to a specific market convention. Keep cross-product orchestration in `PricingService`; an IRS-specific service may provide request/domain assembly, but must not replace the standard pricing orchestration.

The external instrument key can remain `irs`. During implementation, bootstrap should load the fresh instrument module as the active registration for that key. The legacy module must not remain a competing registration or be used as a fallback.

## 6. Proposed Request and Domain Objects

Use typed domain objects after request parsing:

- `IRSTrade`: trade id, currency, effective date, maturity date, principal-exchange terms, fixed-leg terms, floating-leg terms, and required schedule/convention inputs.
- `FixedLegTerms`: direction, fixed coupon in normalized core form, payment frequency, day-count label/variant, and that leg's repayment schedule.
- `FloatingLegTerms`: direction, benchmark identifier and tenor, independent reset and payment frequencies, spread in normalized core form, day-count label, observation conventions, and that leg's repayment schedule.
- `PrincipalRepayment`: payment date and repayment amount. Pay-side and Receive-side events are stored as separate sequences.
- `ScheduleTerms`: only confirmed or explicitly supplied generation inputs. Any fields needed to resolve an open convention must be required or explicitly configured rather than silently defaulted.
- `IRSPricingContext`: typed QuantLib market objects produced for one pricing operation, such as resolved curve handles, index objects, and fixing access required by the selected trade. Its contents must follow explicit market-data/curve mapping rules once those are confirmed.

Keep the wire schema separate from QuantLib objects. Parse and validate external names/units at the boundary; the domain layer stores normalized rates and explicit conventions; QuantLib objects are created only in model, schedule, instrument, or engine builders with clear ownership.

## 7. Instrument, Model, and Engine Responsibilities

### Instrument

- Validate and retain contractual trade terms; expose trade id, currency, type, and maturity through `BaseInstrument`.
- Request fixed and floating schedules from the schedule component.
- Build the appropriate QuantLib-native swap instrument from the resolved schedules, leg terms, and model-provided market context.
- Never compute a manual PV or synthesize an `NPV()` result.
- Keep the QuantLib instrument unpriced until the registered engine supplies a QuantLib pricing engine.

For a confirmed overnight-indexed case such as the canonical SOFR daily-reset trade, the QuantLib instrument should be an overnight-indexed swap using a QuantLib overnight index. Other benchmark families must use the QuantLib instrument/index combination selected by their confirmed conventions; do not force every floating leg into one instrument type.

### Model

- Own the construction/resolution of QuantLib market objects required by the selected IRS inputs.
- Consume the typed market environment, construct the case-appropriate curve/index/fixing objects, and return an explicit `IRSPricingContext`.
- Keep discounting and forecasting roles explicit where the market-data contract specifies them.
- Do not create trade schedules, infer contractual terms, or calculate swap NPV.
- Do not bootstrap, interpolate, or transform market observations except under an explicitly confirmed curve definition.

The current `BaseModel` API does not expose this typed context contract. Add a narrow context-building hook or a dedicated protocol rather than placing model-built state in module globals.

### Engine

- Implement `BaseEngine`, declare compatible IRS instrument/model keys, and build the appropriate QuantLib `PricingEngine` from the model context and market environment.
- For a supported deterministic swap/OIS, use the appropriate QuantLib discounting engine, such as `ql.DiscountingSwapEngine` where applicable.
- Attach no formula-based valuation logic to the engine wrapper; QuantLib's instrument and engine compute NPV and leg results.
- Reject missing or incompatible required market objects instead of silently choosing another currency's first curve.

### Pricing service and model-context handoff

The current service builds an engine before building the QuantLib instrument. The new flow should construct one per-pricing-call context before either consumer needs it:

```text
request → typed trade + market environment
        → IRS model builds IRSPricingContext
        → instrument builds QuantLib swap from trade + context
        → engine builds QuantLib PricingEngine from context
        → service attaches engine and calls QuantLib NPV()
```

Implement this with an explicit typed context/build hook shared by the IRS instrument and engine. Preserve the existing flow for instruments that do not use the new hook.

## 8. Independent Pay and Receive Leg Parameters

- Store fixed-leg and floating-leg terms separately; do not use one shared frequency, day count, direction, reset, or repayment object where the requirements make the inputs independent.
- Store Pay and Receive repayment events as separate sequences. Different dates and row counts are valid.
- Keep payment frequency, floating reset frequency, and observation conventions as separate fields and schedules.
- Generate cashflows from the corresponding leg's terms and outstanding notional.
- Do not create a shared schedule merely to align table rows. Any schedule alignment needed internally must preserve the original independent event data and must not invent dates or amounts.

## 9. Principal Repayment Schedule

The domain schedule should represent dated principal-repayment **amounts** for each side. Apply each repayment to the outstanding notional for subsequent coupon periods according to its contractual effective date. Keep this notional roll-forward separate from QuantLib principal-exchange cashflows.

The `Principal Exchange` term remains a distinct instrument input. Only that explicit term may request a separate principal exchange. A repayment amount alone does not request one. The supported repayment signs, date application, and exchange choices remain open in `docs/IRS_REQUIREMENTS.md` and must not be chosen here.

## 10. Schedule Generation Isolated from Pricing

The schedule component receives contractual effective/maturity dates, leg-specific payment frequencies, explicit generation/stub terms, relevant business-day/calendar terms once confirmed, and repayment events. It returns typed period data including accrual start, accrual end, payment date, and period notional. Floating reset/observation dates are represented separately from payment dates.

The schedule API must not receive valuation date as a schedule-generation input. The pricing context may set QuantLib's evaluation date, but changing valuation date must not silently change contractual dates. Tests should cover the canonical short final stub and other explicitly specified stub conventions without inventing defaults for open cases.

## 11. TDD Implementation Sequence

Write the tests before production work, in this order:

1. **Domain/request parsing:** typed per-leg fields, normalized fixed coupon/spread units, index identifier retention, principal repayment amounts, independent Pay/Receive row counts, and validation of missing required terms. Include no pricing assertions.
2. **Schedule builder:** frequency independence, valuation-date independence, accrual/payment-date separation, explicit stub behavior, and per-period notional after dated amount repayments. Assert that repayment does not create principal-exchange cashflows.
3. **QuantLib instrument construction:** correct QuantLib class for each confirmed benchmark family; direction, leg schedules, coupon conventions, notionals, and cashflow types. Do not require market pricing to validate construction.
4. **Market/model context:** confirmed curve inputs and reference dates, explicit index/curve handles, and fixing access. Test inputs independently; keep unresolved curve conventions out of production assumptions.
5. **Engine wiring:** registered engine returns the expected QuantLib engine, receives the intended market context, attaches to the constructed QuantLib instrument, and delegates valuation to QuantLib.
6. **PricingService integration:** request factory → market-environment builder → model context → instrument → engine → finite typed `PricingResult` through the public path.
7. **External validation:** only after trade, curve, fixing, and convention inputs are confirmed, compare against an approved external oracle in a separate validation test. Keep reference outputs out of construction and market-curve tests.

Each stage should have a focused failing test at its public boundary before its implementation. Do not weaken tests to accommodate unsupported fallback behavior.

## 12. Explicitly Rejected Legacy IRS Design Patterns

- Reusing, repairing, refactoring, or extending the legacy IRS class as the foundation of the new implementation.
- Carrying forward legacy field defaults, silent fallbacks, date mappings, curve selection rules, or model/engine coupling without independent confirmation.
- Formula-based fixed or floating leg PV calculations in an instrument, service, or model when QuantLib has the instrument/cashflow and pricing-engine functionality.
- Returning an analytical wrapper that pretends to be a QuantLib instrument instead of building the QuantLib swap.
- Making the instrument construct market curves or the engine construct contractual schedules.
- Coupling reset frequency to payment frequency, forcing Pay and Receive repayment schedules to equal lengths, or treating repayment as principal exchange.
- Selecting an unspecified stub, business-day, day-count, index, observation, curve, or Bloomberg convention through an implicit default.
- Fitting implementation choices to Bloomberg output values.
