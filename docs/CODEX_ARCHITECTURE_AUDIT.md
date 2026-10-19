# Optima Architecture and IRS Audit

**Audit date:** 2026-10-05  
**Scope:** Repository inspection only. No source code, tests, packaging, or dependencies were changed. This document is the sole created artifact.

## 1. Executive summary

Optima has a recognizable domain layout (`instruments`, `models`, `engines`, `market`, `services`, `api`) and a registry-driven pricing service, but the layout does not describe one uniformly enforced runtime architecture. The mounted application is `api.app:app`; its `/api/v1` router builds an instrument and a market environment and calls `PricingService`. A separate `api.fastapi.app` exists, and a substantial copied tree under `session_zip/` is not mounted by the main app.

IRS is registered and constructed as a QuantLib `VanillaSwap`; the pricing engine is QuantLib `DiscountingSwapEngine`. The route can dispatch it through `PricingService`, but the IRS model is a compatibility stub, the engine does not receive the trade currency, the request market builder supplies flat rather than bootstrapped curves, and the swap wrapper hardcodes zero spread and fabricates past fixings from a discount-curve rate. The `MarketEnvironment.fixings` input is not used by the IRS builder. No IRS-specific test exists in the active test tree.

**Assessment:** NO-GO for starting a clean IRS implementation against the current code as if its conventions or behavior were authoritative. The code paths can be described, but business conventions and intended requirements are not established. Resolve the missing IRS product and market-data semantics first; then pin them in tests before replacing the existing implementation.

## 2. Repository structure

Top-level areas and relevance:

| Area | Observed contents / role |
|---|---|
| `api/` | Main FastAPI app, `api/v1` schemas, helpers, endpoints; also a separate `api/fastapi` app and an unused-looking `api/backup`. |
| `core/` | Base interfaces, enums, value objects, exceptions, portfolio. |
| `instruments/` | Domain wrappers for equity, rates, FX, credit, commodity, inflation, plus common payoff/exercise helpers. |
| `models/` | Equity BSM and lightweight rates/credit model registrations; rates/FX directories largely placeholders. |
| `engines/` | Analytic, finite-difference, lattice, integral and Monte Carlo engine modules. |
| `market/` | Curves, conventions, fixings, volatility, snapshots, historical data, providers, bootstrapping and scenarios. |
| `services/` | Pricing, risk, Greeks, calibration, jobs, reporting, export, comparison, dispatch, portfolio and XVA. |
| `registry/` | Global registration and bootstrap imports. |
| `configs/`, `definitions/`, `numerics/`, `data/`, `workflows/`, `infra/`, `reporting/` | Configuration, static definitions, numerical helpers, persistence/data, workflows and supporting infrastructure. |
| `frontend/` | Vite React shell, Streamlit shell, and main static UI with instrument modules and schema. IRS module itself is a placeholder that uses schema fallback. |
| `tests/` | Unit, regression and integration directories, but integration is empty and unit instrument/market/model folders contain no substantive tests. |
| `docs/` | Only package initializer placeholders under API, architecture and user guides at audit time. |
| `scripts/`, `examples/`, `notebooks/`, `docker/`, `deployment/`, `infra/` | Operational helpers, demonstrations, container and deployment scaffolding. |
| `session_zip/` | A duplicate snapshot of APIs, services, instruments and registry. It is not imported by `api.app` and creates ambiguity about which copy is current. |
| Root files | `main.py`, `run.py`, `run2.py`, `pyproject.toml`, `environment.yml`, `Optima.spec`, `build.bat`, Docker files and assorted notes/hand-off files. `.gitingore` is misspelled, so it is not Git's standard ignore filename. |

Generated/local material observed includes `build/`, `dist/`, `.pytest_cache/`, `.ruff_cache/`, `quantlib_pricing.egg-info/`, `data/market_data.db`, `temp/`, and `session_zip.zip`. These were not inspected as source, except where packaging configuration references build output.

## 3. Actual pricing architecture

### Main mounted single-pricing route

The path for `POST /api/v1/pricing/single` is:

```text
JSON PricingRequest
  -> api/v1/endpoints/pricing.py::price_single
  -> api/v1/helpers.py::build_instrument_from_request
       -> instrument_registry lookup
       -> instrument class from_dict(params), with a permissive direct-constructor fallback
  -> build_market_env_from_request
       -> PricingDate + build_test_market_env (flat curves) for non-FX
  -> PricingService.price
       -> choose model/engine from explicit request or pricer config registry
       -> instantiate model and engine from registries
       -> engine.build(model, market_env, instrument=instrument)
       -> instrument.build(market_env)
       -> setPricingEngine(engine) where available
       -> QuantLib Instrument.NPV()
  -> PricingResult -> response model -> JSON
```

`api/app.py` imports `registry.bootstrap`, mounts `api.v1.router.api_v1_router` under `/api/v1`, and serves `frontend/static/optima.html` at `/`. `api/v1/router.py` mounts `api.v1.endpoints.pricing` under `/pricing` and also mounts risk, sensitivities, market, portfolio, jobs, snapshots, exports, bulk upload and other routers.

`PricingService` does not always use the documented legacy sequence: it has a special FX forward engine `price()` path that can return a typed result before instrument construction. Most other instruments follow the build/set-engine/NPV sequence. `PricingService` builds a model instance but does not validate model-engine compatibility globally; compatibility is usually engine-local. `_build_model` only copies `instrument.underlying` where present.

### Alternate entry points

- `api/fastapi/app.py` is a distinct app that includes `api.fastapi.routes.pricing`; it is not the app mounted by `api.app` or `main.py` as currently wired. Its request schema/factory imports `_factory`, which is not in the repository inventory, so that path is not established as executable from this checkout.
- `main.py` launches `api.app:app` with Uvicorn on `127.0.0.1:8001`, starts Ollama opportunistically, and opens a browser. `run.py` and `run2.py` also exist; their runtime roles are not consolidated in docs.
- `services/pricers/pricing_service.py` has additional callers in risk, portfolio, jobs, exports and bulk upload. Many bulk-upload variants are duplicated (`bulk_upload.py`, `bulk_upload_w2.py`, `bulk_upload_working.py`, `bulk_upload_ww.py`).

## 4. Golden-path instrument

The closest existing architectural reference is the European `VanillaOption` through the main service path. It represents a trade in a `BaseInstrument`, constructs a QuantLib instrument without setting its engine, uses an environment-backed BSM model and a separately registered engine, and is exercised through `PricingService` and the active `/api/v1/pricing` endpoint.

| Layer | Vanilla option path |
|---|---|
| Request/trade | `InstrumentRequest(type, params)` in `api/v1/schemas.py`; helper resolves class via registry and passes normalized params into `VanillaOption.from_dict`. Fields include trade id, underlying, strike, expiry, option type, exercise and currency. |
| Instrument | `instruments/equity/vanilla_option.py::VanillaOption` implements `BaseInstrument`; `build()` produces `ql.VanillaOption` using shared payoff/exercise builders. It does not set the pricing engine. |
| Market environment | `api/v1/helpers.py` maps market request to `build_test_market_env`; market object contains pricing date, spot, discount curve, dividend curve and vol surface. |
| Model | `models/equity/black_scholes.py::BlackScholesModel` creates a `ql.GeneralizedBlackScholesProcess` from `MarketEnvironment`. |
| Engine | `engines/analytic/bsm_engine.py::AnalyticEuropeanEngine` checks BSM model type and returns `ql.AnalyticEuropeanEngine(process)`. |
| QuantLib | `ql.VanillaOption` (or instrument-specific variant), process and `ql.AnalyticEuropeanEngine`; service sets engine and reads NPV. |
| Service/API | `PricingService.price()`; `api/v1/endpoints/pricing.py` single/batch/compare routes call the common helper and service. |
| Tests | `tests/unit/test_services/test_vanilla_pricing_smoke.py` tests European, American and Bermudan smoke paths through PricingService; `tests/regression/test_equity_pricing.py` checks equity numerical properties and approximate values. |

Caveats: this is a *reference for wiring*, not a claim that the whole platform or all exercise types are canonical. The smoke tests only require positive values. The regression test's fixture imports `engines.analytic.equity_engines`; its fixture may be inconsistent with the currently bootstrapped `bsm_engine` module. Also, it describes the ATM call as approximately 10.06 but asserts a target near 9.227. No test execution was performed for this audit.

## 5. IRS forensic audit

### Trade representation and request path

`InterestRateSwap` in `instruments/rates/interest_rate_swap.py` is a dataclass registered under `InstrumentType.IRS` (registry key `irs`). `from_dict` parses dates and defaults missing values. The API helper filters/falls back to constructor fields and the static frontend `frontend/static/instruments/rates/irs.js` has no bespoke field or payload mapping; it delegates to `schema_master.js` and generic collection. The IRS schema identifies a rate curve and displays “Discounting” model / “Analytic” engine, but those labels do not define a product convention.

Current trade fields:

| Requested term | Current code behavior |
|---|---|
| Notional | Present; defaults to 1,000,000. One notional for both legs. |
| Effective date | `start_date`; nullable in declaration and defaults to absent via `from_dict`, with no visible business validation in the dataclass. |
| Maturity | `end_date`; returned by `maturity()`. |
| Fixed rate | Present; defaults to zero. |
| Floating benchmark | Derived from currency (`USDLibor`, `Euribor`, `GBPLibor`; otherwise falls back to `USDLibor`); no benchmark name field. |
| Spread | Not represented as a trade field. `VanillaSwap` spread argument is hardcoded to 0.0. |
| Payment frequency | Separate fixed and floating frequencies; defaults semiannual / quarterly; allowed-map fallback silently selects those defaults for unknown strings. |
| Reset frequency | Implied by floating schedule and selected index tenor, not an independent reset convention. |
| Currency | `_currency`; defaults USD. |
| Pay/receive | `direction == "pay"` selects payer (pay fixed); every other value selects receiver. No strict enum/validation. |
| Amortization | No amortization schedule or notionals; the QL swap receives a scalar notional. |

### Schedule and dates

`InterestRateSwap.build()` converts start/end Python dates to `ql.Date`, chooses calendar from currency (USD GovernmentBond, EUR TARGET, GBP UnitedKingdom, JPY Japan, otherwise NullCalendar), uses `ql.ModifiedFollowing`, and creates two `ql.Schedule`s with their respective frequencies, the same start/end dates and calendar/convention, `ql.DateGeneration.Forward`, and `endOfMonth=False`.

- Schedule generation, business-day adjustment, adjusted coupon dates and date sequence generation are done by QuantLib `ql.Schedule`; no custom Python date loop exists for coupon schedule generation.
- The start and end input dates are passed as unadjusted dates; schedule applies the selected convention.
- Stub dates/rules are not supplied explicitly; QuantLib's default schedule behavior therefore applies. There is no explicit long/short first/last stub policy.
- End-of-month behavior is explicitly false.
- Fixed and floating payment dates come from the adjusted schedule dates and the swap leg conventions internal to QuantLib.
- Floating fixing dates are generated with `index.fixingDate(float_schedule[i])` by QuantLib.
- No explicit payment lag, fixing lag, termination-date convention, or separate fixed/floating calendars are configured by this wrapper; some index-specific conventions are inherited from the QuantLib index constructor.
- UI fields may be generic schema-provided, but the module itself does not provide a schedule implementation. The schema/frontend does not override these Python defaults in the audit-visible IRS module.

### Floating index, fixings and curves

`_get_ibor_index()` chooses a forecast curve from `forecast_curves[currency]`, falling back to the discount curve for that currency. Tenor maps only `1M`, `3M`, `6M`, with unknown strings falling back to 3M. It builds `ql.USDLibor`, `ql.Euribor`, or `ql.GBPLibor`; unsupported currencies fall back to USD Libor. Thus benchmark family is not independent of currency, and post-reform benchmark selection such as SOFR is not modeled here.

For past reset dates, the builder retrieves the currency discount curve (or the first available curve), derives one fixing rate as its continuously compounded 0.25-year zero rate, or falls back to the fixed coupon if no curve is found. It inserts that same rate into all past fixing dates with `index.addFixing`; duplicate-fixing `RuntimeError`s are silently ignored. It does not read `market_env.fixings`. This is custom Python logic coupled to QuantLib's fixing store and can affect repeated pricing through QuantLib global/index history.

`api/v1/helpers.py::build_market_env_from_request` uses `build_test_market_env` for standard rates/equity environments. That makes flat curves from `rate` (or the first `rate_curve` element's rate); it does not bootstrap the submitted tenor points. The constructed `MarketEnvironment` puts the same flat curve under USD discount and forecast keys. A distinct `YieldCurveBuilder` exists in `market/curves/yield_curve.py`, using deposit and swap helpers and `PiecewiseLogCubicDiscount`, with extrapolation enabled, but the audited IRS API path does not call it. No Excel ingestion path was found in the IRS construction flow; legacy placement scripts and spreadsheet utilities elsewhere are not connected here.

No `RelinkableYieldTermStructureHandle` use was found in the IRS path. Handles are `ql.YieldTermStructureHandle`s returned by the curve builders. Discount and forecast handles can be separate in `MarketEnvironment`, although the request helper creates flat same-rate handles in the non-FX case.

### Pricing calculation

`DiscountingSwapEngine` in `engines/analytic/rates_engines.py` returns `ql.DiscountingSwapEngine(curve)`. It selects `market_env.discount_curves[kwargs.get("currency", "USD")]`, falling back to the first curve. `PricingService` calls this engine with `instrument=instrument` but does not pass currency; consequently the engine defaults to USD even if the swap object is another currency, and can silently use the first curve if USD is absent.

The service then calls `InterestRateSwap.build()`, sets the returned QuantLib engine on the QL swap, and calls `NPV()`. The floating index references its selected forwarding handle; the engine discounts swap cashflows on the discount handle. This is **partially QuantLib**: QuantLib handles schedules, index accrual/fixing mechanics, `VanillaSwap` cashflow valuation and discounting, while Python maps product conventions, injects synthetic historic fixings, chooses curves and does request/environment assembly. There is no custom-Python IRS NPV formula in this path.

## 6. QuantLib usage audit

| QuantLib object | IRS use |
|---|---|
| `ql.Schedule` | Yes, twice (fixed and floating). |
| `ql.VanillaSwap` | Yes; one scalar notional, fixed coupon, zero spread, two schedules, one Ibor index. |
| `ql.IborIndex` | Yes via currency-specific subclasses; forwarding handle passed to index constructors. |
| `ql.DiscountingSwapEngine` | Yes, engine returns it using a discount curve handle. |
| `ql.YieldTermStructureHandle` | Yes, through curve/environment construction. |
| `ql.RelinkableYieldTermStructureHandle` | Not found in the IRS path. |
| `index.addFixing` | Yes, synthetic single-rate history for past fixing dates. |
| Explicit curves bootstrapped from the IRS API request | No; the API helper currently builds flat curves. |

The label “fully QuantLib” would obscure Python-side trade/convention selection, synthetic fixing handling and curve selection. The calculation engine and swap valuation are QuantLib-backed, but market and trade semantics are partly custom and under-specified.

## 7. PricingService audit

`PricingService` is the central intended orchestrator, with registries for instrument, model, engine and default-pricer configuration. Its default configs cover only vanilla, barrier and Asian options; IRS requests must explicitly supply model and engine or default config lookup fails. The visible UI requests `discounting`/`analytic`, while the engine is registered under both `("irs", "discounting")` and `("irs", "analytic")`.

The IRS schema exposes model key `discounting`, and the active endpoint forwards it as `model_type`; however, no `discounting` model registration or alias exists in `registry/bootstrap.py` or the model modules inspected. The registry bootstrap aliases only `analytical` to the Black-Scholes model. Therefore a request carrying the UI-declared `discounting` key fails at `model_registry.get("discounting")` unless some caller substitutes another model key. The rates model file documents `HullWhiteModel` and `HazardRateModel` stubs; `DiscountingSwapEngine.supported_models()` claims Black-Scholes and Hull-White, but does not use the model in its build method. The service does not enforce declared supported-model lists.

`PricingService` creates the model, creates the engine, builds the QL engine first, then calls instrument `build`, attempts `setPricingEngine`, and obtains NPV. It wraps all failures in `PricingError`. It also has a separate typed direct-engine path specifically for FX forwards. Model, engine and market are not cleanly decoupled for every instrument, but IRS does pass through the service on the active pricing route.

## 8. MarketEnvironment audit

`core/interfaces/base.py::MarketEnvironment` holds pricing date; discount and forecast curve maps; volatility surfaces; spot; fixings; correlations; hazard curves; and dividend curves. `set_evaluation_date()` sets the global `ql.Settings.instance().evaluationDate`. IRS uses the evaluation date and discount/forecast maps but ignores the `fixings` dictionary and does not consume conventions from environment. There is no dedicated rate-convention or index-definition object in the IRS path.

The global QuantLib evaluation date and fixing history are process-global/shared concerns. Repricing trades at different dates or repeatedly adding fixings is therefore an important integration risk. `build_market_env_from_request` currently produces demonstration flat curves, while `market/curves/yield_curve.py` also has bootstrapping utilities that are not wired into this request flow.

## 9. API audit and architectural bypasses

### IRS path

The active main-app pricing endpoint does not directly call IRS pricing functions: it calls the common instrument builder, market builder and `PricingService`. No direct IRS NPV function exists in active API code.

### Other bypasses / alternate architecture

- `api/fastapi/routes/pricing.py` is another direct service caller with its own request and `_factory` construction path. It is not mounted by `api.app`; `_factory` was not found, so status is unclear.
- `services/calibration/implied_vol.py` contains standalone Black-Scholes valuation math for calibration; it is not the IRS path, but it bypasses `PricingService` and instrument/engine abstractions for those calculations.
- `instruments/fx/fx_forward.py` calculates forward and NPV with custom Python math and returns `AnalyticalInstrument`; `PricingService` has a dedicated branch to return engine results. This deliberately bypasses QuantLib instrument construction and ordinary model-engine attachment while still entering the service.
- `instruments/fx/fx_range_forward.py` computes its wrapper NPV by direct arithmetic over leg NPVs, though its legs and API integration require separate tracing to establish whether the wrapper is serviced.
- Several bulk-upload endpoint variants contain their own trade parsing / flat-rate fallback and duplicated control flow. Their pricing fallback calls `PricingService`, so they bypass centralized request-to-domain/market setup more than the service itself.
- `session_zip/`, `api/backup`, `api/v1/*_old.py`, `bulk_upload_*` alternatives, frontend backups and root demos are parallel/legacy-looking implementations. They should not be treated as active without explicit import/route evidence.

The primary active router's pricing endpoints, jobs, risk, sensitivities, portfolio, export and comparison use `PricingService`. No direct IRS-specific pricing call from a mounted endpoint was found.

## 10. Test audit

### Inventory and coverage observed

| Instrument/area | Existing tests | Classification and limits |
|---|---|---|
| Vanilla/equity options | `test_vanilla_pricing_smoke.py`, `regression/test_equity_pricing.py`, exotics and FD convergence tests | Service-level smoke and regression/property checks; some approximate expected prices and put-call parity. Not broad API-to-QuantLib architecture coverage; possible engine import mismatch in regression fixture. |
| FX forward | Engine/service/API and QL-pattern tests | Unit/integration-style tests check service diagnostics and engine behavior. FX-focused, no bearing on IRS correctness. |
| Bulk upload | One service-level bulk upload test | Limited upload path; multiple endpoint variants are not comprehensively covered. |
| IRS, bond, FRA, cap/floor, swaption, CDS | No instrument-specific tests found in `tests/`. | No numerical baseline, schedule tests, request tests, fixing tests, curve wiring or architecture assertions. |
| Market/model/engine unit folders | Mostly `__init__.py` placeholders | No substantive dedicated tests visible for many components. |
| Integration folder | `__init__.py` only | No suite connecting active API request through market, registry, instrument, engine and response. |

The tests directory has `unit`, `integration`, `regression`, `fixtures`, plus a root `test_exotics.py`. `pyproject.toml` declares pytest markers and config but no dedicated architecture test tree. Existing equity “regression” values are approximate with broad tolerances; there are no SME-defined cases in the inspected repository. No IRS values or SME case sources were found.

### Most important gaps

1. IRS acceptance and convention cases, including independent SME/reference values and agreed tolerances.
2. Trade parsing/default/validation tests for every required economic field (spread, benchmark, pay/receive, amortization and dates).
3. Schedule-date assertions for each leg: holiday calendar, business-day adjustment, stubs, EOM, payment/fixing lags and reset dates.
4. Curve construction tests and proof that request curves/quotes map to the intended discount and forwarding curves; current request data does not reach bootstrapping.
5. Fixing behavior tests for past, today and future resets; supplied fixings, missing fixings, duplicates, repeated pricing and multiple valuation dates.
6. QuantLib wiring tests verifying `VanillaSwap`, schedules, index/forward handle and discount engine handles with distinct curves.
7. Service/registry tests for model/engine selection, currency propagation, unsupported combinations and returned `PricingResult` fields.
8. Active API end-to-end tests from JSON request through response, plus frontend payload contract tests.
9. Determinism/independence tests for global QuantLib evaluation date and fixing state.

## 11. TDD readiness and proposed hierarchy

Do not write these tests until the business conventions and reference cases are agreed. Proposed target layout:

```text
tests/
├── unit/
│   ├── instruments/rates/test_irs_trade_and_schedule.py
│   ├── market/test_rate_curves_and_fixings.py
│   ├── engines/test_discounting_swap_engine.py
│   └── services/test_pricing_service_irs_dispatch.py
├── integration/
│   ├── api/test_irs_pricing_request.py
│   └── pricing/test_irs_market_to_result.py
├── regression/
│   └── rates/test_irs_reference_cases.py
└── architecture/
    ├── test_instrument_registry_contract.py
    ├── test_pricing_service_boundary.py
    └── test_irs_quantlib_wiring.py
```

Retain the existing unit smoke tests, FX-specific tests and useful equity regression/exotic/FD suites, but first reconcile stale/inconsistent fixtures and expected values. Unit tests should pin pure trade validation and schedule conventions; integration tests should exercise the real active route and multi-curve/fixing path; regression tests should use approved SME cases and market snapshots; architecture tests should assert the allowed service path, registry registrations and intended QuantLib object/handle wiring. Add independent cashflow-level expectations so a shared implementation and its “expected” output cannot mask the same mistake.

## 12. Packaging audit

- `Optima.spec` uses `main.py`, creates a one-file/windowed `Optima` executable, and includes frontend/static plus major Python source packages and a hardcoded absolute QuantLib site-packages path. It calls PyInstaller `collect_all` for QuantLib, FastAPI, Uvicorn, Starlette, FPDF, Plotly, Kaleido, OpenPyXL and Requests; hidden imports are manually listed for server modules.
- `build.bat` activates a hardcoded local Anaconda environment, invokes PyInstaller one-file/no-console, repeats `--add-data` and `--collect-all` settings, then points to `dist/Optima.exe`.
- `main.py` is the frozen entry point and changes working directory to the executable directory when frozen. It starts the local server and opportunistically starts Ollama.
- `docker/Dockerfile` and `docker-compose.yml` are separate container workflow. `environment.yml`, `pyproject.toml`, `Makefile` and `WINDOWS_SETUP.md` also contain setup/build context.
- Generated folders `build/` and `dist/` exist in the repository workspace. Packaging consistency and inclusion of data, credentials/config, and non-source resources need separate verification; no build was run.
- Clear local-machine assumptions: absolute `C:\Users\Abhishek\anaconda3` paths; no platform-neutral environment resolution. `pyproject.toml` does not list QuantLib among project dependencies despite it being required throughout source and explicitly bundled by packaging.

Packaging is not a current development priority and was not changed.

## 13. Architectural deviations

1. Repository layout implies a general Instrument/Model/Engine/MarketEnvironment architecture, but `PricingService` has product-specific FX logic and engines can contain their own model construction.
2. IRS is a thin wrapper with undeclared product defaults and synthetic fixings, not a trustworthy specification of the intended new implementation.
3. API curve request accepts tenor points, but active helper uses only the first rate to create a flat curve.
4. IRS model and engine names are inconsistent across UI (`discounting` model) and registry/model concepts; the engine ignores its model argument.
5. The IRS engine call omits currency, causing USD/default-first curve selection.
6. MarketEnvironment has fixings and multiple curve maps, but IRS does not consume fixings and standard API market setup creates same-rate flat discount/forecast curves.
7. `session_zip`, backup endpoints, old schemas/helpers, multiple bulk-upload variants and duplicate frontend implementations blur source of truth.
8. Test folder taxonomy suggests unit/integration/regression layers, but integration/architecture coverage is missing and no IRS test exists.
9. `pyproject.toml` dependency metadata and PyInstaller environment assumptions do not describe one reproducible distribution contract.

## 14. Loose ends

### Requirements and SME-dependent behavior

- Which currency, benchmark/index and fallback conventions are in scope (e.g., legacy IBOR versus overnight rates)?
- Which calendar source, day-count, payment/reset/fixing lag, roll convention, stub rules, EOM behavior, payment delay and termination-date rule apply per currency/index/leg?
- Is spread supported, and on which leg? Is spread quoted as decimal or bps? Are amortizing notionals, exchanges, upfronts, compounding, business-day overrides or fixing overrides required?
- What determines pay/receive semantics and trade sign? Is `direction` normalized to an enum?
- What is the effective-date rule relative to trade date/settlement, and how are expired, spot-starting and same-day trades handled?
- How are discount and forecast curves sourced, named, bootstrapped, interpolated and extrapolated? Which curve takes precedence? Are OIS discounting and collateral conventions needed?
- What is the approved source of historical fixings, and how should missing/duplicate fixings behave?
- Which SME cases and authoritative values establish acceptance and tolerances?

### Code and operational risks

- No IRS/bond/FRA/cap-floor/swaption regression or schedule tests.
- Existing integration directory has no tests; test architecture is not enforced.
- Past fixing synthesis uses the discount curve's quarter-year zero rate for every historical reset.
- Unknown direction, tenor and frequency values silently fall back to defaults; unsupported currencies select USD Libor/NullCalendar.
- Service omits currency when constructing the rates engine.
- Global QuantLib settings and fixing store can leak between valuations/tests.
- Flat rate curve builder and bootstrapped curve builder coexist without clear API selection; input `rate_curve` shape/meaning is under-specified and only its first value is read.
- Frontend IRS module is a placeholder; schema refers to model `discounting`, which is not a documented model object.
- Alternate app imports `_factory` not found in the repository; `session_zip` and old variants need source-of-truth decisions.
- Duplicated bulk upload logic risks inconsistent parsing/pricing behavior.
- Potential stale regression expectations/imports merit separate triage before treating existing tests as a clean baseline.
- `environment.yml`, `pyproject.toml`, Windows build scripts and PyInstaller spec may describe different environments; absolute machine paths reduce portability.
- Several generic folders and empty package initializers make intended extension points unclear; do not infer implemented behavior from directory names.

## 15. Recommended next step

Before implementation, hold an IRS convention/requirements review with the pricing SME and write down one minimally scoped product definition, reference market snapshot, fixing policy and authoritative NPV/cashflow cases. Confirm the active endpoint payload and curve source. Turn that agreement into failing unit, architecture and regression tests, then implement to those tests. Treat `VanillaOption` primarily as a service-wiring example; decide separately whether its general design is appropriate for rates.

## GO / NO-GO

> Is the repository sufficiently understood to begin a clean IRS TDD implementation?

**NO-GO for implementation now.** The code architecture and existing IRS behavior are sufficiently traced to identify where a clean implementation belongs and what must not be copied uncritically. The missing information is the IRS specification itself: supported benchmark/index set; currency-specific leg, calendar, day-count, roll, stub, EOM, payment/fixing/reset and lag conventions; spread and amortization requirements; pay/receive sign rules; discount/forecast curve construction and source; fixing source/missing-fixing policy; API curve payload semantics; and SME-approved reference trades, cashflows and NPVs with tolerances. Without these, tests would encode assumptions rather than requirements. Once those are agreed, the repository is understood enough to begin test-first implementation.

