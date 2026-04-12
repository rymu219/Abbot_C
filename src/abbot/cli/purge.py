"""CLI command to purge old raw snapshots."""

import click


@click.command()
@click.option(
    "--days", default=7, show_default=True,
    help="Delete raw snapshots older than this many days.",
)
@click.option("--dry-run", is_flag=True, help="Show what would be deleted without deleting.")
def purge(days: int, dry_run: bool) -> None:
    """Purge raw snapshots older than N days.

    Keeps the ingest_log forever (lightweight audit trail).
    Only deletes from the raw snapshot tables.
    """
    from datetime import datetime, timezone, timedelta

    from sqlalchemy import delete, func, select, text
    from sqlalchemy.orm import Session

    from abbot.db.engine import get_engine
    from abbot.db.models.raw import (
        RawEventSnapshot,
        RawMarketSnapshot,
        RawSeriesSnapshot,
        RawTradeSnapshot,
    )

    engine = get_engine()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    tables = [
        ("raw_market_snapshots", RawMarketSnapshot),
        ("raw_event_snapshots", RawEventSnapshot),
        ("raw_series_snapshots", RawSeriesSnapshot),
        ("raw_trade_snapshots", RawTradeSnapshot),
    ]

    with Session(engine) as session:
        total = 0
        for name, model in tables:
            count = session.execute(
                select(func.count()).where(model.ingested_at < cutoff)
            ).scalar()

            if dry_run:
                click.echo(f"  [dry run] {name}: {count} rows would be deleted")
            else:
                if count > 0:
                    session.execute(delete(model).where(model.ingested_at < cutoff))
                click.echo(f"  {name}: {count} rows deleted")

            total += count

        if not dry_run and total > 0:
            session.commit()

            # Reclaim space
            with engine.connect() as conn:
                for name, _ in tables:
                    conn.execute(text(f"VACUUM {name}"))

        click.echo(f"\nTotal: {total} rows {'would be ' if dry_run else ''}deleted (cutoff: {cutoff:%Y-%m-%d %H:%M})")
