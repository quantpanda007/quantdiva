# QuantPricer

**Multi-asset derivatives pricing platform built on QuantLib, with FastAPI backend and Dash frontend.**

Covers **13 instruments** across **4 asset classes** (Equity, Rates, Credit, FX), with multiple pricing engines, bump-and-reprice risk analytics, and an interactive dark-themed dashboard.

---

## Architecture

```
quantlib-pricing/
├── core/                          # Domain layer
│   ├── enums/                     # InstrumentType, AssetClass, EngineType, etc.
│   ├── interfaces/                # BaseInstrument, BaseEngine, MarketEnvironment
│   ├── types/                     # Value objects (PricingDate, TradeId, etc.)
│   └── exceptions/                # Typed exceptions
│
├── instruments/                   # Instrument wrappers
│   ├── equity/                    # Vanilla, Barrier, Digital, Asian, Lookback
│   ├── rates/                     # IRS, Bond, FRA, Cap/Floor, Swaption
│   ├── credit/                    # CDS
│   └── fx/                        # FX Forward, FX Option
│
├── engines/                       # Pricing engines
│   ├── analytic/                  # BSM, Barrier/Digital, Asian, Lookback,
│   │                              #   Rates (Discounting, Black), Credit, FX (GK)
│   ├── finite_difference/         # Crank-Nicolson PDE
│   ├── lattice/                   # CRR Binomial tree
│   └── monte_carlo/               # GBM simulation, variance reduction
│
├── models/                        # Stochastic models
│   └── equity/                    # Black-Scholes, Heston
│
├── services/                      # Application services
│   ├── pricers/                   # PricingService (dispatch + execution)
│   ├── greeks/                    # Bump-and-reprice Greeks + DV01/Duration
│   ├── risk/                      # Scenarios, stress tests, VaR, P&L explain
│   ├── calibration/               # Heston calibration, implied vol solver
│   ├── comparison/                # Engine comparison framework
│   └── jobs/                      # Async job execution
│
├── market/                        # Market data layer
│   ├── volatility/                # SVI vol surface, local vol
│   └── snapshots/                 # Market data versioning + checksums
│
├── registry/                      # Plugin-style dispatch
│   ├── __init__.py                # Generic Registry class
│   └── bootstrap.py               # Auto-registers all instruments/engines/models
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
└── tests/                         # 36 integration tests
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

### Equity Derivatives

| Instrument | QuantLib Class | Engines | Models |
|---|---|---|---|
| **Vanilla Option** | `VanillaOption` | Analytic, FD, Binomial, MC, Heston | BSM, Heston |
| **Barrier Option** | `BarrierOption` | Analytic, FD, MC | BSM |
| **Digital Option** | `VanillaOption` (CashOrNothing) | Analytic, FD | BSM |
| **Asian Option** | `DiscreteAveragingAsianOption` | MC | BSM |
| **Lookback Option** | `ContinuousFloatingLookbackOption` | MC | BSM |

### Rates

| Instrument | QuantLib Class | Engine | Description |
|---|---|---|---|
| **Interest Rate Swap** | `VanillaSwap` | DiscountingSwapEngine | Fixed vs float, pay/receive |
| **Fixed Rate Bond** | `FixedRateBond` | DiscountingBondEngine | Coupon bond valuation |
| **FRA** | `VanillaSwap` (single-period) | DiscountingSwapEngine | Forward rate agreement |
| **Cap / Floor** | `Cap`, `Floor` | BlackCapFloorEngine | Interest rate caps and floors |
| **Swaption** | `Swaption` | BlackSwaptionEngine | European payer/receiver swaption |

### Credit

| Instrument | QuantLib Class | Engine | Description |
|---|---|---|---|
| **CDS** | `CreditDefaultSwap` | MidPointCdsEngine | Buy/sell protection, flat hazard curve |

### FX

| Instrument | QuantLib Class | Engine | Description |
|---|---|---|---|
| **FX Forward** | `VanillaOption` | Garman-Kohlhagen (BSM) | Forward exchange agreement |
| **FX Option** | `VanillaOption` | Garman-Kohlhagen (BSM) | European call/put on FX rate |

Engine compatibility is registry-driven — adding a new instrument requires zero API or frontend changes.

## Pricing Engines

| Engine | Method | Speed | Instruments |
|---|---|---|---|
| `analytic` | Closed-form BSM / Black | <5ms | All 13 instruments |
| `finite_difference` | Crank-Nicolson PDE | ~10ms | Vanilla, Barrier |
| `binomial` | CRR tree | ~5ms | Vanilla |
| `monte_carlo` | GBM simulation | 1-30s | Vanilla, Barrier, Asian, Lookback |
| `heston_analytic` | Semi-analytic Heston | ~20ms | Vanilla |
| `discounting` | Curve discounting | <5ms | IRS, Bond, FRA |
| `black` | Black's formula | <5ms | Cap/Floor, Swaption |
| `midpoint` | Default probability integration | <5ms | CDS |
| `garman_kohlhagen` | BSM + foreign rate | <5ms | FX Forward, FX Option |

## Risk Analytics

### Equity Greeks
Delta, Gamma, Vega, Theta, Rho — computed via bump-and-reprice (central difference).

### Rates Sensitivities
DV01, Modified Duration, Convexity — automatically computed for IRS, Bond, FRA, Cap/Floor, Swaption, CDS.

### Scenario Analysis
- 12 predefined scenarios (market crash, vol spike, rate shock, etc.)
- Custom scenarios with arbitrary spot/vol/rate shocks
- Stress testing with worst/best identification
- P&L explain via Taylor expansion decomposition
- VaR: Parametric, Historical, Monte Carlo

## Frontend Pages

| Page | Features |
|---|---|
| **Dashboard** | System health, quick pricer, navigation |
| **Pricer** | All 13 instruments, adaptive market data panel (equity/rates/FX), Greeks, engine comparison |
| **Risk Lab** | Spot/vol ladders with charts, stress test table, custom scenarios |
| **Portfolio** | Multi-asset trade books with asset class badges, aggregated NPV + Greeks, stress test |
| **Market Tools** | 3D vol surface (SVI), yield curve charts, implied vol solver |
| **Registry** | Engine compatibility matrix, registered instruments, scenarios |

The UI automatically adapts based on instrument type:
- **Equity options**: Spot, Vol, Div Yield market data panel
- **Rates/Credit**: Discount Rate only (curves built internally)
- **FX**: FX Spot Rate (domestic/foreign rates in instrument form)

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

Runs 36 tests across all endpoints. Requires backend on port 8000.

## API Endpoints

| Group | Endpoints | Description |
|---|---|---|
| System | `GET /health` | Health check |
| Pricing | `POST /api/v1/pricing/single, /batch, /compare` | Price any instrument |
| Sensitivities | `POST /api/v1/sensitivities/greeks, /ladder, /matrix` | Greeks, DV01, Duration |
| Risk | `POST /api/v1/risk/scenario, /stress-test, /pnl-explain, /var` | Risk analytics |
| Calibration | `POST /api/v1/calibration/model, /implied-vol` | Model calibration |
| Market Data | `POST /api/v1/market/vol-surface/*, /yield-curve/*` | Market tools |
| Registry | `GET /api/v1/registry/instruments, /engines, /compatibility` | Browse registry |
| Portfolio | `POST /api/v1/portfolio/create, /value, /scenario` | Portfolio mgmt |
| Jobs | `POST /api/v1/jobs/submit`, `GET /status, /result` | Async execution |
| Snapshots | `POST /api/v1/snapshots/save`, `GET /list, /verify` | Market data versioning |

## Design Principles

1. **Multi-asset from the ground up**: Same API handles equity options, rate swaps, CDS, and FX — `{"type": "cds", "params": {...}}`
2. **Registry-driven dispatch**: Adding a new product = instrument class + engine + `@register_decorator`. Zero changes to API or frontend.
3. **Instrument-aware risk**: Equity gets Delta/Gamma/Vega; rates get DV01/Duration/Convexity — automatic detection.
4. **Adaptive UI**: Market data panel, Greeks display, and position cards all adapt to the instrument type.
5. **Versioned API**: `/api/v1/` prefix for backward-compatible evolution.
6. **Market environment as first-class object**: Discount curves, vol surfaces, hazard curves, forecast curves — all in `MarketEnvironment`.

## Integration Test Results

```
36/36 (100%)

Health 1/1 | Registry 5/5 | Pricing 13/13
Sensitivities 4/4 | Risk 4/4 | Calibration 1/1
Market Data 2/2 | E2E Flows 6/6
```