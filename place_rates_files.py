"""
Place IRS + Bond files. Run from project root:
    python place_rates_files.py
"""
import shutil, os

FILE_MAP = {
    # Backend - NEW files
    "fixed_rate_bond.py":     "instruments/rates/fixed_rate_bond.py",
    "rates_engines.py":       "engines/analytic/rates_engines.py",
    # Backend - UPDATED files
    "interest_rate_swap.py":  "instruments/rates/interest_rate_swap.py",
    "bootstrap.py":           "registry/bootstrap.py",
    "helpers.py":             "api/v1/helpers.py",
    # Frontend - UPDATED files
    "components.py":          "frontend/dash/components/components.py",
    "page_pricer.py":         "frontend/dash/pages/pricer.py",
    "page_risk_lab.py":       "frontend/dash/pages/risk_lab.py",
    "page_portfolio.py":      "frontend/dash/pages/portfolio.py",
    "test_integration.py":    "frontend/dash/test_integration.py",
}

SRC = "temp"

for src_name, dest in FILE_MAP.items():
    src = os.path.join(SRC, src_name)
    if not os.path.exists(src):
        print(f"  SKIP  {src_name}")
        continue
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    shutil.copy2(src, dest)
    print(f"  OK    {src_name} -> {dest}")

print("Done. Restart backend and frontend.")
