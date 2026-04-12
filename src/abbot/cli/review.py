"""Phase 15: Review and Control Loop.

Structured daily/weekly review summaries so the operator can manage
the system without guesswork.
"""

import json
import logging
import sys

import click


@click.group()
def review() -> None:
    """Review system state and generate summaries."""


@review.command()
def daily() -> None:
    """Generate a daily review summary."""
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    from abbot.monitor.performance import generate_daily_summary

    summary = generate_daily_summary()

    click.echo("=" * 60)
    click.echo("DAILY REVIEW")
    click.echo("=" * 60)

    s = summary["summary"]
    click.echo(f"\n  Events today:     {s['events_today']}")
    click.echo(f"  Events this week: {s['events_this_week']}")
    click.echo(f"  Total P&L:        ${s['total_pnl']:.2f}")
    click.echo(f"  Total trades:     {s['total_trades']}")

    click.echo(f"\n  Data freshness: {summary['data_freshness']['latest_ingest']}")
    click.echo(f"  DB size: {summary['storage']['db_size']}")

    click.echo("\n  Data tables:")
    for table, count in summary["storage"]["tables"].items():
        click.echo(f"    {table}: {count:,}")

    # Run distillation summary
    from abbot.pipeline.distill import run_distillation
    families = run_distillation()
    p = sum(1 for f in families if f.decision.value == "prioritize")
    w = sum(1 for f in families if f.decision.value == "watch")

    click.echo(f"\n  Families: {len(families)} total, {p} prioritized, {w} watching")

    click.echo("\n" + "=" * 60)


@review.command()
def weekly() -> None:
    """Generate a weekly review summary."""
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    from abbot.monitor.performance import generate_weekly_summary

    summary = generate_weekly_summary()

    click.echo("=" * 60)
    click.echo("WEEKLY REVIEW")
    click.echo("=" * 60)

    s = summary["summary"]
    click.echo(f"\n  Events this week: {s['events_this_week']}")
    click.echo(f"  Total P&L:        ${s['total_pnl']:.2f}")
    click.echo(f"  DB size:          {summary['storage']['db_size']}")

    if summary.get("weekly_ingests"):
        click.echo("\n  Ingest activity this week:")
        for r in summary["weekly_ingests"]:
            click.echo(f"    {r['type']}: {r['runs']} runs, {r['total_records']:,} records ({r['status']})")

    click.echo("\n" + "=" * 60)


@review.command()
def full() -> None:
    """Run the full pipeline and display a comprehensive review.

    Equivalent to running: distill → scan → candidates in sequence
    and presenting all results.
    """
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    from abbot.pipeline.distill import run_distillation
    from abbot.pipeline.features import compute_features
    from abbot.pipeline.state import classify_all
    from abbot.pipeline.candidates import discover_candidates

    click.echo("Running full pipeline review...\n")

    # Distillation
    families = run_distillation()
    prioritize = [f for f in families if f.decision.value == "prioritize"]
    watch = [f for f in families if f.decision.value == "watch"]
    ignore = [f for f in families if f.decision.value == "ignore"]

    click.echo(f"DISTILLATION: {len(families)} families")
    click.echo(f"  Prioritize: {len(prioritize)}  |  Watch: {len(watch)}  |  Ignore: {len(ignore)}")

    # Scan
    eligible = [f.series_ticker for f in families if f.decision.value != "ignore"]
    features = compute_features(prioritized_series=eligible)
    states = classify_all(features)

    dist = {}
    for s in states:
        dist[s.state.value] = dist.get(s.state.value, 0) + 1

    click.echo(f"\nSCAN: {len(states)} markets")
    for state_name in ["actionable", "forming", "early", "ignore"]:
        if dist.get(state_name, 0) > 0:
            click.echo(f"  {state_name.upper()}: {dist[state_name]}")

    # Candidates
    candidates = discover_candidates(families, states)
    build = [c for c in candidates if c.decision.value == "build_candidate"]
    proto = [c for c in candidates if c.decision.value == "prototype_candidate"]

    click.echo(f"\nCANDIDATES: {len(candidates)} evaluated")
    click.echo(f"  Build: {len(build)}  |  Prototype: {len(proto)}")

    if build:
        click.echo("\n  Top Build Candidates:")
        for c in build[:10]:
            click.echo(f"    {c.monk_worthiness:.2f}  {c.series_ticker:<25} {c.title[:35]}")

    click.echo()
