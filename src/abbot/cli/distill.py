"""CLI commands for the distillation pipeline."""

import logging
import sys

import click


@click.group()
def distill() -> None:
    """Run and review the distillation pipeline."""


@distill.command()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging.")
def run(verbose: bool) -> None:
    """Run the distillation pipeline.

    Reduces raw Kalshi data into scored, classified families.
    """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    from abbot.pipeline.distill import run_distillation

    families = run_distillation()

    # Show summary
    prioritize = [f for f in families if f.decision.value == "prioritize"]
    watch = [f for f in families if f.decision.value == "watch"]
    ignore = [f for f in families if f.decision.value == "ignore"]

    click.echo(f"\nDistillation complete: {len(families)} families")
    click.echo(f"  PRIORITIZE: {len(prioritize)}")
    click.echo(f"  WATCH:      {len(watch)}")
    click.echo(f"  IGNORE:     {len(ignore)}")

    if prioritize:
        click.echo(f"\n{'='*80}")
        click.echo("PRIORITIZE — High-value families for Monk consideration")
        click.echo(f"{'='*80}")
        _print_families(prioritize[:20])

    if watch:
        click.echo(f"\n{'='*80}")
        click.echo("WATCH — Moderate potential, needs more data")
        click.echo(f"{'='*80}")
        _print_families(watch[:10])


@distill.command()
@click.option("--decision", type=click.Choice(["all", "prioritize", "watch", "ignore"]), default="all")
@click.option("--domain", default=None, help="Filter by domain (economics, politics, etc.)")
@click.option("--limit", default=50, show_default=True)
def families(decision: str, domain: str | None, limit: int) -> None:
    """List distilled families with scores."""
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    from abbot.pipeline.distill import run_distillation

    all_families = run_distillation()

    if decision != "all":
        all_families = [f for f in all_families if f.decision.value == decision]

    if domain:
        all_families = [f for f in all_families if f.domain.value == domain]

    click.echo(f"\n{len(all_families)} families" + (f" ({decision})" if decision != "all" else ""))
    _print_families(all_families[:limit])


def _print_families(families) -> None:
    """Print a formatted table of families."""
    click.echo(
        f"\n  {'Score':>5}  {'Decision':<11} {'Freq':<10} {'Domain':<12} "
        f"{'Events':>6} {'Mkts':>6} {'Volume':>10}  {'Series'}"
    )
    click.echo("  " + "-" * 95)
    for f in families:
        vol = f"{f.total_volume:,.0f}" if f.total_volume > 0 else "-"
        click.echo(
            f"  {f.composite_score:5.2f}  {f.decision.value:<11} {f.frequency:<10} "
            f"{f.domain.value:<12} {f.event_count:>6} {f.market_count:>6} {vol:>10}  "
            f"{f.series_ticker} — {f.title[:40]}"
        )
