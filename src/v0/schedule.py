"""MLB schedule sync worker.

Pulls today's MLB schedule from the MLB Stats API and upserts
into the games table. Handles reschedules by updating first_pitch_utc.

Build spec ref: §5 "Schedule sync" worker.
"""

import logging
from datetime import datetime, timezone

import statsapi
from sqlalchemy import text
from sqlalchemy.orm import Session

from v0.db import get_engine

logger = logging.getLogger(__name__)


def sync_schedule(date: str | None = None) -> int:
    """Sync MLB schedule for the given date (YYYY-MM-DD) or today.

    Returns the number of games upserted.
    """
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    logger.info("Syncing MLB schedule for %s", date)
    games = statsapi.schedule(start_date=date, end_date=date)

    if not games:
        logger.info("No games found for %s", date)
        return 0

    engine = get_engine()
    count = 0

    with Session(engine) as session:
        for g in games:
            game_id = str(g["game_id"])
            game_date = g["game_date"]

            # Parse the game datetime — statsapi returns ISO format
            game_datetime = g.get("game_datetime")
            if game_datetime:
                if isinstance(game_datetime, str):
                    first_pitch = datetime.fromisoformat(
                        game_datetime.replace("Z", "+00:00")
                    )
                else:
                    first_pitch = game_datetime
            else:
                logger.warning("No game_datetime for game %s, skipping", game_id)
                continue

            home_abbr = g.get("home_name", "???")
            away_abbr = g.get("away_name", "???")

            # Map status
            status_raw = g.get("status", "").lower()
            if "final" in status_raw:
                status = "final"
            elif "progress" in status_raw or "live" in status_raw:
                status = "live"
            elif "postponed" in status_raw:
                status = "postponed"
            elif "cancelled" in status_raw or "canceled" in status_raw:
                status = "cancelled"
            else:
                status = "scheduled"

            home_score = g.get("home_score")
            away_score = g.get("away_score")

            # Determine winner
            winning_team = None
            if status == "final" and home_score is not None and away_score is not None:
                if home_score > away_score:
                    winning_team = home_abbr
                elif away_score > home_score:
                    winning_team = away_abbr

            session.execute(
                text("""
                    INSERT INTO games (
                        game_id, game_date, first_pitch_utc,
                        home_team_abbr, away_team_abbr,
                        home_team_name, away_team_name,
                        status, home_score, away_score, winning_team_abbr
                    ) VALUES (
                        :game_id, :game_date, :first_pitch,
                        :home_abbr, :away_abbr,
                        :home_name, :away_name,
                        :status, :home_score, :away_score, :winning_team
                    )
                    ON CONFLICT (game_id) DO UPDATE SET
                        first_pitch_utc = EXCLUDED.first_pitch_utc,
                        status = EXCLUDED.status,
                        home_score = EXCLUDED.home_score,
                        away_score = EXCLUDED.away_score,
                        winning_team_abbr = EXCLUDED.winning_team_abbr,
                        updated_at = NOW()
                """),
                {
                    "game_id": game_id,
                    "game_date": game_date,
                    "first_pitch": first_pitch,
                    "home_abbr": home_abbr,
                    "away_abbr": away_abbr,
                    "home_name": g.get("home_name", home_abbr),
                    "away_name": g.get("away_name", away_abbr),
                    "status": status,
                    "home_score": home_score,
                    "away_score": away_score,
                    "winning_team": winning_team,
                },
            )
            count += 1

        session.commit()

    logger.info("Synced %d games for %s", count, date)
    return count
