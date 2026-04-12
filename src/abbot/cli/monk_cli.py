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


@monk_group.command()
@click.option("--config-file", "-f", required=True, type=click.Path(exists=True),
              help="Path to generated configs JSON file.")
@click.option("--index", "-i", default=0, show_default=True,
              help="Index of the config to test (0-based).")
@click.option("--verbose", "-v", is_flag=True)
def test(config_file: str, index: int, verbose: bool) -> None:
    """Run a replay test on a generated Monk config."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    from abbot.monk.testing import run_replay_test
    from abbot.types import MonkConfig

    with open(config_file) as f:
        configs_data = json.load(f)

    if index >= len(configs_data):
        click.echo(f"Index {index} out of range (0-{len(configs_data)-1})")
        return

    entry = configs_data[index]
    config = MonkConfig.model_validate(entry["config"])

    click.echo(f"Testing: {config.identity.name} (family: {config.identity.family_id})")
    report = run_replay_test(config)

    click.echo(f"\n{'='*60}")
    click.echo(f"TEST REPORT: {report.config_name}")
    click.echo(f"{'='*60}")
    click.echo(f"  Data: {report.snapshots_analyzed} snapshots, {report.markets_analyzed} markets, {report.data_days:.1f} days")
    click.echo(f"  Trades: {report.trade_count} (W:{report.win_count} L:{report.loss_count})")
    click.echo(f"  Win rate: {report.win_rate*100:.1f}%")
    click.echo(f"  P&L: ${report.total_pnl:.2f}")
    click.echo(f"  Avg gain: ${report.avg_gain:.2f}  |  Avg loss: ${report.avg_loss:.2f}")
    click.echo(f"  Max drawdown: ${report.max_drawdown:.2f}")
    click.echo(f"  Profit factor: {report.profit_factor:.2f}")
    click.echo(f"  ROI: {report.roi*100:.1f}%")
    click.echo(f"\n  VERDICT: {report.verdict.value.upper()} (confidence: {report.confidence:.0%})")
    click.echo(f"  Reasons: {', '.join(report.verdict_reasons)}")


@monk_group.command()
@click.option("--config-file", "-f", required=True, type=click.Path(exists=True))
@click.option("--verbose", "-v", is_flag=True)
def test_all(config_file: str, verbose: bool) -> None:
    """Run replay tests on all configs in a file and show summary."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    from abbot.monk.testing import run_replay_test
    from abbot.types import MonkConfig

    with open(config_file) as f:
        configs_data = json.load(f)

    click.echo(f"Testing {len(configs_data)} configs...\n")

    results = []
    for entry in configs_data:
        config = MonkConfig.model_validate(entry["config"])
        report = run_replay_test(config)
        results.append((config, report))

    click.echo(f"\n{'='*80}")
    click.echo(f"TEST SUMMARY — {len(results)} configs tested")
    click.echo(f"{'='*80}")
    click.echo(
        f"  {'Name':<35} {'Trades':>6} {'P&L':>8} {'WR':>5} {'PF':>5}  {'Verdict'}"
    )
    click.echo("  " + "-" * 80)

    for config, report in results:
        wr = f"{report.win_rate*100:.0f}%"
        pf = f"{report.profit_factor:.1f}" if report.profit_factor < 100 else "inf"
        click.echo(
            f"  {config.identity.name:<35} {report.trade_count:>6} "
            f"${report.total_pnl:>7.2f} {wr:>5} {pf:>5}  {report.verdict.value}"
        )

    verdicts = {}
    for _, r in results:
        verdicts[r.verdict.value] = verdicts.get(r.verdict.value, 0) + 1
    click.echo(f"\n  Verdicts: {', '.join(f'{v}={c}' for v, c in sorted(verdicts.items()))}")


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
