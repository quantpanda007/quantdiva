"""
QuantLib Pricing Platform — FastAPI Application.

Instrument-agnostic REST API for pricing, risk, and calibration.
All product logic is resolved through the registry — the API
never knows about specific instrument types.

Run:
    uvicorn api.app:app --reload --port 8000

Docs:
    http://localhost:8000/docs      (Swagger UI)
    http://localhost:8000/redoc     (ReDoc)
"""

from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure project root on path
# ---------------------------------------------------------------------------

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

import registry.bootstrap  # noqa: F401

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.v1.router import api_v1_router

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="QuantLib Pricing Platform",
    description=(
        "Instrument-agnostic pricing, risk, and calibration API. "
        "Supports any registered instrument type, model, and engine."
    ),
    version="0.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# CORS — allow all origins for development
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Mount versioned API
# ---------------------------------------------------------------------------

app.include_router(api_v1_router, prefix="/api/v1")

# ---------------------------------------------------------------------------
# Frontend — Serve Optima UI
# ---------------------------------------------------------------------------

frontend_path = project_root / "frontend"
templates_path = frontend_path / "static"

# Optional: serve static files if you later split CSS/JS into /frontend/static
if frontend_path.exists():
    app.mount(
        "/static",
        StaticFiles(directory=str(frontend_path/"static")),
        name="static",
    )

@app.get("/", include_in_schema=False)
def root():
    html_file = templates_path / "optima.html"
    if html_file.exists():
        return FileResponse(str(html_file))
    return {
        "error": "Optima UI not found",
        "expected_location": str(html_file)
    }

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "version": "0.2.0"}

# ---------------------------------------------------------------------------
# Scheduler — daily market data refresh
# ---------------------------------------------------------------------------

@app.on_event("startup")
def startup_scheduler():
    try:
        from market.historical.scheduler import start_scheduler
        start_scheduler()
    except Exception:
        pass

    # Warm up Ollama model in background
    try:
        import threading
        from services.report.report_service import warmup_ollama
        threading.Thread(target=warmup_ollama, daemon=True).start()
    except Exception:
        pass


@app.on_event("shutdown")
def shutdown_scheduler():
    try:
        from market.historical.scheduler import stop_scheduler
        stop_scheduler()
    except Exception:
        pass