# Optima — Handoff / Current State

**Purpose.** Single source of truth for where this project actually stands, so a fresh
session (Claude or human) can pick up work without re-reading a year of chat history.
Keep this file current — it is the first thing to read and the first thing to update.

**Status of this document.** First pass, reconstructed from the repository on
2026-08-24 by reading the source tree, README, CHANGELOG, DEV_GUIDE, the output-panel
spec and the loose notes files. Sections marked **[FILL]** could not be recovered from
the repo — the reasoning lives only in the original chat thread. See §9.

---

## 1. What Optima is

A multi-asset derivatives pricing platform on QuantLib-Python: registry-driven pricing
core, versioned FastAPI REST API, and a schema-driven single-page web terminal served by
the same FastAPI process. Ships as a PyInstaller executable (`dist/Optima.exe`) as well
as running from source.

Asset classes: equity, rates, credit, FX, commodity (inflation scaffolded, empty).

---

## 2. How it runs

```bash
python run.py     # uvicorn on 127.0.0.1:8001, opens browser, starts Ollama
python main.py    # same app with --reload, no browser, no Ollama
```

FastAPI serves the UI at `/` from `frontend/static/optima.html` and JS from `/static/*`.
Same-origin — no CORS proxy, no second dev server.

Note: `README.md` still documents port 8000, `uvicorn api.app:app`, and a separate Dash
frontend on 8050. That is historical. The live path is `run.py` on **8001**.

---

## 3. Architecture

### Dispatch chain (single deal)

```
UI collectPayload()               → frontend/static/optima_core.js
POST /api/v1/pricing/single       → api/v1/endpoints/pricing.py
  _resolve_underlying()           → api/v1/endpoints/pricing.py
  build_instrument_from_request() → api/v1/helpers.py
    instrument_registry.get()     → registry/__init__.py
  build_market_env_from_request() → api/v1/helpers.py
    build_flat_curve/build_flat_vol → market/curves/yield_curve.py
  PricingService.price()          → services/pricers/pricing_service.py
    market_env.set_evaluation_date()
    model_registry.get() → model.build_process()
    engine_registry.get() → engine.build()
    instrument.build() → ql.Instrument.NPV()
```

### Bulk upload (curve path)

```
processBulkFile()                 → optima_core.js
POST /api/v1/pricing/bulk-price   → api/v1/endpoints/bulk_upload.py
  parse_upload() → parse_all_market_data() → _parse_curve_sheet() → MarketCurves
  price_deals_with_curves() → MarketCurves.interpolate_forward()/interpolate_df()
```

### Layers

- `core/` — enums, abstract interfaces (`BaseInstrument`, `BaseEngine`, `BaseModel`,
  `BaseCurve`, `BaseVolSurface`), value objects (`Money`, `PricingDate`, `Tenor`,
  `Quote`, `Rate`, `TradeId`, `PricingResult`, `RiskResult`), 15+ typed exceptions,
  and `MarketEnvironment` — the one container for all market data.
- `registry/` — generic `Registry[T]`, singletons for instrument / engine / model /
  curve / calibrator / pricer_config, `auto_discover_modules()`, `bootstrap.py`.
- `instruments/`, `engines/`, `models/`, `market/`, `numerics/` — the quant core.
- `services/` — `PricingService` (dispatch + batch with error isolation),
  `RiskService` (bump-and-reprice Greeks, scenarios, stress, VaR, P&L explain),
  calibration, comparison, jobs, portfolio, export, report (Ollama).
- `api/v1/` — router aggregating 12 endpoint groups; `schemas.py` (Pydantic v2),
  `helpers.py` (instrument + market-env builders).
- `frontend/static/` — the live UI.

---

## 4. Frontend state

Live files (`frontend/static/`), load order matters:

```
schema/schema_master.js    SCHEMA, FIELDS, MODULE_TABS, ASSET_CLASSES; creates INSTRUMENT_REGISTRY
instruments/_base.js       COUNTERPARTY_FIELDS, FX_MARKET_DATA, METADATA_KEYS
instruments/<asset>/*.js   one module per instrument, self-registering
optima_registry.js         asserts every SCHEMA entry has a registry module
optima_core.js             ~86 KB — all behavior
optima.html                ~60 KB — structure + CSS only
```

Instrument module completeness (last known):

| Asset | Complete | Placeholder |
|---|---|---|
| FX | `fx_forward`, `fx_range_forward` | `fx_option`, `fx_seagull`, `fx_call_spread`, `fx_put_spread`, `fx_range_forward_opt`, `principal_only_swap`, `ccirs`, `fx_swaption`, `fx_digital`, `fx_barrier` |
| Rates | — | 8 placeholders |
| Equity | — | 7 placeholders |
| Commodity | — | 4 placeholders |
| Credit | — | 1 placeholder |

**Verify this table against `frontend/static/instruments/` before relying on it** — it is
the fastest-moving part of the repo.

Legacy, do not edit: `static_old/`, `streamlit/`, `react/`, `src/` (React+Vite scaffold,
never wired up), `templates/optima.html`, `static/working files backup/`,
`definitions/optima.js`.

---

## 5. Output panels — spec vs. reality

Per `Optima output spec.md` v0.4.0 (2026-02-28), status at time of writing:

| Panel | Instruments | Status |
|---|---|---|
| A NPV + Meta | all | done |
| B Sensitivities | all (schema-driven) | done |
| C Engine Comparison | 2+ engines | done |
| E Diagnostics | all | done |
| F Valuation (MTM P&L) | all | done |
| D Scenario Analysis | `scenario` in analysis | UI only — wire `/risk/scenario` |
| H Sensitivity Ladder | ladder keys in analysis | UI only — wire `/sensitivities/ladder` |
| I Sensitivity Matrix | `spot_vol_matrix` | UI only — wire `/sensitivities/matrix` |
| G Payoff Diagram | options | not built — client-side math, no API |
| J/M Cashflow Schedule | rates + credit | not built — **needs new `POST /api/v1/pricing/cashflows`** |
| K Risk Ladder (DV01 by bucket) | rates | not built — extend `/sensitivities/ladder` with `buckets` |
| L Curve Data | rates | not built — wire `/market/yield-curve/query` |
| N Spread Ladder (CS01) | CDS | not built |
| O Resets (Fixings) | IRS, COS | not built — **needs `POST /api/v1/pricing/resets`** |
| P Amortization Schedule | amortizing swaps | blocked on instrument-level amortization support |

Implementation order from the spec: (1) wire existing APIs — D, H, I; (2) client-side —
G; (3) new backend endpoints — J/M, K, L; (4) O, P.

Chart decision in the spec is inline SVG for the terminal aesthetic; the shipped UI uses
Plotly via CDN. **[FILL]** — confirm which one won.

---

## 6. Backend build state

From `CHANGELOG.md`, v0.2.0 (Options Pricing Module, in progress):

Done:
- `instruments/common/payoffs.py`, `exercise.py` — Payoff/Exercise builder factories
- `instruments/equity/vanilla_option.py` — unified European/American/Bermudan
- `engines/analytic/bsm_engine.py` — Analytic European + Analytic Heston
- `engines/lattice/binomial_engine.py` — CRR/JR/Tian/LR/Joshi4, all exercise types
- `engines/finite_difference/` — `fd_config.py` (7 schemes, 6 grid presets, runtime
  estimation, node safeguards), `fd_dividends.py`, `fd_result.py`, rewritten
  `fd_vanilla_engine.py` (+ Heston 2D Douglas, discrete-dividend engine)
- `engines/monte_carlo/` — `mc_result.py` (Parquet/CSV path storage), `mc_simulation.py`
  (GBM + Heston Euler), `longstaff_schwartz.py` (vectorized backward pass),
  `mc_vanilla_engine.py`, `rng.py` (Mersenne/Sobol/Halton + antithetic),
  `variance_reduction.py` (control variate, moment matching), `mc_greeks.py`
  (pathwise delta/gamma, likelihood-ratio vega/rho, FD theta)

Not done:
- `models/equity/heston.py` — full Heston SV + calibration
- `services/calibration/implied_vol_solver.py`
- Barrier + Digital instruments and engines
- Engine comparison / benchmarking utility
- Regression tests for all of the above

MC v2 audit fixes already applied (T from instrument expiry not hardcoded, market data
extracted at correct T and strike, Heston uses proper Euler not GBM, LS vectorized,
discount factors from the actual curve per step, MCResult wired into
`PricingResult.diagnostics`).

---

## 7. Design decisions (recovered)

1. **Registry over factory.** New products decorate themselves and are available
   everywhere — zero API or frontend changes to add one.
2. **`MarketEnvironment` as one container.** All curves, surfaces, spots, fixings in a
   single object, passed everywhere, bumped wholesale for scenarios.
3. **Central dispatch in `PricingService`.** Instrument type → default model + engine
   from `pricer_config_registry`, always overridable explicitly.
4. **Bump-and-reprice Greeks.** Engine-agnostic; analytic Greeks used as an optimization
   where the engine exposes them.
5. **Clean QuantLib wiring.** `instrument.build() → ql.Instrument`,
   `model.build_process() → ql.Process`, `engine.build() → ql.PricingEngine`.
6. **Schema-driven UI.** One JS object per instrument decides every visible control.
7. **No frontend build step.** Vanilla JS served by FastAPI, same-origin. React and
   Streamlit were both tried and abandoned.
8. **Split the frontend by concern, not by size.** HTML = structure/CSS, schema = data
   definitions, core = behavior — so a change to one chart never touches the markup.
   Threshold agreed at the time: split further if a JS file passes ~2,500 lines
   (`optima_core.js` is now ~86 KB and past that — revisit).
9. **Versioned API** under `/api/v1/` for backward-compatible evolution.

---

## 8. Known issues / debt

**Repo hygiene**
- `.gitingore` is misspelled — git has never been ignoring anything. Rename to
  `.gitignore` and check what is currently tracked.
- Large binaries in the tree: `dist/Optima.exe` (~120 MB), `quantlib-pricing.zip`
  (~25 MB), `session_zip.zip`, `data/market_data.db` (~4 MB), `frontend/node_modules/`.
- Duplicate/backup source files that will confuse both you and any indexer:
  `api/v1/endpoints/bulk_upload{,_w2,_working,_ww}.py` (4 copies, 28–35 KB each),
  `api/v1/{helpers_old,schemas_old,router_work}.py`, `api/backup/app.py`,
  `api/fastapi/` (superseded by `api/v1/`), `frontend/static_old/`,
  `frontend/static/working files backup/`, `nn1.py`/`nn2.py`/`nn3.py`,
  `new 4.txt`, `New Text Document.txt`.
- Notes scattered in untitled text files: `claude_notes.txt`,
  `Learnings/New Text Document.txt`, `hisrotical_data_notes.txt` (sic),
  `unittest_sample_scripts.txt`, `UI_notes.txt` (empty).
- `docs/architecture/`, `docs/api_docs/`, `docs/user_guides/` contain only `__init__.py`.

**Functional (from CHANGELOG 0.1.0, verify whether still true)**
- `FXForward.build()` used `VanillaOption` as a placeholder — needs proper forward pricing.
  The `Learnings` call-trace suggests a real `instruments/fx/fx_forward.py` now exists.
- Rate bumping in `RiskService` rebuilds flat curves instead of bumping the bootstrapped curve.
- No persistence layer — repositories are interfaces only.
- gRPC servicers not implemented (`api/grpc/` is empty scaffolding).
- Missing `__init__.py` re-exports in most subpackages.
- `api/v1/router.py` ends with a stray triple-quoted block; several routers are imported
  under bare `try/except` so failures are silent.

**Docs**
- `README.md` describes a Dash frontend, 13 instruments, port 8000, and "36/36 tests
  passing". All historical. Rewrite or mark deprecated.
- `DEV_GUIDE.md` references `make streamlit` and a Streamlit dashboard on 8501.

---

## 9. [FILL] — recover these from the original chat thread

Ask the old conversation for each of these before archiving it:

1. **Instrument coverage.** The frontend schema claims 27 instruments; the backend
   registry covers far fewer. Which of the 27 actually price end-to-end today?
2. **The FX build-out.** Why FX first, and why `fx_range_forward` before `fx_option`?
   What is the intended order for the remaining FX placeholders?
3. **Chart library.** Spec says inline SVG; shipped code uses Plotly CDN. Which is the
   decision, and does the PyInstaller build tolerate a CDN dependency offline?
4. **Bulk upload.** Four versions of `bulk_upload.py` exist. What distinguishes them,
   which is live, and what was the Excel/CSV input contract agreed with the user?
5. **Ollama reports.** Which model, what prompt contract, and what happens when Ollama
   is not running?
6. **Historical market data.** Schema of `data/market_data.db`, what the scheduler
   refreshes, which provider (OpenBB vs yfinance) is primary and why.
7. **Curve bootstrapping.** Are production curves bootstrapped, or still flat curves
   from `build_flat_curve()`? What instruments feed the bootstrap?
8. **Multi-currency / discounting.** Is there a CSA/collateral discounting story, or is
   everything single-curve?
9. **Testing.** The README claims 36 integration tests at 100%. Where do they live now
   (`frontend/dash/test_integration.py` no longer exists), and what is the current
   green/red state?
10. **Packaging.** What does `Optima.spec` bundle, and what is the release process —
    who is the .exe for?
11. **Anything I ruled out.** Approaches tried and abandoned, and why — this is the most
    expensive knowledge to lose and none of it survives in the repo.

---

## 10. Next actions (proposed)

1. Answer §9 from the old chat, fold the answers into this file, then archive the thread.
2. Fix `.gitingore` → `.gitignore`; untrack binaries and `node_modules`.
3. Delete or move the duplicate/backup source files into a single `_archive/` folder
   outside the package so they stop competing with live code.
4. Rewrite `README.md` to describe the actual system (vanilla-JS UI, port 8001, current
   instrument list).
5. Resume the output-panel spec at Phase 1: wire Scenario, Ladder and Matrix to their
   existing endpoints.
6. Close out CHANGELOG 0.2.0: Heston model, implied-vol solver, barrier/digital,
   engine comparison utility, regression tests.
