# Developer Guide — QuantLib Pricing Platform

## Your Daily Workflow

### Step 1: Setup (One-Time)

```bash
# After downloading the zip, extract it
cd ~/Projects  # or wherever you keep code
unzip quantlib-pricing.zip
cd quantlib-pricing

# Create the staging folder for file sync
mkdir -p ~/Downloads/quantlib-staging

# Install dependencies
pip install -e ".[dev]"

# Verify setup
python -c "import QuantLib; print(f'QuantLib {QuantLib.__version__} OK')"
```

### Step 2: Receiving Files from Claude

When I give you a new file, I'll always say something like:

> **File: `engines/lattice/binomial_engine.py`**

You have **4 options** to add it to your project:

---

#### Option A: Encoded Filename (Recommended for multiple files)

1. Save the file as: `engines__lattice__binomial_engine.py`
   - Replace `/` with `__` (double underscore)
2. Drop it in `~/Downloads/quantlib-staging/`
3. Run the sync script:

```bash
python sync_files.py
```

The script will:
- Decode the path: `engines__lattice__binomial_engine.py` → `engines/lattice/binomial_engine.py`
- Create directories if missing
- Ensure `__init__.py` exists in every directory
- Back up any existing file
- Move the processed file to `quantlib-staging/done/`

---

#### Option B: Explicit Copy (Quick for single files)

```bash
python sync_files.py --src ~/Downloads/binomial_engine.py --dst engines/lattice/binomial_engine.py
```

---

#### Option C: Interactive Mode (When unsure about placement)

```bash
python sync_files.py --interactive
```

Shows each file and asks you to confirm/modify the destination.

---

#### Option D: Manual (Old school, but always works)

```bash
# Create directory if needed
mkdir -p engines/lattice

# Copy the file
cp ~/Downloads/binomial_engine.py engines/lattice/binomial_engine.py
```

---

### Step 3: Verify After Adding Files

```bash
# Quick check: does Python find the module?
python -c "from engines.lattice.binomial_engine import BinomialEngine; print('OK')"

# Run tests for that module
pytest tests/unit/test_engines/ -v

# Run all regression tests
pytest tests/regression/ -v -m regression
```

### Step 4: Quick Commands Reference

```bash
# --- DEVELOPMENT ---
make test                # Run all tests
make test-unit           # Unit tests only
make test-regression     # Regression tests only
make lint                # Check code style
make format              # Auto-format code
make serve               # Start API server (localhost:8000)
make streamlit           # Start dashboard (localhost:8501)

# --- SYNC ---
python sync_files.py                    # Process staging folder
python sync_files.py --dry-run          # Preview without copying
python sync_files.py -i                 # Interactive mode
python sync_files.py --src X --dst Y    # Explicit file placement

# --- QUICK PRICING TEST ---
python -c "
from market.curves.yield_curve import build_test_market_env
from instruments.equity.vanilla_option import VanillaOption
from core.enums.definitions import OptionType, ExerciseType
from services.pricers.pricing_service import PricingService
from datetime import date

env = build_test_market_env(spot=100, rate=0.05, vol=0.20, underlying='TEST')
opt = VanillaOption('T1', 'TEST', 100, date(2026,1,15), OptionType.CALL, ExerciseType.EUROPEAN)

import engines.analytic.equity_engines, models.equity.black_scholes
result = PricingService().price(opt, env)
print(f'NPV: {result.npv:.4f}')
"

# --- REGISTRY CHECK ---
python -c "
import instruments.equity.vanilla_option
import instruments.rates.interest_rate_swap
import instruments.fx.fx_instruments
import engines.analytic.equity_engines
import models.equity.black_scholes
from registry import instrument_registry, engine_registry, model_registry
print('Instruments:', instrument_registry.keys())
print('Engines:', engine_registry.keys())
print('Models:', model_registry.keys())
"

# --- VIEW SYNC LOG ---
cat .sync_log.txt

# --- VIEW CHANGELOG ---
cat CHANGELOG.md
```

## Project Conventions

### File Naming
- All Python files: `snake_case.py`
- All classes: `PascalCase`
- All module names: `snake_case`
- Test files: `test_<module_name>.py`

### Registration Pattern
Every instrument, engine, and model must register itself:

```python
from registry import instrument_registry

@instrument_registry.register_decorator("vanilla_option")
class VanillaOption(BaseInstrument):
    ...
```

### Import Pattern
```python
# Good: import from the package
from core.enums.definitions import OptionType
from core.interfaces.base import BaseInstrument, MarketEnvironment
from registry import instrument_registry

# Bad: relative imports across packages
from ..core.enums import OptionType  # Don't do this
```

### Testing
Every new instrument/engine/model needs:
1. **Unit test** in `tests/unit/test_<category>/`
2. **Regression test** with known-good values in `tests/regression/`
3. Registration check: `assert "my_instrument" in instrument_registry`
