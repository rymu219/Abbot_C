"""Phase 5: Distillation Engine.

Reduces raw Kalshi data into structured, scored families.

Pipeline:
1. Map Kalshi categories → Abbot domains
2. Map Kalshi series → Abbot families (series IS the family)
3. Filter out non-viable series (one-off, no recurring structure)
4. Compute viability scores for each family
5. Assign family decisions: Ignore / Watch / Prioritize

The distillation runs against the latest ingested data and produces
a scored family table that downstream phases (6-8) consume.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from abbot.db.engine import get_engine
from abbot.types import Domain, FamilyDecision, Platform

logger = logging.getLogger(__name__)


# --- Category → Domain mapping ---

CATEGORY_TO_DOMAIN: dict[str, Domain] = {
    "Economics": Domain.ECONOMICS,
    "Financials": Domain.FINANCE,
    "Politics": Domain.POLITICS,
    "Elections": Domain.POLITICS,
    "Climate and Weather": Domain.WEATHER,
    "Crypto": Domain.CRYPTO,
    "Science and Technology": Domain.TECH,
    "Companies": Domain.FINANCE,
    "Entertainment": Domain.CULTURE,
    "Sports": Domain.SPORTS,
    "Mentions": Domain.CULTURE,
    "World": Domain.OTHER,
    "Health": Domain.SCIENCE,
    "Social": Domain.CULTURE,
    "Transportation": Domain.OTHER,
    "Education": Domain.OTHER,
    "Exotics": Domain.OTHER,
    "": Domain.OTHER,
}


def map_domain(kalshi_category: str) -> Domain:
    """Map a Kalshi category string to an Abbot Domain."""
    return CATEGORY_TO_DOMAIN.get(kalshi_category, Domain.OTHER)


# --- Frequency scoring ---

# Higher = better for automation (more repeatable, more data points)
FREQUENCY_SCORES: dict[str, float] = {
    "fifteen_min": 1.0,  # Highest cadence
    "hourly": 0.95,
    "daily": 0.85,
    "weekly": 0.70,
    "monthly": 0.55,
    "annual": 0.20,      # Too slow for meaningful automation
    "custom": 0.10,      # Irregular, hard to automate
    "one_off": 0.0,      # Not recurring — skip
}


# --- Distillation result model ---


class DistilledFamily:
    """A scored, classified family produced by distillation."""

    def __init__(
        self,
        series_ticker: str,
        title: str,
        kalshi_category: str,
        domain: Domain,
        frequency: str,
        tags: list[str],
        event_count: int,
        market_count: int,
        total_volume: float,
        avg_open_interest: float,
        avg_spread: float,
        markets_with_volume: int,
    ):
        self.series_ticker = series_ticker
        self.title = title
        self.kalshi_category = kalshi_category
        self.domain = domain
        self.frequency = frequency
        self.tags = tags
        self.event_count = event_count
        self.market_count = market_count
        self.total_volume = total_volume
        self.avg_open_interest = avg_open_interest
        self.avg_spread = avg_spread
        self.markets_with_volume = markets_with_volume

        # Computed scores
        self.repeatability_score: float = 0.0
        self.cadence_score: float = 0.0
        self.liquidity_score: float = 0.0
        self.spread_score: float = 0.0
        self.clarity_score: float = 0.0
        self.automation_score: float = 0.0
        self.composite_score: float = 0.0
        self.decision: FamilyDecision = FamilyDecision.IGNORE
        self.reason_codes: list[str] = []

    def to_dict(self) -> dict:
        return {
            "series_ticker": self.series_ticker,
            "title": self.title,
            "kalshi_category": self.kalshi_category,
            "domain": str(self.domain),
            "frequency": self.frequency,
            "tags": self.tags,
            "event_count": self.event_count,
            "market_count": self.market_count,
            "total_volume": self.total_volume,
            "avg_open_interest": self.avg_open_interest,
            "avg_spread": self.avg_spread,
            "markets_with_volume": self.markets_with_volume,
            "scores": {
                "repeatability": round(self.repeatability_score, 3),
                "cadence": round(self.cadence_score, 3),
                "liquidity": round(self.liquidity_score, 3),
                "spread": round(self.spread_score, 3),
                "clarity": round(self.clarity_score, 3),
                "automation": round(self.automation_score, 3),
                "composite": round(self.composite_score, 3),
            },
            "decision": str(self.decision),
            "reason_codes": self.reason_codes,
        }


# --- Scoring functions ---


def score_family(family: DistilledFamily, weights: dict | None = None) -> None:
    """Compute all sub-scores and composite score for a family.

    Modifies the family in place.
    """
    if weights is None:
        from abbot.config import get_scoring_config
        sc = get_scoring_config()
        weights = sc.family_worthiness.as_dict()

    # Repeatability: based on event count (more events = more recurring)
    if family.event_count >= 20:
        family.repeatability_score = 1.0
    elif family.event_count >= 10:
        family.repeatability_score = 0.8
    elif family.event_count >= 5:
        family.repeatability_score = 0.6
    elif family.event_count >= 2:
        family.repeatability_score = 0.3
    else:
        family.repeatability_score = 0.1

    # Cadence: from frequency
    family.cadence_score = FREQUENCY_SCORES.get(family.frequency, 0.1)

    # Liquidity: based on total volume across markets
    if family.total_volume >= 10000:
        family.liquidity_score = 1.0
    elif family.total_volume >= 1000:
        family.liquidity_score = 0.7
    elif family.total_volume >= 100:
        family.liquidity_score = 0.4
    elif family.total_volume > 0:
        family.liquidity_score = 0.2
    else:
        family.liquidity_score = 0.0

    # Spread: lower spread = better (tighter market)
    if family.avg_spread <= 0:
        family.spread_score = 0.0  # No data
    elif family.avg_spread <= 0.05:
        family.spread_score = 1.0
    elif family.avg_spread <= 0.10:
        family.spread_score = 0.7
    elif family.avg_spread <= 0.20:
        family.spread_score = 0.4
    else:
        family.spread_score = 0.2

    # Clarity: does the series have a clear title and category?
    clarity = 0.5  # base
    if family.title and len(family.title) > 5:
        clarity += 0.2
    if family.kalshi_category and family.kalshi_category != "":
        clarity += 0.2
    if family.tags:
        clarity += 0.1
    family.clarity_score = min(clarity, 1.0)

    # Automation fit: combines cadence + repeatability + liquidity signal
    if family.frequency == "one_off":
        family.automation_score = 0.0
    else:
        family.automation_score = (
            0.4 * family.cadence_score
            + 0.3 * family.repeatability_score
            + 0.3 * (1.0 if family.markets_with_volume > 0 else 0.0)
        )

    # Composite
    family.composite_score = (
        weights["repeatability"] * family.repeatability_score
        + weights["cadence"] * family.cadence_score
        + weights["liquidity"] * family.liquidity_score
        + weights["spread"] * family.spread_score
        + weights["clarity"] * family.clarity_score
        + weights.get("automation_fit", weights.get("automation", 0.15)) * family.automation_score
    )


def assign_decision(
    family: DistilledFamily,
    ignore_below: float | None = None,
    prioritize_above: float | None = None,
) -> None:
    """Assign a family decision based on composite score.

    Modifies the family in place.
    """
    if ignore_below is None or prioritize_above is None:
        from abbot.config import get_scoring_config
        sc = get_scoring_config()
        if ignore_below is None:
            ignore_below = sc.family_thresholds.ignore_below
        if prioritize_above is None:
            prioritize_above = sc.family_thresholds.prioritize_above

    family.reason_codes = []

    # Hard filters: one-off series are always ignored
    if family.frequency == "one_off":
        family.decision = FamilyDecision.IGNORE
        family.reason_codes.append("one_off_frequency")
        return

    # Hard filter: no events = nothing to analyze
    if family.event_count == 0:
        family.decision = FamilyDecision.IGNORE
        family.reason_codes.append("no_events")
        return

    if family.composite_score < ignore_below:
        family.decision = FamilyDecision.IGNORE
        family.reason_codes.append(f"low_composite_{family.composite_score:.2f}")
    elif family.composite_score >= prioritize_above:
        family.decision = FamilyDecision.PRIORITIZE
        if family.liquidity_score >= 0.7:
            family.reason_codes.append("strong_liquidity")
        if family.cadence_score >= 0.7:
            family.reason_codes.append("high_cadence")
        if family.repeatability_score >= 0.6:
            family.reason_codes.append("repeatable")
    else:
        family.decision = FamilyDecision.WATCH
        family.reason_codes.append(f"moderate_composite_{family.composite_score:.2f}")


# --- Main distillation pipeline ---


def run_distillation() -> list[DistilledFamily]:
    """Run the full distillation pipeline against the latest ingested data.

    Returns a list of scored DistilledFamily objects.
    """
    engine = get_engine()

    with Session(engine) as session:
        # Step 1: Load all series (the foundation of family discovery)
        series_rows = session.execute(text("""
            SELECT DISTINCT ON (series_ticker)
                series_ticker, data
            FROM raw_series_snapshots
            ORDER BY series_ticker, ingested_at DESC
        """)).fetchall()

        logger.info("Loaded %d unique series", len(series_rows))

        # Step 2: Count events per series
        event_counts = dict(session.execute(text("""
            SELECT series_ticker, count(*)
            FROM raw_event_snapshots
            WHERE series_ticker IS NOT NULL
            GROUP BY series_ticker
        """)).fetchall())

        # Step 3: Aggregate market stats per series (via event_ticker prefix)
        # Markets link to events, events link to series
        # We use the event_ticker → series_ticker mapping from events
        market_stats_rows = session.execute(text("""
            SELECT
                e.series_ticker,
                count(m.id) as market_count,
                coalesce(sum((m.data->>'volume_fp')::float), 0) as total_volume,
                coalesce(avg((m.data->>'open_interest_fp')::float), 0) as avg_oi,
                coalesce(avg(
                    (m.data->>'yes_ask_dollars')::float - (m.data->>'yes_bid_dollars')::float
                ), 0) as avg_spread,
                count(CASE WHEN (m.data->>'volume_fp')::float > 0 THEN 1 END) as with_volume
            FROM raw_market_snapshots m
            JOIN raw_event_snapshots e ON m.event_ticker = e.event_ticker
            WHERE e.series_ticker IS NOT NULL
            GROUP BY e.series_ticker
        """)).fetchall()
        market_stats = {
            row[0]: (row[1], row[2], row[3], row[4], row[5])
            for row in market_stats_rows
        }

        logger.info("Computed market stats for %d series", len(market_stats))

    # Step 4: Build DistilledFamily objects
    families = []
    for series_ticker, data in series_rows:
        category = data.get("category", "")
        frequency = data.get("frequency", "custom")
        tags = data.get("tags", []) or []
        title = data.get("title", "")

        stats = market_stats.get(series_ticker, (0, 0.0, 0.0, 0.0, 0))
        if isinstance(stats, tuple):
            mkt_count, total_vol, avg_oi, avg_spread, with_vol = stats
        else:
            # dict from row
            mkt_count = stats

        family = DistilledFamily(
            series_ticker=series_ticker,
            title=title,
            kalshi_category=category,
            domain=map_domain(category),
            frequency=frequency,
            tags=tags,
            event_count=event_counts.get(series_ticker, 0),
            market_count=mkt_count if isinstance(mkt_count, int) else 0,
            total_volume=total_vol if isinstance(stats, tuple) else 0.0,
            avg_open_interest=avg_oi if isinstance(stats, tuple) else 0.0,
            avg_spread=avg_spread if isinstance(stats, tuple) else 0.0,
            markets_with_volume=with_vol if isinstance(stats, tuple) else 0,
        )

        # Step 5: Score
        score_family(family)

        # Step 6: Assign decision
        assign_decision(family)

        families.append(family)

    # Sort by composite score descending
    families.sort(key=lambda f: f.composite_score, reverse=True)

    # Log summary
    decisions = {}
    for f in families:
        decisions[f.decision] = decisions.get(f.decision, 0) + 1

    logger.info(
        "Distillation complete: %d families — %s",
        len(families),
        ", ".join(f"{d.value}={c}" for d, c in sorted(decisions.items(), key=lambda x: -x[1])),
    )

    return families
