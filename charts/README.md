# Optima Frontend — Developer Guide

## What is this?

Optima is a single-page derivatives pricing UI served directly by the FastAPI backend. No build step, no npm, no React, no Dash. Three files, one HTTP server, everything works.

```
frontend/
├── templates/
│   └── optima.html          ← The page (HTML + CSS, no inline JS)
├── optima_schema.js          ← Schema: 27 instruments, all configurations
└── optima.js                 ← Application logic: UI builders, API calls, charts
```

## How it works

### Architecture

```
Browser                          FastAPI Server (port 8000)
┌──────────────────────┐        ┌────────────────────────┐
│ optima.html           │  GET / │                        │
│  ├ optima_schema.js  │ ←──────│  Serves HTML at /       │
│  ├ optima.js         │        │  Serves JS at /static/  │
│  └ Plotly CDN        │        │                        │
│                      │        │  API at /api/v1/        │
│  fetch('/api/v1/..') │ ──────→│    /pricing/single     │
│                      │ ←──────│    /sensitivities/...  │
│  Render results      │        │    /risk/scenario      │
└──────────────────────┘        └────────────────────────┘
```

Everything is same-origin — the HTML and API are both served by FastAPI on port 8000. No CORS issues, no proxy needed.

### File responsibilities

**optima.html** — Structure and styling only. Contains the Home page (instrument catalog with 5 asset class sections), the Workspace skeleton (trade inputs, market data, model/engine, NPV display, greeks, comparison table), and all collapsible output panels (payoff, cashflows, risk, curves, resets, valuation, analysis). Never edit this file to change behavior — only touch it for layout or styling changes.

**optima_schema.js** — The brain of the UI. Every instrument is defined here with its label, asset class, market data requirements, available models, engines (with engine-specific parameters), sensitivity measures, analysis panels, and output panel flags. Adding a new instrument means adding entries to SCHEMA and FIELDS in this file, plus an HTML card on the Home page. That's it.

**optima.js** — All the behavior. Reads the schema, dynamically builds forms, handles button clicks, makes API calls, parses responses, renders Plotly charts, and manages navigation. Depends on optima_schema.js being loaded first.

### Schema-driven design

The schema dictates everything the UI shows. Example for a vanilla option:

```javascript
vanilla_option: {
  label: 'Vanilla Option',
  asset: 'Equity',
  badge: 'badge-eq',
  market_data: ['spot', 'vol', 'div_yield', 'rate_curve'],
  models: [{v:'black_scholes', l:'Black-Scholes'}, {v:'heston', l:'Heston'}],
  engines: [
    {v:'analytic', l:'Analytic', params:[]},
    {v:'monte_carlo', l:'Monte Carlo', params:['mc_paths','mc_steps']},
  ],
  sensitivities: [
    {id:'delta', l:'Delta', d:4},
    {id:'gamma', l:'Gamma', d:4},
    {id:'vega',  l:'Vega',  d:4},
  ],
  analysis: ['spot_ladder', 'vol_ladder', 'spot_vol_matrix', 'scenario'],
  payoff: true,
  cashflows: false,
  risk_ladder: false,
  curves: false,
  resets: false,
}
```

What this controls:

| Schema field | UI effect |
|---|---|
| `market_data` | Which input fields appear in the Market Data card |
| `models` | Dropdown options in the Model selector |
| `engines` | Dropdown options in the Engine selector |
| `engines[].params` | Which engine-specific fields appear (MC paths, Heston params, etc.) |
| `sensitivities` | Which KPI tiles render in the Sensitivities card, and what measures to request from the API |
| `analysis` | Which analysis panels appear (ladders, heatmap, scenario) |
| `payoff` | Show/hide the Payoff Diagram section |
| `cashflows` | Show/hide the Cashflow Schedule section |
| `risk_ladder` | Show/hide the DV01 by Bucket section |
| `curves` | Show/hide the Curve Data section |
| `resets` | Show/hide the Resets (Fixings) section |

### The flow

1. User clicks an instrument card on the Home page
2. `openWorkspace(instType)` reads `SCHEMA[instType]`
3. `buildTradeFields()` renders form inputs from `FIELDS[instType]`
4. `buildMarketData()` renders market data inputs from `schema.market_data`
5. `buildModelEngine()` populates model/engine dropdowns from schema
6. `buildGreeks()` creates sensitivity KPI tiles from `schema.sensitivities`
7. `buildOutputPanels()` shows/hides collapsible sections based on schema flags
8. `buildAnalysis()` creates analysis cards from `schema.analysis`
9. User clicks "Price" → `collectPayload()` gathers all form values → `apiPost('/pricing/single', payload)` + `apiPost('/sensitivities/greeks', payload)`
10. Results render into NPV display and Greek tiles

## Output panels

### Universal (all instruments)

| Panel | Section | Trigger | API endpoint |
|---|---|---|---|
| NPV + Meta | Always visible | Price button | POST /pricing/single |
| Sensitivities | Always visible | Auto with Price | POST /sensitivities/greeks |
| Engine Comparison | Hidden until used | Compare button | POST /pricing/compare |
| Valuation (MTM) | Collapsible | Valuate button | POST /pricing/single |
| Diagnostics | Collapsible | Auto with Price | (raw JSON display) |

### Options only (payoff: true)

| Panel | Trigger | API |
|---|---|---|
| Payoff Diagram | Auto on workspace open | None (client-side math) |

### Rates / Credit (cashflows: true)

| Panel | Trigger | API |
|---|---|---|
| Cashflow Schedule | Load Cashflows button | POST /pricing/cashflows |

### Rates only (risk_ladder: true)

| Panel | Trigger | API |
|---|---|---|
| DV01 by Bucket | Compute Risk Ladder button | POST /sensitivities/ladder |

### Rates only (curves: true)

| Panel | Trigger | API |
|---|---|---|
| Curve Data | Load Curves button | POST /market/yield-curve/query |

### Floating-rate only (resets: true)

| Panel | Trigger | API |
|---|---|---|
| Resets (Fixings) | Load Resets button | POST /pricing/resets |

### Analysis (schema.analysis)

| Panel | Trigger | API |
|---|---|---|
| Spot/Vol/Rate/Spread Ladder | Run button | POST /sensitivities/ladder |
| Spot × Vol Heatmap | Generate button | POST /sensitivities/matrix |
| Scenario Analysis | Run / Run All buttons | POST /risk/scenario |

## How to add a new instrument

### Step 1: Schema entry (optima_schema.js)

Add to `SCHEMA`:
```javascript
my_new_product: {
  label: 'My New Product',
  asset: 'Equity',
  badge: 'badge-eq',
  market_data: ['spot', 'vol', 'rate_curve'],
  models: [{v:'black_scholes', l:'Black-Scholes'}],
  engines: [{v:'analytic', l:'Analytic'}],
  sensitivities: [{id:'delta', l:'Delta', d:4}],
  analysis: ['spot_ladder'],
  payoff: true, cashflows: false, risk_ladder: false, curves: false, resets: false,
}
```

### Step 2: Trade fields (optima_schema.js)

Add to `FIELDS`:
```javascript
my_new_product: [
  {id:'underlying', label:'Underlying', type:'text', val:'AAPL'},
  {id:'strike', label:'Strike', type:'number', val:100},
  {id:'expiry', label:'Expiry', type:'date', val:'2026-12-31'},
]
```

### Step 3: Home page card (optima.html)

Add inside the appropriate asset class `<details>` section:
```html
<a class="inst-card" data-inst="my_new_product">
  <div class="ic-icon">📊</div>
  <div class="ic-name">My New Product</div>
  <div class="ic-desc">Description of the product</div>
</a>
```

Done. The workspace, market data form, model/engine dropdowns, sensitivity tiles, and all output panels will automatically adapt.

## API payload format

Every API call sends this structure:
```json
{
  "instrument": {
    "type": "vanilla_option",
    "params": {
      "underlying": "AAPL",
      "strike": 185,
      "expiry": "2026-01-15",
      "option_type": "call"
    }
  },
  "market_data": {
    "pricing_date": "2025-01-15",
    "underlyings": {
      "AAPL": { "spot": 192.50, "vol": 0.25, "div_yield": 0.005 }
    },
    "rate_curve": [{ "tenor": "1Y", "rate": 0.045 }]
  },
  "model": "black_scholes",
  "engine": "analytic",
  "engine_params": {}
}
```

`collectPayload()` in optima.js builds this by reading all form values.

## Charts

All charts use Plotly.js loaded via CDN. The dark theme matches the terminal aesthetic through `PLOT_LAYOUT` defaults in optima.js. Chart types used:

| Chart | Plotly type | Used in |
|---|---|---|
| Sensitivity ladder | scatter (line+markers) | Analysis ladders |
| Scenario P&L | bar | Scenario analysis |
| Spot × Vol | heatmap | Matrix analysis |
| Payoff diagram | scatter (lines) | Payoff panel |
| Yield curve | scatter (multi-line) | Curves panel |
| DV01 buckets | bar | Risk ladder panel |

## File locations

```
quantlib-pricing/
├── run.py                              ← Single entry point
├── api/
│   └── app.py                          ← Serves HTML + API
├── frontend/
│   ├── templates/
│   │   └── optima.html                 ← The page
│   ├── optima_schema.js                ← Instrument definitions
│   ├── optima.js                       ← App logic + charts
│   └── README.md                       ← This file
```

FastAPI serves:
- `GET /` → `frontend/templates/optima.html`
- `GET /static/*` → files from `frontend/` directory
- `POST /api/v1/*` → all API endpoints

## Running

```bash
cd quantlib-pricing
python run.py
```

Opens http://localhost:8000 automatically. One process, one port.

## Debugging

Open browser DevTools → Console. All API errors surface there. The Diagnostics panel in the workspace shows the raw JSON response from the last pricing call. Use `?inst=vanilla_option` URL parameter to jump directly to a workspace.
