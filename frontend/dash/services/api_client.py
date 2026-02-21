"""
Typed API client for the QuantLib Pricing Platform backend.

Centralizes all HTTP calls. Callbacks never call requests directly.

Usage:
    from services.api_client import api_client

    instruments = api_client.get_instruments()
    result = api_client.price_single(payload)
"""

from __future__ import annotations

import os
import logging
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000/api/v1")
TIMEOUT = 60


class APIError(Exception):
    """Backend returned an error."""
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"API {status_code}: {detail}")


class APIClient:
    """Typed client for the pricing platform API."""

    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _get(self, path: str, params: Dict = None) -> Any:
        try:
            r = self.session.get(self._url(path), params=params, timeout=TIMEOUT)
            if not r.ok:
                detail = r.json().get("detail", r.text) if r.text else r.reason
                raise APIError(r.status_code, detail)
            return r.json()
        except requests.ConnectionError:
            raise APIError(0, f"Cannot connect to backend at {self.base_url}")

    def _post(self, path: str, payload: Dict) -> Any:
        try:
            r = self.session.post(self._url(path), json=payload, timeout=TIMEOUT)
            if not r.ok:
                detail = r.json().get("detail", r.text) if r.text else r.reason
                raise APIError(r.status_code, detail)
            return r.json()
        except requests.ConnectionError:
            raise APIError(0, f"Cannot connect to backend at {self.base_url}")

    # ── Registry ──────────────────────────────────────────────────
    def get_instruments(self) -> List[Dict]:
        return self._get("/registry/instruments")

    def get_models(self) -> List[Dict]:
        return self._get("/registry/models")

    def get_engines(self) -> List[Dict]:
        return self._get("/registry/engines")

    def get_engine_compatibility(self) -> Dict[str, List[str]]:
        return self._get("/registry/engines/compatibility")

    def get_scenarios(self) -> List[Dict]:
        return self._get("/registry/scenarios")

    def get_instrument_schema(self, instrument_type: str) -> Dict:
        return self._get(f"/registry/schema/{instrument_type}")

    # ── Pricing ───────────────────────────────────────────────────
    def price_single(self, payload: Dict) -> Dict:
        return self._post("/pricing/single", payload)

    def price_batch(self, payload: Dict) -> Dict:
        return self._post("/pricing/batch", payload)

    def price_compare(self, payload: Dict) -> Dict:
        return self._post("/pricing/compare", payload)

    # ── Sensitivities ─────────────────────────────────────────────
    def compute_greeks(self, payload: Dict) -> Dict:
        return self._post("/sensitivities/greeks", payload)

    def run_ladder(self, payload: Dict) -> Dict:
        return self._post("/sensitivities/ladder", payload)

    def run_matrix(self, payload: Dict) -> Dict:
        return self._post("/sensitivities/matrix", payload)

    # ── Risk ──────────────────────────────────────────────────────
    def run_scenario(self, payload: Dict) -> Dict:
        return self._post("/risk/scenario", payload)

    def run_stress_test(self, payload: Dict) -> Dict:
        return self._post("/risk/stress-test", payload)

    def run_pnl_explain(self, payload: Dict) -> Dict:
        return self._post("/risk/pnl-explain", payload)

    def compute_var(self, payload: Dict) -> Dict:
        return self._post("/risk/var", payload)

    # ── Calibration ───────────────────────────────────────────────
    def calibrate_model(self, payload: Dict) -> Dict:
        return self._post("/calibration/model", payload)

    def compute_implied_vol(self, payload: Dict) -> Dict:
        return self._post("/calibration/implied-vol", payload)

    # ── Market Data ───────────────────────────────────────────────
    def query_vol_surface(self, payload: Dict) -> Dict:
        return self._post("/market/vol-surface/query", payload)

    def build_vol_surface(self, payload: Dict) -> Dict:
        return self._post("/market/vol-surface/build", payload)

    def query_yield_curve(self, payload: Dict) -> Dict:
        return self._post("/market/yield-curve/query", payload)

    # ── Portfolio ─────────────────────────────────────────────────
    def create_portfolio(self, payload: Dict) -> Dict:
        return self._post("/portfolio/create", payload)

    def list_portfolios(self) -> List[Dict]:
        return self._get("/portfolio/list")

    def get_portfolio(self, portfolio_id: str) -> Dict:
        return self._get(f"/portfolio/{portfolio_id}")

    def value_portfolio(self, payload: Dict) -> Dict:
        return self._post("/portfolio/value", payload)

    def portfolio_scenario(self, payload: Dict) -> Dict:
        return self._post("/portfolio/scenario", payload)

    # ── Jobs ──────────────────────────────────────────────────────
    def submit_job(self, payload: Dict) -> Dict:
        return self._post("/jobs/submit", payload)

    def get_job_status(self, job_id: str) -> Dict:
        return self._get(f"/jobs/status/{job_id}")

    def get_job_result(self, job_id: str) -> Dict:
        return self._get(f"/jobs/result/{job_id}")

    def list_jobs(self) -> List[Dict]:
        return self._get("/jobs/list")

    # ── Snapshots ─────────────────────────────────────────────────
    def save_snapshot(self, payload: Dict) -> Dict:
        return self._post("/snapshots/save", payload)

    def list_snapshots(self, params: Dict = None) -> List[Dict]:
        return self._get("/snapshots/list", params=params)

    # ── Health ────────────────────────────────────────────────────
    def health(self) -> Dict:
        """Health check is at root, not under /api/v1."""
        try:
            r = self.session.get(
                self.base_url.replace("/api/v1", "") + "/health",
                timeout=TIMEOUT,
            )
            if not r.ok:
                detail = r.json().get("detail", r.text) if r.text else r.reason
                raise APIError(r.status_code, detail)
            return r.json()
        except requests.ConnectionError:
            raise APIError(0, f"Cannot connect to backend at {self.base_url}")


# Global singleton
api_client = APIClient()
