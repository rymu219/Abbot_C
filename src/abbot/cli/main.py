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
    click.echo("Phases 1-15 implemented. MVP loop complete.")


@cli.command()
@click.option("--port", default=8000, show_default=True)
@click.option("--host", default="127.0.0.1", show_default=True)
def web(host: str, port: int) -> None:
    """Launch the Abbot web UI."""
    import uvicorn

    click.echo(f"Starting Abbot UI at http://{host}:{port}")
    uvicorn.run("abbot.web.app:app", host=host, port=port, reload=True)


# Register sub-command groups
from abbot.cli.ingest import ingest  # noqa: E402
from abbot.cli.schedule import schedule  # noqa: E402
from abbot.cli.purge import purge  # noqa: E402
from abbot.cli.distill import distill  # noqa: E402
from abbot.cli.scan import scan  # noqa: E402
from abbot.cli.monk_cli import monk_group  # noqa: E402
from abbot.cli.review import review  # noqa: E402

cli.add_command(ingest)
cli.add_command(schedule)
cli.add_command(purge)
cli.add_command(distill)
cli.add_command(scan)
cli.add_command(monk_group)
cli.add_command(review)
