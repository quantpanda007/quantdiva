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

# Ensure project root on path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

import registry.bootstrap  # noqa: F401

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.v1.router import api_v1_router
from fastapi.middleware.cors import CORSMiddleware

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

# CORS — allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount versioned API
app.include_router(api_v1_router, prefix="/api/v1")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "version": "0.2.0"}


@app.get("/", tags=["system"])
def root():
    return {
        "name": "QuantLib Pricing Platform",
        "version": "0.2.0",
        "docs": "/docs",
        "api": "/api/v1",
    }