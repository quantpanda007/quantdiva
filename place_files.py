"""
Place downloaded files from temp/ folder to their correct locations.

Run from project root:
    cd C:\\Users\\Abhishek\\Quantdiva\\quantlib-pricing
    python place_files.py
"""

import shutil
import os

# Map: download filename -> destination path
FILE_MAP = {
    "README.md":            "README.md",
    "app.py":               "frontend/dash/app.py",
    "theme.css":            "frontend/dash/assets/theme.css",
    "api_client.py":        "frontend/dash/services/api_client.py",
    "components.py":        "frontend/dash/components/components.py",
    "page_dashboard.py":    "frontend/dash/pages/dashboard.py",
    "page_pricer.py":       "frontend/dash/pages/pricer.py",
    "page_registry.py":     "frontend/dash/pages/registry.py",
    "page_risk_lab.py":     "frontend/dash/pages/risk_lab.py",
    "page_portfolio.py":    "frontend/dash/pages/portfolio.py",
    "page_market_tools.py": "frontend/dash/pages/market_tools.py",
    "cb_dashboard.py":      "frontend/dash/callbacks/dashboard_callbacks.py",
    "cb_pricer.py":         "frontend/dash/callbacks/pricer_callbacks.py",
    "cb_registry.py":       "frontend/dash/callbacks/registry_callbacks.py",
    "cb_risk.py":           "frontend/dash/callbacks/risk_callbacks.py",
    "cb_portfolio.py":      "frontend/dash/callbacks/portfolio_callbacks.py",
    "cb_market.py":         "frontend/dash/callbacks/market_callbacks.py",
    "test_integration.py":  "frontend/dash/test_integration.py",
}

SRC_DIR = "temp"


def main():
    if not os.path.isdir(SRC_DIR):
        print(f"ERROR: '{SRC_DIR}' folder not found. Download files there first.")
        return

    placed = 0
    missing = 0

    for src_name, dest_path in FILE_MAP.items():
        src = os.path.join(SRC_DIR, src_name)
        if not os.path.exists(src):
            print(f"  SKIP  {src_name} (not in temp/)")
            missing += 1
            continue

        # Ensure destination directory exists
        os.makedirs(os.path.dirname(dest_path) if os.path.dirname(dest_path) else ".", exist_ok=True)

        shutil.copy2(src, dest_path)
        placed += 1
        print(f"  OK    {src_name} -> {dest_path}")

    print(f"\nDone: {placed} placed, {missing} skipped")


if __name__ == "__main__":
    main()