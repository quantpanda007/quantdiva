# QuantLib Pricing Platform

A full-stack quantitative finance pricing, risk, and portfolio management platform built on QuantLib.

## Architecture Overview

```
quantlib-pricing/
│
├── core/                       # Shared domain primitives
│   ├── types/                  #   Value objects: Money, Rate, Quote, Tenor, etc.
│   ├── exceptions/             #   Domain-specific exceptions
│   ├── enums/                  #   TradeType, AssetClass, Currency, DayCount, etc.
│   ├── interfaces/             #   ABCs: BaseInstrument, BaseEngine, BaseModel, BaseCurve
│   ├── versioning/             #   Model/trade versioning & audit trail
│   └── config/                 #   Global configuration management
│
├── instruments/                # QuantLib instrument wrappers (the "what")
│   ├── common/                 #   Base instrument, payoff builders, exercise builders
│   ├── equity/                 #   VanillaOption, BarrierOption, AsianOption, etc.
│   ├── fx/                     #   FXForward, FXOption, FXSwap, etc.
│   ├── rates/                  #   IRS, CCS, Swaption, Cap/Floor, Bond, FRA, etc.
│   ├── credit/                 #   CDS, CDO, CLN, etc.
│   ├── inflation/              #   InflationSwap, ZCInflationSwap, YoYSwap, etc.
│   └── commodity/              #   CommodityForward, CommodityOption, etc.
│
├── engines/                    # Pricing engine wrappers (the "how")
│   ├── analytic/               #   BSM, Heston analytic, Hull-White analytic, etc.
│   ├── lattice/                #   Binomial, Trinomial trees
│   ├── finite_difference/      #   FD schemes for PDE-based pricing
│   ├── monte_carlo/            #   MC engines, path generators, variance reduction
│   └── integral/               #   Numerical integration engines
│
├── models/                     # Stochastic models & processes (the "assumptions")
│   ├── common/                 #   Base model, process builders
│   ├── equity/                 #   BSM, Heston, LocalVol, SABR, SLV
│   ├── rates/                  #   HullWhite, G2++, LGM, LIBOR Market Model
│   ├── credit/                 #   Hazard rate models, structural models
│   └── fx/                     #   Garman-Kohlhagen, mixed models
│
├── market/                     # Market data construction & management
│   ├── curves/                 #   YieldCurve, DiscountCurve, ForwardCurve, BasisCurve
│   ├── volatility/             #   VolSurface, SmileSection, SABR, SVI fits
│   ├── correlation/            #   Correlation matrices, copulas
│   ├── fixings/                #   Historical fixings management
│   ├── conventions/            #   Market conventions per currency/product
│   ├── bootstrapping/          #   Curve & surface bootstrappers
│   └── scenarios/              #   Stress tests, bumped curves, scenario generation
│
├── numerics/                   # Low-level numerical utilities
│   ├── interpolation/          #   Linear, cubic, log-linear, monotone convex
│   ├── optimization/           #   Levenberg-Marquardt, Simplex, DE
│   ├── random/                 #   RNG, Sobol, low-discrepancy sequences
│   ├── integration/            #   Gauss quadrature, adaptive integration
│   └── solvers/                #   Brent, Newton, bisection
│
├── services/                   # Domain services (business logic orchestration)
│   ├── pricers/                #   PricerService: wires instrument + engine + model
│   ├── calibration/            #   Model calibration to market data
│   ├── risk/                   #   Greeks, VaR, scenario analysis, PFE
│   ├── portfolio/              #   Portfolio aggregation, netting, attribution
│   ├── xva/                    #   CVA, DVA, FVA, MVA, KVA
│   ├── dispatch/               #   Route pricing requests to correct pricer
│   └── scheduling/             #   Async jobs, batch runs, EOD processing
│
├── registry/                   # Central registries for plugin-style architecture
│   ├── instrument_registry.py  #   Register & lookup instrument builders
│   ├── engine_registry.py      #   Register & lookup pricing engines
│   ├── model_registry.py       #   Register & lookup stochastic models
│   ├── pricer_registry.py      #   Register & lookup pricer configurations
│   └── curve_registry.py       #   Register & lookup curve builders
│
├── workflows/                  # High-level orchestration (use cases)
│   ├── pricing/                #   Single trade & batch pricing workflows
│   ├── market_build/           #   End-of-day market data build pipeline
│   ├── risk/                   #   Risk report generation workflows
│   ├── batch/                  #   Batch processing orchestration
│   └── lifecycle/              #   Trade lifecycle events (novation, amendment, etc.)
│
├── data/                       # Data access layer
│   ├── loaders/                #   File, DB, API data loaders
│   ├── repositories/           #   Repository pattern for domain objects
│   ├── market_store/           #   Market data persistence
│   ├── trade_store/            #   Trade persistence
│   ├── cache/                  #   Redis/in-memory caching layer
│   └── schemas/                #   DB schemas, migrations (Alembic)
│
├── api/                        # External API layer
│   ├── fastapi/                #   REST API
│   │   ├── routes/             #     /price, /risk, /market, /portfolio, /trades
│   │   ├── schemas/            #     Pydantic request/response models
│   │   ├── dependencies/       #     DI for services, auth, DB sessions
│   │   └── middleware/         #     Logging, CORS, rate limiting, error handling
│   └── grpc/                   #   gRPC for low-latency internal services
│       ├── protos/             #     .proto definitions
│       ├── generated/          #     Auto-generated stubs
│       └── servicers/          #     gRPC service implementations
│
├── frontend/                   # UI layer (multiple options)
│   ├── streamlit/              #   Rapid prototyping / internal tools
│   │   ├── pages/              #     Multi-page Streamlit app
│   │   └── components/         #     Custom Streamlit components
│   ├── dash/                   #   Plotly Dash for rich analytics dashboards
│   │   ├── pages/
│   │   └── components/
│   ├── react/                  #   Production React frontend
│   └── shared_components/      #   Shared UI logic across frameworks
│
├── reporting/                  # Report generation
│   ├── pnl/                    #   P&L reports, attribution
│   ├── risk/                   #   Risk reports, VaR, Greeks summaries
│   ├── regulatory/             #   Regulatory reporting (FRTB, SA-CCR, etc.)
│   └── templates/              #   Report templates (Jinja2, etc.)
│
├── infra/                      # Infrastructure concerns
│   ├── logging/                #   Structured logging configuration
│   ├── monitoring/             #   Prometheus metrics, health checks
│   ├── messaging/              #   Kafka/RabbitMQ for event-driven updates
│   └── security/               #   Auth, encryption, secrets management
│
├── configs/                    # Configuration files
│   ├── environments/           #   dev.yaml, staging.yaml, prod.yaml
│   ├── instruments/            #   Instrument-specific config templates
│   ├── models/                 #   Model parameter defaults
│   └── market/                 #   Curve definitions, vol surface configs
│
├── tests/                      # Test suite
│   ├── unit/                   #   Unit tests per module
│   │   ├── test_instruments/
│   │   ├── test_engines/
│   │   ├── test_models/
│   │   ├── test_market/
│   │   ├── test_services/
│   │   └── test_workflows/
│   ├── integration/            #   Cross-module integration tests
│   ├── regression/             #   Known-good pricing regression tests
│   └── fixtures/               #   Shared test data & market snapshots
│
├── notebooks/                  # Jupyter notebooks for exploration
├── scripts/                    # CLI scripts (data loading, migrations, etc.)
├── docker/                     # Docker configurations
├── deployment/                 # Deployment configs
│   ├── kubernetes/
│   └── terraform/
├── docs/                       # Documentation
│   ├── architecture/           #   Architecture decision records (ADRs)
│   ├── api_docs/               #   API documentation
│   └── user_guides/            #   End-user documentation
│
├── pyproject.toml              # Project metadata & dependencies
├── Makefile                    # Common dev commands
├── docker-compose.yml          # Local dev environment
└── README.md                   # This file
```

## Design Principles

### 1. QuantLib Wiring Pattern
The core pricing pattern follows QuantLib's design:
```
Instrument + PricingEngine(Model(Process), MarketData) → Price + Greeks
```

This maps to our architecture as:
- **`instruments/`** → What we're pricing
- **`models/`** → What assumptions we're making (stochastic processes)
- **`engines/`** → How we compute the price (analytic, MC, PDE, tree)
- **`market/`** → What market data feeds into the model
- **`services/pricers/`** → Orchestrates all of the above

### 2. Registry Pattern
All instruments, engines, and models are registered in a central registry, enabling:
- Dynamic dispatch: `registry.get_pricer("vanilla_option", "analytic")`
- Configuration-driven pricing: YAML/JSON defines which engine/model to use
- Easy extensibility: add new instruments without touching existing code

### 3. Separation of Concerns
```
workflows/  →  "What business process are we running?"
services/   →  "What domain logic do we apply?"
engines/    →  "How do we compute?"
data/       →  "Where does data come from?"
api/        →  "How does the outside world talk to us?"
```

### 4. Market Data Pipeline
```
External Sources → data/loaders → market/bootstrapping → market/curves + market/volatility
                                                              ↓
                                    Cached in data/cache ← market_store
```

## Quick Start

```bash
# Clone and setup
git clone <repo-url> && cd quantlib-pricing
pip install -e ".[dev]"

# Run tests
make test

# Start API server
make serve

# Launch Streamlit dashboard
make streamlit

# Build market data
python -m scripts.build_market --env dev --date 2025-01-15
```

## Tech Stack
- **Pricing**: QuantLib (via QuantLib-Python / ORE)
- **API**: FastAPI + gRPC
- **Data**: PostgreSQL + Redis + Parquet
- **Frontend**: Streamlit (prototyping) / React (production)
- **Infra**: Docker + Kubernetes
- **Testing**: pytest + hypothesis (property-based testing)
