"""Place Excel export files. Run from project root."""
import shutil, os

FILE_MAP = {
    "export_init.py":      "services/export/__init__.py",
    "excel_export.py":     "services/export/excel_export.py",
    "export_endpoint.py":  "api/v1/endpoints/export.py",
    "router.py":           "api/v1/router.py",
    "api_client.py":       "frontend/dash/services/api_client.py",
    "page_pricer.py":      "frontend/dash/pages/pricer.py",
    "cb_pricer.py":        "frontend/dash/callbacks/pricer_callbacks.py",
    "test_integration.py": "frontend/dash/test_integration.py",
}

SRC = "temp"
for src_name, dest in FILE_MAP.items():
    src = os.path.join(SRC, src_name)
    if not os.path.exists(src):
        print(f"  SKIP  {src_name}"); continue
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    shutil.copy2(src, dest)
    print(f"  OK    {src_name} -> {dest}")

print("\nDone. Restart backend and frontend.")
