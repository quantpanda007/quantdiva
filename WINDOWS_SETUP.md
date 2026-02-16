# Windows Setup Guide — QuantLib Pricing Platform

## Step 1: Install Miniconda (if you don't have it)

Download from: https://docs.conda.io/en/latest/miniconda.html
Choose: **Miniconda3 Windows 64-bit**

After install, open **Anaconda Prompt** (not regular cmd/PowerShell).

## Step 2: Create Project Directory

```cmd
mkdir C:\Users\Abhishek\Quantdiva
mkdir C:\Users\Abhishek\Quantdiva\quantlib-staging
```

## Step 3: Extract the Zip

Extract `quantlib-pricing.zip` into `C:\Users\Abhishek\Quantdiva\` so you have:
```
C:\Users\Abhishek\Quantdiva\
├── quantlib-pricing\        ← project root
│   ├── core\
│   ├── instruments\
│   ├── engines\
│   ├── ...
│   ├── environment.yml
│   ├── sync_files.py
│   └── README.md
└── quantlib-staging\        ← drop files from Claude here
```

## Step 4: Create Conda Environment

```cmd
cd C:\Users\Abhishek\Quantdiva\quantlib-pricing
conda env create -f environment.yml
```

This will:
- Create environment named `quantlib-pricing`
- Install Python 3.11
- Install QuantLib-Python from conda-forge (pre-built, no compilation needed)
- Install all other dependencies

**If `environment.yml` fails** (sometimes conda solver is slow), use this manual approach:
```cmd
conda create -n quantlib-pricing python=3.11 -y
conda activate quantlib-pricing
conda install -c conda-forge quantlib-python numpy scipy pandas -y
pip install fastapi uvicorn pydantic httpx structlog pyyaml python-dotenv
pip install pytest pytest-cov hypothesis ruff mypy black
pip install streamlit plotly pyarrow
pip install grpcio grpcio-tools sqlalchemy alembic redis
```

## Step 5: Activate Environment

```cmd
conda activate quantlib-pricing
```

**You must do this every time you open a new terminal.**

To make it default in Anaconda Prompt, add to your `.condarc`:
```yaml
auto_activate_base: false
```

## Step 6: Verify Installation

```cmd
cd C:\Users\Abhishek\Quantdiva\quantlib-pricing

python -c "import QuantLib as ql; print(f'QuantLib {ql.__version__}')"
python -c "import numpy; print(f'NumPy {numpy.__version__}')"
python -c "import fastapi; print(f'FastAPI {fastapi.__version__}')"
python -c "from core.types.value_objects import PricingDate; print('Core imports OK')"
```

Expected output:
```
QuantLib 1.3x
NumPy 1.2x
FastAPI 0.10x
Core imports OK
```

## Step 7: Sync Workflow

When Claude gives you a file like `engines/lattice/binomial_engine.py`:

### Option A: Using the sync script
1. Download/save the file as `engines__lattice__binomial_engine.py`
2. Move it to `C:\Users\Abhishek\Quantdiva\quantlib-staging\`
3. Run:
```cmd
cd C:\Users\Abhishek\Quantdiva\quantlib-pricing
python sync_files.py
```

### Option B: Direct copy (PowerShell)
```powershell
# Single file
Copy-Item "$env:USERPROFILE\Downloads\binomial_engine.py" "C:\Users\Abhishek\Quantdiva\quantlib-pricing\engines\lattice\binomial_engine.py"

# Or use the explicit sync mode
python sync_files.py --src "$env:USERPROFILE\Downloads\binomial_engine.py" --dst "engines\lattice\binomial_engine.py"
```

### Option C: PowerShell shortcut function
Add this to your PowerShell profile (`$PROFILE`):
```powershell
function ql-sync {
    param([string]$src, [string]$dst)
    $project = "C:\Users\Abhishek\Quantdiva\quantlib-pricing"
    if ($dst) {
        python "$project\sync_files.py" --src $src --dst $dst
    } else {
        python "$project\sync_files.py"
    }
}

# Usage:
# ql-sync                                               # process staging folder
# ql-sync -src .\my_file.py -dst engines\analytic\x.py  # explicit
```

## Step 8: Running the Project

```cmd
conda activate quantlib-pricing
cd C:\Users\Abhishek\Quantdiva\quantlib-pricing

:: Run tests
pytest tests\ -v

:: Start API server
uvicorn api.fastapi.app:app --host 0.0.0.0 --port 8000 --reload

:: Start Streamlit (in another terminal)
streamlit run frontend\streamlit\app.py

:: Run a quick pricing test
python notebooks\01_quick_start.py
```

## Troubleshooting

### "QuantLib not found"
```cmd
conda install -c conda-forge quantlib-python
```

### "ModuleNotFoundError: No module named 'core'"
Make sure you're in the project root:
```cmd
cd C:\Users\Abhishek\Quantdiva\quantlib-pricing
set PYTHONPATH=.
python -c "from core import PricingDate"
```

Or install as editable package:
```cmd
pip install -e .
```

### "Solving environment takes forever"
Use `libmamba` solver:
```cmd
conda install -n base conda-libmamba-solver
conda config --set solver libmamba
conda env create -f environment.yml
```

### Conda vs pip conflicts
Always prefer conda for packages with C extensions (QuantLib, numpy, scipy).
Use pip only for pure-Python packages or those not on conda-forge.
