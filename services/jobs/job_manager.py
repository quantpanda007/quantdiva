"""
Asynchronous Job Manager.

Manages long-running computations (MC VaR, calibration, batch pricing)
via a submit → poll → retrieve pattern.

Flow:
    1. Client submits job → receives job_id immediately
    2. Job runs in background thread
    3. Client polls status via job_id
    4. When complete, client retrieves result

This prevents API timeouts and allows concurrent processing.

Usage:
    from services.jobs.job_manager import JobManager, job_manager

    # Submit
    job_id = job_manager.submit(
        job_type="monte_carlo_var",
        func=var_engine.monte_carlo_var,
        kwargs={"instruments": [...], "market_env": env, ...},
    )

    # Poll
    status = job_manager.get_status(job_id)
    # {"job_id": "...", "status": "running", "progress": 45}

    # Retrieve
    result = job_manager.get_result(job_id)
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Job status
# ---------------------------------------------------------------------------

class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Job record
# ---------------------------------------------------------------------------

@dataclass
class JobRecord:
    """Internal record of a job."""
    job_id: str
    job_type: str
    status: JobStatus = JobStatus.PENDING
    submitted_at: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    progress: float = 0.0  # 0-100
    result: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "status": self.status.value,
            "submitted_at": self.submitted_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "progress": self.progress,
            "error": self.error,
            "has_result": self.result is not None,
        }


# ---------------------------------------------------------------------------
# Job Manager
# ---------------------------------------------------------------------------

class JobManager:
    """
    Thread-pool based job manager.

    Stores jobs in memory. For production, swap with
    Redis/Celery/database-backed implementation.
    """

    def __init__(self, max_workers: int = 4, max_jobs: int = 1000):
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._jobs: Dict[str, JobRecord] = {}
        self._lock = threading.Lock()
        self._max_jobs = max_jobs

    def submit(
        self,
        job_type: str,
        func: Callable,
        args: tuple = (),
        kwargs: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Submit a job for async execution.

        Returns job_id immediately.
        """
        kwargs = kwargs or {}
        metadata = metadata or {}

        job_id = str(uuid.uuid4())[:12]

        job = JobRecord(
            job_id=job_id,
            job_type=job_type,
            status=JobStatus.PENDING,
            submitted_at=datetime.utcnow().isoformat(),
            metadata=metadata,
        )

        with self._lock:
            # Evict oldest completed jobs if at capacity
            if len(self._jobs) >= self._max_jobs:
                self._evict_old_jobs()
            self._jobs[job_id] = job

        # Submit to thread pool
        self._executor.submit(self._run_job, job_id, func, args, kwargs)

        logger.info(f"Job submitted: {job_id} ({job_type})")
        return job_id

    def _run_job(
        self,
        job_id: str,
        func: Callable,
        args: tuple,
        kwargs: Dict,
    ) -> None:
        """Execute the job in a worker thread."""
        job = self._jobs.get(job_id)
        if job is None:
            return

        job.status = JobStatus.RUNNING
        job.started_at = datetime.utcnow().isoformat()

        try:
            # Inject progress callback if function accepts it
            if "progress_callback" in func.__code__.co_varnames:
                kwargs["progress_callback"] = lambda p: setattr(job, "progress", p)

            result = func(*args, **kwargs)

            job.result = result
            job.status = JobStatus.COMPLETED
            job.progress = 100.0
            job.completed_at = datetime.utcnow().isoformat()

            logger.info(f"Job completed: {job_id}")

        except Exception as e:
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.completed_at = datetime.utcnow().isoformat()
            logger.error(f"Job failed: {job_id}: {e}\n{traceback.format_exc()}")

    def get_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get job status."""
        job = self._jobs.get(job_id)
        if job is None:
            return None
        return job.to_dict()

    def get_result(self, job_id: str) -> Optional[Any]:
        """Get job result (None if not complete)."""
        job = self._jobs.get(job_id)
        if job is None:
            return None
        if job.status != JobStatus.COMPLETED:
            return None
        return job.result

    def cancel(self, job_id: str) -> bool:
        """Cancel a pending job. Cannot cancel running jobs."""
        job = self._jobs.get(job_id)
        if job is None:
            return False
        if job.status == JobStatus.PENDING:
            job.status = JobStatus.CANCELLED
            return True
        return False

    def list_jobs(
        self,
        status: Optional[JobStatus] = None,
        job_type: Optional[str] = None,
    ) -> list:
        """List jobs, optionally filtered."""
        results = []
        for job in self._jobs.values():
            if status and job.status != status:
                continue
            if job_type and job.job_type != job_type:
                continue
            results.append(job.to_dict())
        return results

    def _evict_old_jobs(self) -> None:
        """Remove oldest completed/failed jobs."""
        completed = [
            (jid, j) for jid, j in self._jobs.items()
            if j.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
        ]
        # Sort by completion time, evict oldest
        completed.sort(key=lambda x: x[1].completed_at or "")
        evict_count = max(len(completed) // 2, 1)
        for jid, _ in completed[:evict_count]:
            del self._jobs[jid]


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

job_manager = JobManager(max_workers=4)