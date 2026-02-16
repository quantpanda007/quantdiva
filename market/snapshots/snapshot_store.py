"""
Market Data Snapshot Store.

Provides versioned, reproducible market data snapshots.

Every pricing run can reference a snapshot_id, ensuring:
- Reproducibility: re-price with exact same market data
- Auditability: prove what data was used
- P&L explain consistency: yesterday's snapshot vs today's

Storage is in-memory for now. Production would use a database
or object store (S3, Redis, etc.).

Usage:
    from market.snapshots.snapshot_store import SnapshotStore, snapshot_store

    # Save current market state
    snapshot_id = snapshot_store.save(
        market_data=market_data_dict,
        source="bloomberg",
        tags={"desk": "equity", "cob_date": "2025-01-15"},
    )

    # Retrieve
    snapshot = snapshot_store.get(snapshot_id)

    # List snapshots
    snapshots = snapshot_store.list(cob_date="2025-01-15")

    # Build market env from snapshot
    from market.snapshots.snapshot_store import build_env_from_snapshot
    env = build_env_from_snapshot(snapshot_id)
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Snapshot record
# ---------------------------------------------------------------------------

@dataclass
class MarketSnapshot:
    """
    A versioned point-in-time market data snapshot.

    Attributes:
        snapshot_id:   Unique identifier
        timestamp:     When the snapshot was created
        cob_date:      Close-of-business date
        source:        Data source (e.g. "bloomberg", "refinitiv", "manual")
        data:          The actual market data dict
        checksum:      SHA256 hash for integrity verification
        tags:          Arbitrary metadata
        version:       Increment if same cob_date is re-snapped
    """
    snapshot_id: str = ""
    timestamp: str = ""
    cob_date: str = ""
    source: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    checksum: str = ""
    tags: Dict[str, str] = field(default_factory=dict)
    version: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
            "cob_date": self.cob_date,
            "source": self.source,
            "checksum": self.checksum,
            "tags": self.tags,
            "version": self.version,
        }

    def to_full_dict(self) -> Dict[str, Any]:
        """Include the actual data."""
        d = self.to_dict()
        d["data"] = self.data
        return d


# ---------------------------------------------------------------------------
# Snapshot Store
# ---------------------------------------------------------------------------

class SnapshotStore:
    """
    In-memory snapshot store with versioning.

    Thread-safe. For production, replace with database-backed store.
    """

    def __init__(self, max_snapshots: int = 500):
        self._snapshots: Dict[str, MarketSnapshot] = {}
        self._lock = threading.Lock()
        self._max_snapshots = max_snapshots

    def save(
        self,
        market_data: Dict[str, Any],
        cob_date: Optional[str] = None,
        source: str = "manual",
        tags: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Save a market data snapshot.

        Returns snapshot_id.
        """
        snapshot_id = f"snap-{uuid.uuid4().hex[:8]}"
        now = datetime.utcnow().isoformat()

        if cob_date is None:
            cob_date = now[:10]  # extract date

        # Compute checksum
        data_str = json.dumps(market_data, sort_keys=True, default=str)
        checksum = hashlib.sha256(data_str.encode()).hexdigest()[:16]

        # Version: check if same cob_date + source already exists
        version = 1
        for snap in self._snapshots.values():
            if snap.cob_date == cob_date and snap.source == source:
                version = max(version, snap.version + 1)

        snapshot = MarketSnapshot(
            snapshot_id=snapshot_id,
            timestamp=now,
            cob_date=cob_date,
            source=source,
            data=market_data,
            checksum=checksum,
            tags=tags or {},
            version=version,
        )

        with self._lock:
            if len(self._snapshots) >= self._max_snapshots:
                self._evict_oldest()
            self._snapshots[snapshot_id] = snapshot

        logger.info(
            f"Snapshot saved: {snapshot_id} | cob={cob_date} | "
            f"source={source} | v{version} | checksum={checksum}"
        )

        return snapshot_id

    def get(self, snapshot_id: str) -> Optional[MarketSnapshot]:
        """Retrieve a snapshot by ID."""
        return self._snapshots.get(snapshot_id)

    def get_data(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve just the market data from a snapshot."""
        snap = self._snapshots.get(snapshot_id)
        return snap.data if snap else None

    def get_latest(
        self,
        cob_date: Optional[str] = None,
        source: Optional[str] = None,
    ) -> Optional[MarketSnapshot]:
        """Get the latest snapshot, optionally filtered."""
        candidates = list(self._snapshots.values())

        if cob_date:
            candidates = [s for s in candidates if s.cob_date == cob_date]
        if source:
            candidates = [s for s in candidates if s.source == source]

        if not candidates:
            return None

        return max(candidates, key=lambda s: s.timestamp)

    def list_snapshots(
        self,
        cob_date: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List snapshots (metadata only, no data)."""
        candidates = list(self._snapshots.values())

        if cob_date:
            candidates = [s for s in candidates if s.cob_date == cob_date]
        if source:
            candidates = [s for s in candidates if s.source == source]

        candidates.sort(key=lambda s: s.timestamp, reverse=True)
        return [s.to_dict() for s in candidates[:limit]]

    def delete(self, snapshot_id: str) -> bool:
        """Delete a snapshot."""
        with self._lock:
            if snapshot_id in self._snapshots:
                del self._snapshots[snapshot_id]
                return True
        return False

    def verify_checksum(self, snapshot_id: str) -> bool:
        """Verify data integrity of a snapshot."""
        snap = self._snapshots.get(snapshot_id)
        if snap is None:
            return False

        data_str = json.dumps(snap.data, sort_keys=True, default=str)
        computed = hashlib.sha256(data_str.encode()).hexdigest()[:16]
        return computed == snap.checksum

    def _evict_oldest(self) -> None:
        """Remove oldest snapshots."""
        sorted_snaps = sorted(
            self._snapshots.items(),
            key=lambda x: x[1].timestamp,
        )
        evict_count = max(len(sorted_snaps) // 4, 1)
        for sid, _ in sorted_snaps[:evict_count]:
            del self._snapshots[sid]

    @property
    def count(self) -> int:
        return len(self._snapshots)


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

snapshot_store = SnapshotStore()


# ---------------------------------------------------------------------------
# Helper: build MarketEnvironment from snapshot
# ---------------------------------------------------------------------------

def build_env_from_snapshot(
    snapshot_id: str,
    underlying: Optional[str] = None,
    store: Optional[SnapshotStore] = None,
):
    """
    Build a MarketEnvironment from a saved snapshot.

    The snapshot data is expected to follow the same format
    as MarketDataRequest (pricing_date, underlyings, rate).
    """
    from api.v1.schemas import MarketDataRequest, UnderlyingData
    from api.v1.helpers import build_market_env_from_request

    store = store or snapshot_store
    snap = store.get(snapshot_id)

    if snap is None:
        raise ValueError(f"Snapshot not found: '{snapshot_id}'")

    data = snap.data

    # Build MarketDataRequest from snapshot data
    underlyings = {}
    for und_key, und_data in data.get("underlyings", {}).items():
        if isinstance(und_data, dict):
            underlyings[und_key] = UnderlyingData(**und_data)

    req = MarketDataRequest(
        pricing_date=data.get("pricing_date", snap.cob_date),
        underlyings=underlyings,
        rate=data.get("rate", 0.05),
    )

    if underlying is None and underlyings:
        underlying = list(underlyings.keys())[0]

    return build_market_env_from_request(req, underlying=underlying)