"""Scheduled jobs for Abbot.

Runs when `abbot web` is active. Uses APScheduler for in-process scheduling.

Jobs:
  - Focused ingest: pull markets for active Monk families (every 15 min)
  - Monk runner: execute scan cycle for paper/live Monks (every 15 min, after ingest)
  - Catalog refresh: pull full series + events (every 12 hours)
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> BackgroundScheduler:
    """Start the background scheduler with all jobs."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler()

    # Focused ingest: every 15 minutes
    _scheduler.add_job(
        _run_focused_ingest,
        "interval",
        minutes=15,
        id="focused_ingest",
        name="Focused market ingest",
        max_instances=1,
    )

    # Monk runner: every 15 minutes, offset by 2 min after ingest
    _scheduler.add_job(
        _run_monks,
        "interval",
        minutes=15,
        id="monk_runner",
        name="Monk execution cycle",
        max_instances=1,
    )

    # Catalog refresh: every 12 hours
    _scheduler.add_job(
        _run_catalog_refresh,
        "interval",
        hours=12,
        id="catalog_refresh",
        name="Full catalog refresh",
        max_instances=1,
    )

    _scheduler.start()
    logger.info("Scheduler started: focused ingest (15m), monk runner (15m), catalog (12h)")
    return _scheduler


def stop_scheduler() -> None:
    """Stop the scheduler."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped")


def _run_focused_ingest() -> None:
    """Pull markets for families that have active Monks."""
    try:
        from sqlalchemy import select
        from sqlalchemy.orm import Session
        from abbot.db.engine import get_engine
        from abbot.db.models.pipeline import StoredMonkConfig
        from abbot.kalshi.ingest import ingest_markets

        engine = get_engine()
        with Session(engine) as session:
            active = session.execute(
                select(StoredMonkConfig.family_id).where(
                    StoredMonkConfig.lifecycle_status.in_(["paper", "probation", "live", "scaled"]),
                    StoredMonkConfig.approval_status == "approved",
                )
            ).scalars().all()

        if not active:
            logger.debug("No active Monks — skipping focused ingest")
            return

        families = list(set(active))
        logger.info("Focused ingest for %d families: %s", len(families), families)

        for family in families:
            ingest_markets(series_ticker=family, max_pages=2)

    except Exception as e:
        logger.error("Focused ingest failed: %s", str(e)[:200])


def _run_monks() -> None:
    """Execute one scan cycle for all active Monks."""
    try:
        from abbot.monk.runner import run_active_monks
        results = run_active_monks()
        if results:
            logger.info("Monk run: %s", [
                f"{r['monk']}:{r.get('new_entries',0)}e/{r.get('closed',0)}c"
                for r in results
            ])
    except Exception as e:
        logger.error("Monk runner failed: %s", str(e)[:200])


def _run_catalog_refresh() -> None:
    """Refresh the full series and events catalog."""
    try:
        from abbot.kalshi.ingest import ingest_series, ingest_events
        ingest_series()
        ingest_events(max_pages=100)
        logger.info("Catalog refresh complete")
    except Exception as e:
        logger.error("Catalog refresh failed: %s", str(e)[:200])
