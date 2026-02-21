# QuantPricer

**QuantLib-based derivatives pricing platform with FastAPI backend and Dash frontend.**

A production-grade pricing library covering vanilla and exotic options, multiple pricing engines, risk analytics, and interactive visualization.

---

## Architecture

```
quantlib-pricing/
├── core/                          # Domain layer
│   ├── instruments/               # Vanilla, Barrier, Digital, Asian, Lookback
│   ├── engines/                   # Analytic, FD, Binomial, Monte Carlo
│   ├── models/                    # Black-Scholes, Heston
│   ├── portfolio.py               # Portfolio with aggregated valuation
│   └── greeks/                    # Bump-and-reprice sensitivities
│
├── market/                        # Market data layer
│   ├── environment.py             # MarketEnvironment (curves, surfaces)
│   ├── volatility/                # SVI vol surface, local vol, SABR
│   └── snapshots/                 # Market data versioning + checksums
│
├── services/                      # Application services
│   ├── calibration/               # Heston calibration, implied vol solver
│   ├── comparison/                # Engine comparison framework
│   ├── risk/                      # Scenarios, stress tests, VaR, P&L explain
│   └── jobs/                      # Async job execution (submit → poll → retrieve)
│
├── registry/                      # Plugin-style instrument/engine registry
│   ├── __init__.py                # Generic Registry class
│   └── bootstrap.py               # Registers all instruments, engines, models
│
├── api/                           # FastAPI backend
│   ├── app.py                     # Entry point
│   └── v1/
│       ├── schemas.py             # Pydantic request/response models
│       ├── helpers.py             # Instrument/environment builders
│       └── endpoints/             # 10 endpoint groups, 30+ routes
│
├── frontend/dash/                 # Dash frontend
│   ├── app.py                     # Multi-page Dash app
│   ├── assets/theme.css           # Dark terminal theme
│   ├── services/api_client.py     # Typed API client
│   ├── components/components.py   # Reusable UI components
│   ├── pages/                     # 6 pages
│   └── callbacks/                 # Callback modules per page
│
└── tests/                         # Regression + integration tests
```

## Tech Stack

| Layer | Technology |
|---|---|
| Pricing Engine | QuantLib (C++ via SWIG) |
| Language | Python 3.11 |
| Backend | FastAPI + Uvicorn |
| Frontend | Dash + Plotly + dash-bootstrap-components |
| Validation | Pydantic v2 |
| Environment | Conda |

## Instruments

| Type | Engines | Models |
|---|---|---|
| **Vanilla Option** | Analytic, FD, Binomial, MC, Heston | BSM, Heston |
| **Barrier Option** | Analytic, FD, MC | BSM |
| **Digital Option** | Analytic, FD | BSM |
| **Asian Option** | MC | BSM |
| **Lookback Option** | MC | BSM |

Engine compatibility is registry-driven — adding a new instrument requires zero API or frontend changes.

## Pricing Engines

| Engine | Method | Speed | Accuracy |
|---|---|---|---|
| `analytic` | Closed-form BSM | <5ms | Reference |
| `finite_difference` | Crank-Nicolson PDE | ~10ms | <1bps |
| `binomial` | CRR tree | ~5ms | <5bps |
| `monte_carlo` | GBM simulation | 1-30s | Depends on paths |
| `heston_analytic` | Semi-analytic Heston | ~20ms | Reference (Heston) |
| `fd_heston` | ADI PDE solver | ~50ms | <2bps |

## Risk Analytics

- **Greeks**: Delta, Gamma, Vega, Theta, Rho (bump-and-reprice)
- **Spot/Vol Ladders**: Configurable bump sizes
- **Spot x Vol Matrix**: 2D sensitivity heatmap
- **12 Predefined Scenarios**: Market crash, vol spike, rate shock, etc.
- **Custom Scenarios**: Arbitrary spot/vol/rate shocks
- **Stress Testing**: All scenarios with worst/best identification
- **P&L Explain**: Taylor expansion decomposition
- **VaR**: Parametric, Historical, Monte Carlo

## Frontend Pages

| Page | Features |
|---|---|
| **Dashboard** | System health, quick pricer, navigation |
| **Pricer** | Any instrument, dynamic form, MC/FD params, Greeks, engine comparison |
| **Risk Lab** | Spot/vol ladders with charts, stress test table, custom scenarios |
| **Portfolio** | Build trade books, aggregated NPV + Greeks, portfolio stress test |
| **Market Tools** | 3D vol surface (SVI), yield curve charts, implied vol solver |
| **Registry** | Engine compatibility matrix, instruments, scenarios |

## Setup

### Prerequisites

- Conda (Miniconda or Anaconda)
- Python 3.11
- QuantLib-Python

### Installation

```bash
git clone <repo>
cd quantlib-pricing
conda create -n quantlib-pricing python=3.11
conda activate quantlib-pricing

# QuantLib
conda install -c conda-forge quantlib-python

# Backend
pip install fastapi uvicorn pydantic scipy numpy

# Frontend
pip install dash dash-bootstrap-components requests plotly
```

### Running

**Terminal 1 — Backend:**
```bash
cd quantlib-pricing
uvicorn api.app:app --reload --port 8000
```

**Terminal 2 — Frontend:**
```bash
cd frontend/dash
python app.py
```

Open: http://localhost:8050

Swagger docs: http://localhost:8000/docs

### Integration Tests

```bash
cd frontend/dash
python test_integration.py
```

Runs 28 tests across all endpoints. Requires backend on port 8000.

## API Endpoints

| Group | Endpoints | Description |
|---|---|---|
| System | `GET /health` | Health check |
| Pricing | `POST /api/v1/pricing/single, /batch, /compare` | Price instruments |
| Sensitivities | `POST /api/v1/sensitivities/greeks, /ladder, /matrix` | Greeks and ladders |
| Risk | `POST /api/v1/risk/scenario, /stress-test, /pnl-explain, /var` | Risk analytics |
| Calibration | `POST /api/v1/calibration/model, /implied-vol` | Model calibration |
| Market Data | `POST /api/v1/market/vol-surface/*, /yield-curve/*` | Market tools |
| Registry | `GET /api/v1/registry/instruments, /engines, /compatibility` | Browse registry |
| Portfolio | `POST /api/v1/portfolio/create, /value, /scenario` | Portfolio mgmt |
| Jobs | `POST /api/v1/jobs/submit`, `GET /status, /result` | Async execution |
| Snapshots | `POST /api/v1/snapshots/save`, `GET /list, /verify` | Market data versioning |

## Design Principles

1. **Instrument-agnostic API**: `{"type": "vanilla_option", "params": {...}}` — works for any registered type
2. **Registry-driven dispatch**: Adding a new product = register it. Zero code changes elsewhere.
3. **Risk factor as string key**: `"spot"`, `"vol"`, `"rate"` — extensible to any asset class
4. **Model as string key**: `"black_scholes"`, `"heston"` — pluggable
5. **Versioned API**: `/api/v1/` prefix for evolution
6. **Market environment as first-class object**: Curves, surfaces, snapshots with checksums

## Integration Test Results

```
28/28 (100%)

Health 1/1 | Registry 5/5 | Pricing 8/8
Sensitivities 4/4 | Risk 4/4 | Calibration 1/1
Market Data 2/2 | E2E Flows 3/3
```
