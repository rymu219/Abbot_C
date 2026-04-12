"""CLI for Monk-01's scan pipeline: features → state → transitions."""

import logging
import sys

import click


@click.group()
def scan() -> None:
    """Run Monk-01's scan pipeline (features, state, transitions)."""


@scan.command()
@click.option("--verbose", "-v", is_flag=True)
@click.option("--prioritized-only", is_flag=True, help="Only scan markets from Prioritized families.")
def run(verbose: bool, prioritized_only: bool) -> None:
    """Run the full scan: compute features → classify states ��� detect transitions."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    from abbot.pipeline.features import compute_features
    from abbot.pipeline.state import classify_all

    # Get prioritized series if requested
    series_filter = None
    if prioritized_only:
        from abbot.pipeline.distill import run_distillation
        families = run_distillation()
        series_filter = [f.series_ticker for f in families if f.decision.value == "prioritize"]
        click.echo(f"Scanning {len(series_filter)} prioritized families")

    # Phase 6: Features
    features = compute_features(prioritized_series=series_filter)
    click.echo(f"\nFeatures computed for {len(features)} markets")

    active = sum(1 for f in features if f.is_active)
    with_vol = sum(1 for f in features if f.has_volume)
    with_bids = sum(1 for f in features if f.has_bids)
    multi_snap = sum(1 for f in features if f.snapshot_count > 1)

    click.echo(f"  Active: {active}  |  With volume: {with_vol}  |  With bids: {with_bids}")
    click.echo(f"  Markets with history (>1 snapshot): {multi_snap}")

    # Phase 7: State classification
    states = classify_all(features)

    click.echo(f"\nState classification:")
    dist: dict[str, int] = {}
    for s in states:
        dist[s.state.value] = dist.get(s.state.value, 0) + 1
    for state_name in ["actionable", "forming", "early", "ignore", "exhausted"]:
        count = dist.get(state_name, 0)
        if count > 0:
            click.echo(f"  {state_name.upper():<12} {count}")

    # Show top markets by state score
    non_ignore = [s for s in states if s.state.value != "ignore"]
    non_ignore.sort(key=lambda s: s.score, reverse=True)

    if non_ignore:
        click.echo(f"\n{'='*80}")
        click.echo("Non-IGNORE markets (ranked by score)")
        click.echo(f"{'='*80}")
        click.echo(f"  {'Score':>5}  {'State':<12} {'Conf':>4}  {'Ticker':<40}  Reasons")
        click.echo("  " + "-" * 90)
        for s in non_ignore[:30]:
            reasons = ", ".join(s.reason_codes[:3])
            click.echo(
                f"  {s.score:5.2f}  {s.state.value:<12} {s.confidence:4.2f}  "
                f"{s.ticker:<40}  {reasons}"
            )
    else:
        click.echo("\nNo non-IGNORE markets found.")
        click.echo("This is expected with only 1 snapshot — trends need history.")
        click.echo("After a few 6-hour ingest cycles, markets will start showing activity.")


@scan.command()
@click.option("--limit", default=20, show_default=True)
def features(limit: int) -> None:
    """Show feature details for top markets by volume."""
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    from abbot.pipeline.features import compute_features

    all_features = compute_features()
    all_features.sort(key=lambda f: f.volume, reverse=True)

    click.echo(f"\nTop {limit} markets by volume:")
    click.echo(
        f"  {'Volume':>8}  {'Price':>6}  {'Spread':>6}  {'OI':>6}  "
        f"{'Hrs':>5}  {'Snaps':>5}  Ticker"
    )
    click.echo("  " + "-" * 80)
    for f in all_features[:limit]:
        if f.volume > 0 or f.has_bids:
            click.echo(
                f"  {f.volume:8.0f}  {f.last_price:6.3f}  {f.spread:6.3f}  "
                f"{f.open_interest:6.0f}  {f.hours_to_expiry:5.0f}  "
                f"{f.snapshot_count:5d}  {f.ticker}"
            )
