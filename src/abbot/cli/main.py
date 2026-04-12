"""Abbot CLI entry point."""

import click


@click.group()
@click.version_option(version="0.1.0", prog_name="abbot")
def cli() -> None:
    """Abbot — Private automation hub for managing Monks."""


@cli.command()
def status() -> None:
    """Show current system status."""
    click.echo("Abbot v0.1.0")
    click.echo("Status: Phase 3 — Data Access and Raw Ingestion")


# Register sub-command groups
from abbot.cli.ingest import ingest  # noqa: E402
from abbot.cli.schedule import schedule  # noqa: E402
from abbot.cli.purge import purge  # noqa: E402
from abbot.cli.distill import distill  # noqa: E402
from abbot.cli.scan import scan  # noqa: E402
from abbot.cli.monk_cli import monk_group  # noqa: E402

cli.add_command(ingest)
cli.add_command(schedule)
cli.add_command(purge)
cli.add_command(distill)
cli.add_command(scan)
cli.add_command(monk_group)
