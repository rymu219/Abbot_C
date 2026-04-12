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
    click.echo("Status: Foundation phase (Phase 2 complete)")
    click.echo("Next: Phase 3 — Data Access and Raw Ingestion")
