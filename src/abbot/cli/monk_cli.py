"""CLI for Monk candidate discovery and config generation."""

import json
import logging
import sys

import click


@click.group(name="monk")
def monk_group() -> None:
    """Discover Monk candidates and generate configs."""


@monk_group.command()
@click.option("--verbose", "-v", is_flag=True)
def candidates(verbose: bool) -> None:
    """Run the full pipeline: distill → scan → discover candidates."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    from abbot.pipeline.distill import run_distillation
    from abbot.pipeline.features import compute_features
    from abbot.pipeline.state import classify_all
    from abbot.pipeline.candidates import discover_candidates

    # Phase 5
    families = run_distillation()
    prioritized = [f.series_ticker for f in families if f.decision.value == "prioritize"]
    watch = [f.series_ticker for f in families if f.decision.value == "watch"]
    eligible_tickers = prioritized + watch

    # Phase 6-7 (scan only eligible families)
    features = compute_features(prioritized_series=eligible_tickers)
    states = classify_all(features)

    # Phase 8
    all_candidates = discover_candidates(families, states)

    # Display
    build = [c for c in all_candidates if c.decision.value == "build_candidate"]
    proto = [c for c in all_candidates if c.decision.value == "prototype_candidate"]
    watch_longer = [c for c in all_candidates if c.decision.value == "watch_longer"]
    no_monk = [c for c in all_candidates if c.decision.value == "no_monk"]

    click.echo(f"\nCandidate Discovery: {len(all_candidates)} families evaluated")
    click.echo(f"  BUILD_CANDIDATE:     {len(build)}")
    click.echo(f"  PROTOTYPE_CANDIDATE: {len(proto)}")
    click.echo(f"  WATCH_LONGER:        {len(watch_longer)}")
    click.echo(f"  NO_MONK:             {len(no_monk)}")

    if build:
        click.echo(f"\n{'='*80}")
        click.echo("BUILD CANDIDATES — Ready for Monk config generation")
        click.echo(f"{'='*80}")
        _print_candidates(build)

    if proto:
        click.echo(f"\n{'='*80}")
        click.echo("PROTOTYPE CANDIDATES — Worth testing")
        click.echo(f"{'='*80}")
        _print_candidates(proto[:15])

    if watch_longer:
        click.echo(f"\n{'='*80}")
        click.echo(f"WATCH LONGER — {len(watch_longer)} families need more data")
        click.echo(f"{'='*80}")
        _print_candidates(watch_longer[:10])


@monk_group.command()
@click.option("--verbose", "-v", is_flag=True)
@click.option("--output", "-o", type=click.Path(), help="Write configs to JSON file.")
def generate(verbose: bool, output: str | None) -> None:
    """Generate Monk configs for all BUILD and PROTOTYPE candidates."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    from abbot.pipeline.distill import run_distillation
    from abbot.pipeline.features import compute_features
    from abbot.pipeline.state import classify_all
    from abbot.pipeline.candidates import discover_candidates
    from abbot.monk.config_gen import generate_configs

    # Full pipeline
    families = run_distillation()
    eligible = [f.series_ticker for f in families if f.decision.value != "ignore"]
    features = compute_features(prioritized_series=eligible)
    states = classify_all(features)
    candidates = discover_candidates(families, states)

    # Generate configs
    results = generate_configs(candidates)

    if not results:
        click.echo("No candidates eligible for config generation.")
        return

    click.echo(f"\nGenerated {len(results)} Monk configs:")
    click.echo(f"  {'Name':<35} {'Archetype':<18} {'Family':<25} {'Worthiness':>10}")
    click.echo("  " + "-" * 90)

    configs_data = []
    for candidate, config in results:
        click.echo(
            f"  {config.identity.name:<35} {config.identity.archetype.value:<18} "
            f"{candidate.series_ticker:<25} {candidate.monk_worthiness:10.2f}"
        )
        configs_data.append({
            "candidate": candidate.to_dict(),
            "config": config.model_dump(mode="json"),
        })

    if output:
        with open(output, "w") as f:
            json.dump(configs_data, f, indent=2, default=str)
        click.echo(f"\nConfigs written to {output}")


def _print_candidates(candidates) -> None:
    click.echo(
        f"\n  {'Worth':>5}  {'Decision':<20} {'Freq':<10} {'Domain':<10} "
        f"{'Events':>6} {'Vol':>8}  {'Archetype':<25} Series"
    )
    click.echo("  " + "-" * 110)
    for c in candidates:
        vol = f"{c.pattern.total_volume:,.0f}" if c.pattern.total_volume > 0 else "-"
        click.echo(
            f"  {c.monk_worthiness:5.2f}  {c.decision.value:<20} {c.frequency:<10} "
            f"{c.domain:<10} {c.pattern.event_count:>6} {vol:>8}  "
            f"{c.archetype_suggestion or '-':<25} {c.series_ticker}"
        )
