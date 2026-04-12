"""CLI commands for data ingestion."""

import logging
import sys
import time

import click


@click.group()
def ingest() -> None:
    """Ingest data from Kalshi."""


@ingest.command()
@click.option(
    "--type", "ingest_type",
    type=click.Choice(["all", "markets", "events", "series", "trades"]),
    default="all",
    help="What to ingest (default: all).",
)
@click.option(
    "--trade-limit", default=10000, show_default=True,
    help="Max trades to pull per ingest run.",
)
@click.option(
    "--market-pages", default=0, show_default=True,
    help="Max pages for market ingest (1000/page). 0=unlimited.",
)
@click.option(
    "--event-pages", default=0, show_default=True,
    help="Max pages for event ingest (200/page). 0=unlimited.",
)
@click.option(
    "--series-ticker", default=None,
    help="Only pull markets for this series ticker.",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging.")
def run(
    ingest_type: str,
    trade_limit: int,
    market_pages: int,
    event_pages: int,
    series_ticker: str | None,
    verbose: bool,
) -> None:
    """Run a full ingestion cycle.

    Pulls data from Kalshi API, stores raw snapshots in the database,
    and logs the run for auditability.

    Examples:

        abbot ingest run                            # ingest everything

        abbot ingest run --type markets --market-pages 5   # first 5K markets

        abbot ingest run --type series              # series only

        abbot ingest run --type trades --trade-limit 5000
    """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    from abbot.kalshi.ingest import run_ingest

    click.echo(f"Starting {ingest_type} ingest...")
    start = time.time()

    results = run_ingest(
        ingest_type=ingest_type,
        trade_limit=trade_limit,
        market_max_pages=market_pages,
        event_max_pages=event_pages,
        series_ticker=series_ticker,
    )

    elapsed = time.time() - start
    click.echo()
    click.echo("Results:")
    for r in results:
        status_icon = "+" if r.get("status") == "success" else "x"
        count = r.get("count", "?")
        click.echo(f"  [{status_icon}] {r['type']}: {count} records")
        if r.get("error"):
            click.echo(f"      error: {r['error']}")

    click.echo(f"\nCompleted in {elapsed:.1f}s")


@ingest.command()
@click.option("--limit", default=10, show_default=True, help="Number of recent runs to show.")
def log(limit: int) -> None:
    """Show recent ingestion runs."""
    from sqlalchemy import select
    from abbot.db.engine import get_engine
    from abbot.db.models.raw import IngestLog
    from sqlalchemy.orm import Session

    engine = get_engine()
    with Session(engine) as session:
        stmt = (
            select(IngestLog)
            .order_by(IngestLog.started_at.desc())
            .limit(limit)
        )
        logs = session.execute(stmt).scalars().all()

        if not logs:
            click.echo("No ingestion runs found.")
            return

        click.echo(f"{'Ingest ID':<18} {'Type':<10} {'Status':<10} {'Records':>8}  {'Started'}")
        click.echo("-" * 76)
        for entry in logs:
            started = entry.started_at.strftime("%Y-%m-%d %H:%M:%S") if entry.started_at else "?"
            click.echo(
                f"{entry.ingest_id:<18} {entry.ingest_type:<10} {entry.status:<10} "
                f"{entry.records_count:>8}  {started}"
            )
