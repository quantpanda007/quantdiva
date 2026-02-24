"""
Scheduler for daily market data refresh.

Uses APScheduler to run inside the FastAPI process.
Triggers at configurable time (default: 6:30 PM EST).

Usage:
    from market.historical.scheduler import start_scheduler, stop_scheduler
    start_scheduler()   # Call on app startup
    stop_scheduler()    # Call on app shutdown
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

_scheduler = None


def _daily_refresh_job():
    """Job function called by the scheduler."""
    logger.info(f"[Scheduler] Daily refresh triggered at {datetime.now()}")
    try:
        from market.historical.fetcher import fetcher
        results = fetcher.refresh_all()
        total = sum(r.rows_inserted for r in results)
        errors = sum(len(r.errors) for r in results)
        logger.info(f"[Scheduler] Refresh complete: {total} rows, {errors} errors")
    except Exception as e:
        logger.error(f"[Scheduler] Refresh failed: {e}")


def start_scheduler():
    """Start the daily refresh scheduler."""
    global _scheduler

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.warning(
            "[Scheduler] APScheduler not installed. "
            "Install with: pip install apscheduler"
        )
        return

    from market.historical.assets import SCHEDULE

    if not SCHEDULE.get("enabled", True):
        logger.info("[Scheduler] Disabled in config")
        return

    if _scheduler is not None:
        logger.warning("[Scheduler] Already running")
        return

    time_str = SCHEDULE.get("time", "18:30")
    tz = SCHEDULE.get("timezone", "US/Eastern")
    hour, minute = map(int, time_str.split(":"))

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _daily_refresh_job,
        trigger=CronTrigger(
            hour=hour, minute=minute,
            timezone=tz,
            day_of_week="mon-fri",  # Weekdays only
        ),
        id="daily_market_refresh",
        name="Daily Market Data Refresh",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        f"[Scheduler] Started — daily refresh at {time_str} {tz} (Mon-Fri)"
    )


def stop_scheduler():
    """Stop the scheduler gracefully."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("[Scheduler] Stopped")


def get_scheduler_status() -> dict:
    """Get scheduler status info."""
    from market.historical.assets import SCHEDULE

    if _scheduler is None:
        return {
            "running": False,
            "schedule": SCHEDULE,
            "next_run": None,
        }

    jobs = _scheduler.get_jobs()
    next_run = None
    if jobs:
        next_run = str(jobs[0].next_run_time)

    return {
        "running": True,
        "schedule": SCHEDULE,
        "next_run": next_run,
        "jobs": len(jobs),
    }
