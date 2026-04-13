"""Reconciliation checks.

Detects gaps: eligible games without bets, and bets without settlements
that should have settled by now. Log-only — does not auto-repair.

Build spec ref: §5 "Reconciliation check" worker.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from v0.db import get_engine

logger = logging.getLogger(__name__)


def run_reconciliation() -> dict:
    """Run reconciliation checks. Returns summary of findings."""
    engine = get_engine()
    now = datetime.now(timezone.utc)
    findings = {"missed_bets": [], "stale_settlements": []}

    with Session(engine) as session:
        # 1. Games that should have a bet but don't
        # (scheduled games where T-30 has passed but no bet exists)
        missed = session.execute(
            text("""
                SELECT g.game_id, g.first_pitch_utc,
                       g.home_team_abbr, g.away_team_abbr
                FROM games g
                LEFT JOIN bets b ON b.game_id = g.game_id
                WHERE g.status = 'scheduled'
                  AND g.first_pitch_utc - INTERVAL '30 minutes' < :now
                  AND b.bet_id IS NULL
            """),
            {"now": now},
        ).fetchall()

        for game_id, pitch, home, away in missed:
            findings["missed_bets"].append({
                "game_id": game_id,
                "first_pitch": str(pitch),
                "matchup": f"{away} @ {home}",
            })

        # 2. Bets that should have settled but haven't
        # (game is final but no settlement row, and it's been > 4 hours since pitch)
        stale_cutoff = now - timedelta(hours=4)
        stale = session.execute(
            text("""
                SELECT b.bet_id, b.game_id, b.team_abbr, g.first_pitch_utc
                FROM bets b
                JOIN games g ON g.game_id = b.game_id
                LEFT JOIN settlements s ON s.bet_id = b.bet_id
                WHERE s.settlement_id IS NULL
                  AND g.status = 'final'
                  AND g.first_pitch_utc < :cutoff
            """),
            {"cutoff": stale_cutoff},
        ).fetchall()

        for bet_id, game_id, team, pitch in stale:
            findings["stale_settlements"].append({
                "bet_id": bet_id,
                "game_id": game_id,
                "team": team,
                "first_pitch": str(pitch),
            })

    if findings["missed_bets"]:
        logger.warning(
            "RECONCILIATION: %d games missed the decision window",
            len(findings["missed_bets"]),
        )
        for m in findings["missed_bets"]:
            logger.warning("  Missed: %s — %s", m["game_id"], m["matchup"])

    if findings["stale_settlements"]:
        logger.warning(
            "RECONCILIATION: %d bets awaiting settlement (game final >4h ago)",
            len(findings["stale_settlements"]),
        )
        for s in findings["stale_settlements"]:
            logger.warning("  Stale: bet=%s game=%s team=%s", s["bet_id"], s["game_id"], s["team"])

    if not findings["missed_bets"] and not findings["stale_settlements"]:
        logger.info("RECONCILIATION: all clear")

    return findings
