"""
API v1 router — aggregates all endpoint groups.
"""

from fastapi import APIRouter

from api.v1.endpoints.pricing import router as pricing_router
from api.v1.endpoints.sensitivities import router as sensitivities_router
from api.v1.endpoints.risk import router as risk_router
from api.v1.endpoints.calibration import router as calibration_router
from api.v1.endpoints.market_data import router as market_data_router
from api.v1.endpoints.registry_endpoints import router as registry_router
from api.v1.endpoints.portfolio import router as portfolio_router
from api.v1.endpoints.jobs import router as jobs_router
from api.v1.endpoints.snapshots import router as snapshots_router

api_v1_router = APIRouter()

api_v1_router.include_router(pricing_router, prefix="/pricing", tags=["pricing"])
api_v1_router.include_router(sensitivities_router, prefix="/sensitivities", tags=["sensitivities"])
api_v1_router.include_router(risk_router, prefix="/risk", tags=["risk"])
api_v1_router.include_router(calibration_router, prefix="/calibration", tags=["calibration"])
api_v1_router.include_router(market_data_router, prefix="/market", tags=["market data"])
api_v1_router.include_router(registry_router, prefix="/registry", tags=["registry"])
api_v1_router.include_router(portfolio_router, prefix="/portfolio", tags=["portfolio"])
api_v1_router.include_router(jobs_router, prefix="/jobs", tags=["jobs"])
api_v1_router.include_router(snapshots_router, prefix="/snapshots", tags=["snapshots"])

# Live market data (OpenBB / yfinance)
try:
    from api.v1.endpoints.market_data_live import router as live_mkt_router
    api_v1_router.include_router(live_mkt_router, tags=["market data (live)"])
except ImportError:
    pass  # Providers not installed — endpoints won't be available

# Historical market data (SQLite store)
try:
    from api.v1.endpoints.market_data_historical import router as hist_mkt_router
    api_v1_router.include_router(hist_mkt_router, tags=["market data (historical)"])
except Exception as e:
    print(f"[router] Historical market data endpoints not loaded: {e}")

# Excel export
try:
    from api.v1.endpoints.export import router as export_router
    api_v1_router.include_router(export_router, tags=["export"])
except Exception as e:
    print(f"[router] Export endpoints not loaded: {e}")
