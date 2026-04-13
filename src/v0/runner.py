"""Orchestrator for Abbot-C v0.

Runs the full engine cycle: schedule sync → discover/decide → settle → reconcile.
Can be invoked as a one-shot CLI or run on a loop.

Build spec ref: §11 recommended build order, §5 worker cadences.

Usage:
    python -m v0.runner              # one full cycle
    python -m v0.runner --loop       # run continuously (1-min discover, 10-min settle)
    python -m v0.runner --schedule   # schedule sync only
    python -m v0.runner --settle     # settlement poll only
    python -m v0.runner --reconcile  # reconciliation check only
"""

import argparse
import logging
import sys
import time

from v0.schedule import sync_schedule
from v0.discover import run_discover_decide
from v0.settle import run_settle
from v0.reconcile import run_reconciliation

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger("v0.runner")


def run_cycle() -> None:
    """Run one complete engine cycle."""
    logger.info("=== Abbot-C v0 cycle start ===")

    # 1. Schedule sync
    try:
        count = sync_schedule()
        logger.info("Schedule: %d games synced", count)
    except Exception as e:
        logger.error("Schedule sync failed: %s", str(e)[:200])

    # 2. Discover + decide
    try:
        result = run_discover_decide()
        logger.info(
            "Discover: checked=%d snapshotted=%d bets=%d skipped=%d",
            result["checked"], result["snapshotted"],
            result["bet"], len(result["skipped"]),
        )
    except Exception as e:
        logger.error("Discover/decide failed: %s", str(e)[:200])

    # 3. Settle
    try:
        result = run_settle()
        logger.info(
            "Settle: checked=%d settled=%d pending=%d",
            result["checked"], result["settled"], result["still_pending"],
        )
    except Exception as e:
        logger.error("Settlement failed: %s", str(e)[:200])

    # 4. Reconcile
    try:
        findings = run_reconciliation()
        missed = len(findings["missed_bets"])
        stale = len(findings["stale_settlements"])
        if missed or stale:
            logger.warning("Reconciliation: %d missed, %d stale", missed, stale)
        else:
            logger.info("Reconciliation: clean")
    except Exception as e:
        logger.error("Reconciliation failed: %s", str(e)[:200])

    logger.info("=== Abbot-C v0 cycle end ===")


def run_loop(discover_interval: int = 60, settle_interval: int = 600) -> None:
    """Run the engine continuously.

    Discover/decide runs every discover_interval seconds (default 60).
    Settlement polls every settle_interval seconds (default 600).
    Schedule syncs at startup and every 30 minutes.
    """
    logger.info("Starting continuous loop (discover=%ds, settle=%ds)",
                discover_interval, settle_interval)

    last_settle = 0.0
    last_schedule = 0.0
    schedule_interval = 1800  # 30 minutes

    while True:
        now = time.monotonic()

        # Schedule sync
        if now - last_schedule >= schedule_interval or last_schedule == 0:
            try:
                sync_schedule()
            except Exception as e:
                logger.error("Schedule sync failed: %s", str(e)[:200])
            last_schedule = now

        # Discover + decide (every cycle)
        try:
            run_discover_decide()
        except Exception as e:
            logger.error("Discover/decide failed: %s", str(e)[:200])

        # Settlement (less frequent)
        if now - last_settle >= settle_interval or last_settle == 0:
            try:
                run_settle()
            except Exception as e:
                logger.error("Settlement failed: %s", str(e)[:200])
            last_settle = now

            # Reconcile with each settle cycle
            try:
                run_reconciliation()
            except Exception as e:
                logger.error("Reconciliation failed: %s", str(e)[:200])

        time.sleep(discover_interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Abbot-C v0 runner")
    parser.add_argument("--loop", action="store_true", help="Run continuously")
    parser.add_argument("--schedule", action="store_true", help="Schedule sync only")
    parser.add_argument("--settle", action="store_true", help="Settlement poll only")
    parser.add_argument("--reconcile", action="store_true", help="Reconciliation only")
    args = parser.parse_args()

    if args.schedule:
        sync_schedule()
    elif args.settle:
        run_settle()
    elif args.reconcile:
        run_reconciliation()
    elif args.loop:
        run_loop()
    else:
        run_cycle()


if __name__ == "__main__":
    main()
