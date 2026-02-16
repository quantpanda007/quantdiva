# CHANGELOG — QuantLib Pricing Platform

All notable changes, design decisions, and build progress documented here.
This serves as a **memory log** — every task Claude helps build is recorded.

---

## [0.2.0] — Options Pricing Module (IN PROGRESS)

### Plan
Build comprehensive options pricing covering European, American, and Bermudan
exercise types across multiple engines and models.

**Scope decided:**
- Instruments: Vanilla (Eur/Amer/Berm), Barriers, Digitals
- Models: BSM + Heston
- Engines: Analytic, Binomial/Trinomial trees, Finite Difference, Monte Carlo
- MC Output: Full path storage — random numbers, spot paths, intrinsic values,
  exercise decisions, all saved to Parquet with CSV export option
- Engine comparison utility: Yes, for cross-validation

**MC Storage Design:**
- Configurable: in-memory (small), disk (medium), streaming (large)
- Parquet as primary format, CSV export available
- Stores: random numbers (T×N), spot paths (T+1×N), intrinsic values,
  exercise boundaries (Longstaff-Schwartz), cashflows, summary stats

### Build Order
1. [x] `instruments/common/payoffs.py` — PayoffBuilder factory (PlainVanilla, CashOrNothing, AssetOrNothing, SuperShare, Gap)
2. [x] `instruments/common/exercise.py` — ExerciseBuilder factory (European, American, Bermudan with schedule support)
3. [x] `instruments/equity/vanilla_option.py` — Unified Eur/Amer/Berm VanillaOption with validation & serialization
4. [x] `engines/analytic/bsm_engine.py` — AnalyticEuropeanEngine (BSM) + AnalyticHestonEngine
5. [x] `engines/lattice/binomial_engine.py` — BinomialEngine (CRR/JR/Tian/LR/Joshi4) for all exercise types
6. [x] `engines/finite_difference/fd_vanilla_engine.py` — FDVanillaEngine (BSM) + FDHestonVanillaEngine
7. [x] `engines/monte_carlo/mc_vanilla_engine.py` — MCEuropeanEngine + MCAmericanEngine (Longstaff-Schwartz)
   - Full MCResult container with path storage (random numbers, spot paths, intrinsic values)
   - Parquet and CSV export
   - LS backward pass with continuation values, exercise flags, exercise boundary
   - **v2 AUDIT FIXES applied:**
     - T derived from instrument expiry, not hardcoded to 1.0
     - Market data (rate, div, vol) extracted at correct T and strike
     - Heston diagnostics use proper Euler discretization, not GBM
     - Intrinsic values and NPV computed automatically inside engine flow
     - LS backward pass fully vectorized (no O(N²) loops)
     - MCResult wired into PricingService → PricingResult.diagnostics
     - Discount factors computed from actual curve at each time step
   - Split into 4 clean modules:
     - `mc_result.py`: MCResult container + Parquet/CSV/load
     - `mc_simulation.py`: GBM + Heston path generation + market data extraction
     - `longstaff_schwartz.py`: Vectorized LS regression
     - `mc_vanilla_engine.py`: Engine classes wiring everything together
8. [x] **Round 2 — MC Enhancements:**
   - `engines/monte_carlo/rng.py` — RNG framework:
     - PseudoRandomGenerator (Mersenne Twister)
     - SobolGenerator (quasi-random, scrambled, O(1/N) convergence)
     - HaltonGenerator (simpler quasi-random)
     - `create_rng()` factory, `apply_antithetic()` helper
   - `engines/monte_carlo/variance_reduction.py`:
     - Control variate using analytic BSM (β-optimal, reports variance ratio)
     - Moment matching (adjusts paths so E[S(T)] = forward)
     - `apply_all_variance_reduction()` combined pipeline
   - `engines/monte_carlo/mc_greeks.py`:
     - Pathwise delta (tangent method, exact for smooth payoffs)
     - Pathwise gamma (Broadie-Glasserman smoothing with Gaussian kernel)
     - Likelihood ratio vega (score function method, works for all payoffs)
     - Likelihood ratio rho
     - FD theta (finite difference on T)
     - MCGreeksResult container with std errors
   - Updated `mc_simulation.py`: accepts pre-generated Z from any RNG
   - Updated `mc_vanilla_engine.py`: new flags `rng_type`, `use_control_variate`,
     `use_moment_matching`, `compute_mc_greeks` — all wired into diagnostics
9. [x] **Round 3 — FD Improvements:**
   - `engines/finite_difference/fd_config.py` — FDGridConfig:
     - Scheme selection: Crank-Nicolson, Douglas, Craig-Sneyd, Hundsdorfer-Verwer,
       Modified Craig-Sneyd, Implicit Euler, Explicit Euler
     - Configurable spot grid bounds (spot_min_factor, spot_max_factor)
     - Damping steps for short-maturity / discontinuous payoffs
     - Performance safeguards: max_total_nodes, warn_threshold
     - Runtime estimation: estimate_runtime_ms()
     - Presets: FAST_GRID, STANDARD_GRID, FINE_GRID, BENCHMARK_GRID,
       SHORT_MATURITY_GRID, HESTON_GRID
   - `engines/finite_difference/fd_dividends.py`:
     - DividendSchedule: cash + proportional dividends
     - DividendEntry with QuantLib date conversion
     - build_dividend_option() for DividendVanillaOption
     - compute_escrowed_spot() (alternative simple approach)
   - `engines/finite_difference/fd_result.py`:
     - FDResult diagnostics: grid info, Greeks, convergence data
     - ConvergencePoint for convergence study results
     - Export to JSON and CSV
   - `engines/finite_difference/fd_vanilla_engine.py` — rewritten:
     - FDVanillaEngine: grid validation, convergence study, Greek extraction
     - FDHestonVanillaEngine: 2D PDE with Douglas scheme default
     - FDDividendEngine: discrete dividends via DividendVanillaOption
     - All engines produce FDResult diagnostics
   - Updated PricingService: FD diagnostics (scheme, grid, Greeks, convergence)
     wired into PricingResult.diagnostics
10. [ ] `models/equity/heston.py` — Heston SV + analytic engine + calibration
11. [ ] `services/calibration/implied_vol_solver.py` — implied vol
10. [ ] Barrier + Digital instruments and engines
11. [ ] Engine comparison / benchmarking utility
12. [ ] Regression tests for all of the above

---

## [0.1.0] — 2025-XX-XX — Initial Scaffold

### Added
- **Project structure**: 117 directories, full package hierarchy with `__init__.py`
- **Core layer** (`core/`):
  - Value objects: `Money`, `PricingDate`, `Tenor`, `Quote`, `Rate`, `TradeId`,
    `PricingResult`, `RiskResult`
  - 30+ enums: `AssetClass`, `Currency`, `InstrumentType`, `EngineType`,
    `ModelType`, `OptionType`, `ExerciseType`, `RiskMeasure`, `ScenarioType`, etc.
  - Abstract interfaces: `BaseInstrument`, `BaseModel`, `BaseEngine`, `BaseCurve`,
    `BaseVolSurface`, `BasePricer`, `BaseCalibrator`, `BaseRepository`
  - `MarketEnvironment` — unified container for all market data
  - Exception hierarchy: 15+ domain-specific exceptions organized by subsystem

- **Registry** (`registry/`):
  - Generic `Registry[T]` class with decorator registration
  - Singleton registries: `instrument_registry`, `engine_registry`, `model_registry`,
    `pricer_config_registry`, `curve_registry`, `calibrator_registry`
  - `PricerConfig` — maps instrument type → default model + engine
  - `auto_discover_modules()` — imports modules to trigger registration

- **Instruments** (`instruments/`):
  - `VanillaOption` — European/American equity option (equity)
  - `BarrierOption` — Up/Down × In/Out barriers (equity)
  - `InterestRateSwap` — Fixed vs Float IRS (rates)
  - `FXVanillaOption` — Garman-Kohlhagen FX option (fx)
  - `FXForward` — FX forward (fx)

- **Models** (`models/`):
  - `BlackScholesModel` — builds `GeneralizedBlackScholesProcess`
  - `HestonModel` — builds `HestonProcess` with Feller condition check
    and Levenberg-Marquardt calibration

- **Engines** (`engines/`):
  - `AnalyticBSMEngine` — closed-form European BSM
  - `AnalyticHestonEngine` — semi-closed-form Heston
  - `AnalyticBarrierEngine` — closed-form barrier under BSM
  - `MCBSMEngine` — Monte Carlo under BSM/Heston

- **Market Data** (`market/`):
  - `YieldCurveBuilder` — bootstraps from deposit + swap rates
  - `build_flat_curve()`, `build_flat_vol()` — testing helpers
  - `build_test_market_env()` — quick market env for notebooks
  - `build_usd_curve()` — USD curve from market data
  - `VolSurfaceBuilder` — grid-based Black variance surface
  - `SABRParams` + `calibrate_sabr()` — SABR smile fitting
  - `SVIParams` — SVI total variance parameterization

- **Services** (`services/`):
  - `PricingService` — full dispatch: instrument + model + engine → NPV
    - Automatic config lookup from `pricer_config_registry`
    - Batch pricing with error isolation
    - Analytic Greeks extraction with FD fallback
  - `RiskService` — bump-and-reprice Greeks (central FD)
    - Delta, Gamma, Vega, Theta, Rho, DV01
    - Scenario analysis: spot bumps, vol bumps, rate shifts
    - Standard scenario generator (±10%, ±25% spot, ±5vol, ±50bp/100bp rates)

- **API** (`api/fastapi/`):
  - FastAPI app with CORS, auto-discovery, startup logging
  - Routes: `POST /price`, `POST /price/batch`, `POST /greeks`,
    `GET /health`, `GET /registry/*`
  - Pydantic request/response schemas

- **Frontend** (`frontend/streamlit/`):
  - 4-tab dashboard: Single Price, Strike Ladder, Greeks, Scenarios
  - Plotly charts for ladder and scenario bar charts
  - Configurable market data sidebar

- **Tests** (`tests/`):
  - Regression suite: ATM/ITM/OTM call/put, put-call parity, batch monotonicity
  - Test fixtures for market env and pricing service

- **DevOps**:
  - `pyproject.toml` — full project metadata, dependencies, tool config
  - `Makefile` — 14 common commands
  - `Dockerfile` + `docker-compose.yml` — API + Streamlit + Redis + Postgres
  - `sync_files.py` — auto-place downloaded files into project structure
  - `DEV_GUIDE.md` — daily workflow, commands, conventions

### Design Decisions
1. **Registry pattern over factory pattern**: Chose registries for extensibility.
   New instruments/engines just decorate themselves and they're available everywhere.
2. **MarketEnvironment as single container**: One object holds all curves, surfaces,
   spots, fixings. Passed everywhere. Simple to bump for risk scenarios.
3. **Central dispatch in PricingService**: Instrument type → looks up default
   model + engine from config. Can always override explicitly.
4. **Bump-and-reprice for Greeks**: Works for any engine. Analytic Greeks used
   where available as optimization.
5. **QuantLib wiring**: instrument.build() → ql.Instrument, model.build_process() →
   ql.Process, engine.build() → ql.PricingEngine. Clean separation.

### Known Issues / TODO
- FXForward.build() uses VanillaOption as placeholder — needs proper forward pricing
- Rate bumping in RiskService rebuilds flat curves — should bump actual bootstrapped curves
- No persistence layer yet (repositories are interfaces only)
- gRPC servicers not implemented
- Missing `__init__.py` re-exports in most subpackages

---

## How to Read This Log

Each entry includes:
- **What was built** — files and classes
- **Design decisions** — why we chose this approach
- **Known issues** — what's incomplete or needs revisiting
- **Build order** — what comes next

When picking up work after a break, read the latest entry to remember where we left off.
