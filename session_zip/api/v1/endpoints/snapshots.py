"""
Market data snapshot endpoints — save, retrieve, list, verify.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from market.snapshots.snapshot_store import snapshot_store

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SnapshotSaveRequest(BaseModel):
    market_data: Dict[str, Any] = Field(..., description="Market data dict (same format as MarketDataRequest)")
    cob_date: Optional[str] = None
    source: str = "manual"
    tags: Dict[str, str] = Field(default_factory=dict)


class SnapshotResponse(BaseModel):
    snapshot_id: str
    timestamp: str
    cob_date: str
    source: str
    checksum: str
    version: int
    tags: Dict[str, str]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/save", response_model=SnapshotResponse)
def save_snapshot(req: SnapshotSaveRequest):
    """Save a market data snapshot. Returns snapshot_id for future reference."""
    try:
        snapshot_id = snapshot_store.save(
            market_data=req.market_data,
            cob_date=req.cob_date,
            source=req.source,
            tags=req.tags,
        )

        snap = snapshot_store.get(snapshot_id)
        return SnapshotResponse(
            snapshot_id=snap.snapshot_id,
            timestamp=snap.timestamp,
            cob_date=snap.cob_date,
            source=snap.source,
            checksum=snap.checksum,
            version=snap.version,
            tags=snap.tags,
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/get/{snapshot_id}")
def get_snapshot(snapshot_id: str, include_data: bool = False):
    """Retrieve a snapshot by ID."""
    snap = snapshot_store.get(snapshot_id)
    if snap is None:
        raise HTTPException(status_code=404, detail=f"Snapshot '{snapshot_id}' not found")

    if include_data:
        return snap.to_full_dict()
    return snap.to_dict()


@router.get("/list")
def list_snapshots(
    cob_date: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 50,
):
    """List snapshots, optionally filtered."""
    return snapshot_store.list_snapshots(cob_date=cob_date, source=source, limit=limit)


@router.get("/latest")
def get_latest_snapshot(
    cob_date: Optional[str] = None,
    source: Optional[str] = None,
):
    """Get the latest snapshot."""
    snap = snapshot_store.get_latest(cob_date=cob_date, source=source)
    if snap is None:
        raise HTTPException(status_code=404, detail="No snapshots found")
    return snap.to_dict()


@router.get("/verify/{snapshot_id}")
def verify_snapshot(snapshot_id: str):
    """Verify data integrity of a snapshot."""
    snap = snapshot_store.get(snapshot_id)
    if snap is None:
        raise HTTPException(status_code=404, detail=f"Snapshot '{snapshot_id}' not found")

    valid = snapshot_store.verify_checksum(snapshot_id)
    return {
        "snapshot_id": snapshot_id,
        "checksum": snap.checksum,
        "integrity_valid": valid,
    }


@router.delete("/{snapshot_id}")
def delete_snapshot(snapshot_id: str):
    """Delete a snapshot."""
    if snapshot_store.delete(snapshot_id):
        return {"status": "deleted", "snapshot_id": snapshot_id}
    raise HTTPException(status_code=404, detail=f"Snapshot '{snapshot_id}' not found")