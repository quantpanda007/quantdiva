# Optima — Project Instructions

## What this is

Optima is a full-stack, multi-asset derivatives pricing platform built on QuantLib
(Python bindings, C++ via SWIG). It prices equity, rates, credit, FX and commodity
products through a registry-driven dispatch layer, exposes everything over a versioned
FastAPI REST API, and ships a Bloomberg-terminal-styled single-page web UI served by
that same FastAPI process. Package root is `quantlib-pricing/`, Python package name
`quantlib-pricing` v0.1.0, API version 0.2.0.

I am the sole developer. Treat me as competent in quant finance and Python; skip
basic explanations of derivatives, QuantLib idioms, or FastAPI unless I ask.

## Stack

| Layer | Technology |
|---|---|
| Pricing | QuantLib-Python |
| Language | Python 3.11 (`requires-python >=3.10`) |
| Backend | FastAPI + Uvicorn, Pydantic v2 |
| Frontend | Vanilla JS + HTML/CSS, Plotly via CDN — **no build step, no npm, no framework** |
| Data | SQLite (`data/market_data.db`), OpenBB / yfinance for live quotes |
| Reports | Local Ollama LLM (`services/report/`) |
| Env | Conda (`environment.yml`), Windows dev box |
| Packaging | PyInstaller (`Optima.spec`, `build.bat`) → `dist/Optima.exe` |
| Tooling | pytest, ruff (line-length 100), mypy, black |

## Entry point

`python run.py` → uvicorn on **127.0.0.1:8001**, opens the browser, starts Ollama in a
background thread. `main.py` is the same thing with `--reload` and no browser/Ollama.
FastAPI serves the UI at `/` and static JS at `/static/*`, so everything is same-origin —
there is no CORS proxy and no separate frontend server.

## Canonical layout

```
core/         domain layer — enums, interfaces (BaseInstrument/BaseEngine/
              MarketEnvironment), value objects, typed exceptions
instruments/  equity | rates | credit | fx | commodity | inflation | common
engines/      analytic | finite_difference | lattice | monte_carlo | integral
models/       equity (BSM, Heston) | rates | credit | fx | common
market/       curves, volatility (SVI/SABR/local vol), bootstrapping, conventions,
              historical (SQLite store + scheduler), providers, snapshots, scenarios
services/     pricers (PricingService dispatch) | greeks | risk | calibration |
              comparison | jobs | portfolio | export | report | dispatch
registry/     Registry[T] + bootstrap.py — plugin-style auto-registration
api/          app.py (FastAPI app) + v1/{router,schemas,helpers,endpoints/}
frontend/     static/ — THE LIVE UI (see below)
workflows/    batch | lifecycle | market_build | pricing | risk
tests/        unit | regression | integration | fixtures
```

## Frontend — read this before touching UI code

The live UI is `frontend/static/`, loaded in this order:

```
schema/schema_master.js   SCHEMA, FIELDS, MODULE_TABS, ASSET_CLASSES,
                          creates INSTRUMENT_REGISTRY = {}
instruments/_base.js      shared field blocks (COUNTERPARTY_FIELDS,
                          FX_MARKET_DATA, METADATA_KEYS)
instruments/<asset>/*.js  one file per instrument; each registers itself:
                          INSTRUMENT_REGISTRY['fx_forward'] = {fieldGroups, mapPayload, …}
optima_registry.js        verifies every SCHEMA instrument has a registry entry
optima_core.js           all behavior: form building, API calls, charts, navigation
optima.html              structure + CSS only — never edit to change behavior
```

It is **schema-driven**: the schema entry for an instrument decides which market-data
fields, model/engine dropdowns, engine params, Greek tiles, analysis panels and output
panels appear. Adding an instrument = schema entry + `FIELDS` entry + an instrument JS
module + a home-page card in `optima.html`. Nothing else changes.

Panel visibility flags: `payoff`, `cashflows`, `risk_ladder`, `curves`, `resets`,
`amortization`; analysis keys: `spot_ladder`, `vol_ladder`, `rate_ladder`,
`spread_ladder`, `spot_vol_matrix`, `scenario`.

**Legacy — do not edit, do not cite as current:** `frontend/static_old/`,
`frontend/streamlit/`, `frontend/react/`, `frontend/src/` (React+Vite scaffold),
`frontend/templates/optima.html`, `frontend/static/working files backup/`,
`definitions/optima.js`.

## Backend conventions

- **Registry pattern, not factories.** Every instrument, engine and model registers
  itself with a decorator: `@instrument_registry.register_decorator("vanilla_option")`.
  The API and UI never import concrete product classes.
- **`MarketEnvironment` is the single market-data container** — discount curves,
  forecast curves, vol surfaces, hazard curves, spots, fixings. Passed everywhere;
  bumped wholesale for risk scenarios.
- **Dispatch chain:** `PricingService.price()` → `pricer_config_registry` gives default
  model + engine (overridable) → `model.build_process()` → `engine.build()` →
  `instrument.build()` → `ql.Instrument.NPV()`.
- **Greeks:** bump-and-reprice (central difference) by default; analytic Greeks used
  where the engine exposes them. Instrument-aware — equity gets Delta/Gamma/Vega/
  Theta/Rho, rates get DV01/Duration/Convexity, credit gets CS01.
- Absolute imports from the package root only (`from core.enums.definitions import …`).
  No relative imports across packages.
- `snake_case.py` files, `PascalCase` classes, `test_<module>.py` tests.
- ruff line-length 100, target py310, rules `E,F,I,N,W,UP`.
- pytest markers: `slow`, `regression`, `integration`. `pythonpath = ["."]`.

## Standard API payload

```json
{
  "instrument": {"type": "vanilla_option", "params": {…}},
  "market_data": {
    "pricing_date": "2025-01-15",
    "underlyings": {"AAPL": {"spot": 192.5, "vol": 0.25, "div_yield": 0.005}},
    "rate_curve": [{"tenor": "1Y", "rate": 0.045}]
  },
  "model": "black_scholes",
  "engine": "analytic",
  "engine_params": {}
}
```

Endpoint groups under `/api/v1/`: `pricing` (single, batch, compare, bulk-price),
`sensitivities` (greeks, ladder, matrix), `risk` (scenario, stress-test, pnl-explain,
var), `calibration`, `market` (vol-surface, yield-curve, live, historical), `registry`,
`portfolio`, `jobs`, `snapshots`, `export`, `reports`.

## Docs in project knowledge — trust order

Where documents disagree, believe them in this order, and tell me when you spot a
contradiction rather than silently picking one:

1. Source code
2. `HANDOFF.md` — current state, decisions, open threads
3. `Optima output spec.md` — the forward-looking panel spec (v0.4.0)
4. `charts/README.md` — frontend architecture (accurate on the schema-driven design,
   stale on the 3-file split)
5. `CHANGELOG.md` — build log, accurate for the 0.1.0/0.2.0 backend work
6. `README.md` — **substantially stale**: it describes a Dash frontend and 13
   instruments. Both are historical. Architecture, engines and design-principle
   sections are still broadly right.

## How I want you to work

- **Ask before building.** If scope, an edge case, or a design choice is ambiguous,
  ask one round of questions first. I would rather answer three questions than throw
  away a 500-line file.
- **Complete files, with the path as a header** — `**File: `engines/lattice/binomial_engine.py`**`.
  I place them with `python sync_files.py` (staging-folder convention: `/` → `__`,
  e.g. `engines__lattice__binomial_engine.py`). Never hand me a diff fragment or
  "add this somewhere near the top".
- **One concern per file.** If a file is heading past ~1,500 lines, propose a split
  before writing it.
- **Don't rewrite what you weren't asked to touch.** Preserve existing behavior,
  naming and structure unless the change is the point.
- Every new instrument / engine / model needs: registration decorator, a unit test in
  `tests/unit/test_<category>/`, and a regression test with known-good values in
  `tests/regression/`.
- Flag when a change needs a matching frontend schema update, and vice versa.
- Update `CHANGELOG.md` and `HANDOFF.md` when a task lands something structural.
- No emoji in code or docs. Keep prose tight.
- If you are unsure whether something exists in the codebase, say so and ask me to
  paste the file rather than inventing an API.
