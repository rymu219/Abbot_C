"""Pipeline result cache.

Stores pipeline outputs in the DB so pages load instantly.
Results are recomputed when new data arrives (after ingest).

Cache entries:
  - distillation: scored families
  - scan: features + state classifications
  - candidates: monk candidates

Each entry stores: result JSON, computed_at timestamp, ingest_id
that triggered the computation.
"""

import json
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from abbot.db.engine import get_engine

logger = logging.getLogger(__name__)

# In-memory cache for ultra-fast repeated access within same process
_memory_cache: dict[str, dict] = {}


def get_cached(cache_key: str) -> dict | None:
    """Get cached pipeline result. Returns None if no cache exists."""
    # Check memory first
    if cache_key in _memory_cache:
        return _memory_cache[cache_key]

    # Check DB
    engine = get_engine()
    with Session(engine) as session:
        row = session.execute(text(
            "SELECT result_data, computed_at FROM pipeline_cache "
            "WHERE cache_key = :key ORDER BY computed_at DESC LIMIT 1"
        ), {"key": cache_key}).first()

    if row:
        data = {"data": row[0], "computed_at": str(row[1])}
        _memory_cache[cache_key] = data
        return data

    return None


def set_cached(cache_key: str, data: dict, ttl_seconds: int = 900) -> None:
    """Store a pipeline result in the cache.

    Args:
        cache_key: Unique key (e.g., "distillation", "scan")
        data: The result data (must be JSON-serializable)
        ttl_seconds: Not enforced server-side; used for client hints
    """
    engine = get_engine()
    now = datetime.now(timezone.utc)

    with Session(engine) as session:
        # Upsert: delete old, insert new
        session.execute(text(
            "DELETE FROM pipeline_cache WHERE cache_key = :key"
        ), {"key": cache_key})
        session.execute(text(
            "INSERT INTO pipeline_cache (cache_key, result_data, computed_at) "
            "VALUES (:key, :data, :ts)"
        ), {"key": cache_key, "data": json.dumps(data, default=str), "ts": now})
        session.commit()

    _memory_cache[cache_key] = {"data": data, "computed_at": str(now)}
    logger.debug("Cached %s (%d bytes)", cache_key, len(json.dumps(data, default=str)))


def invalidate(cache_key: str | None = None) -> None:
    """Invalidate cache. If key is None, invalidate everything."""
    global _memory_cache

    engine = get_engine()
    with Session(engine) as session:
        if cache_key:
            session.execute(text(
                "DELETE FROM pipeline_cache WHERE cache_key = :key"
            ), {"key": cache_key})
            _memory_cache.pop(cache_key, None)
        else:
            session.execute(text("DELETE FROM pipeline_cache"))
            _memory_cache = {}
        session.commit()

    logger.info("Cache invalidated: %s", cache_key or "ALL")


def ensure_cache_table() -> None:
    """Create the cache table if it doesn't exist."""
    engine = get_engine()
    with Session(engine) as session:
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS pipeline_cache (
                cache_key VARCHAR(64) PRIMARY KEY,
                result_data JSONB NOT NULL,
                computed_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        session.commit()


def run_and_cache_pipeline() -> dict:
    """Run the full pipeline and cache all results. Called after ingest."""
    logger.info("Running full pipeline for cache...")
    t0 = time.time()

    # Distillation
    from abbot.pipeline.distill import run_distillation
    families = run_distillation()
    distill_data = {
        "total": len(families),
        "prioritize": [f.to_dict() for f in families if f.decision.value == "prioritize"],
        "watch": [f.to_dict() for f in families if f.decision.value == "watch"],
        "ignore_count": sum(1 for f in families if f.decision.value == "ignore"),
        "domains": sorted(set(f.domain.value for f in families if f.decision.value != "ignore")),
    }
    set_cached("distillation", distill_data)

    # Features + State
    from abbot.pipeline.features import compute_features
    from abbot.pipeline.state import classify_all
    features = compute_features()
    states = classify_all(features)

    dist = {}
    for s in states:
        dist[s.state.value] = dist.get(s.state.value, 0) + 1

    features_map = {
        f.ticker: {"volume": f.volume, "last_price": f.last_price, "spread": f.spread}
        for f in features
    }

    non_ignore = [s for s in states if s.state.value != "ignore"]
    non_ignore.sort(key=lambda s: s.score, reverse=True)

    scan_data = {
        "total": len(states),
        "distribution": dist,
        "states": [
            {
                "ticker": s.ticker,
                "event_ticker": s.event_ticker,
                "series_ticker": s.series_ticker,
                "state": s.state.value,
                "confidence": s.confidence,
                "score": s.score,
                "reason_codes": s.reason_codes,
            }
            for s in non_ignore[:500]  # Top 500 non-ignore
        ],
        "features_map": {
            k: v for k, v in list(features_map.items())[:5000]  # Limit size
        },
    }
    set_cached("scan", scan_data)

    # Candidates
    from abbot.pipeline.candidates import discover_candidates
    candidates = discover_candidates(families, states)
    candidates_data = {
        "total": len(candidates),
        "build": [c.to_dict() for c in candidates if c.decision.value == "build_candidate"],
        "prototype": [c.to_dict() for c in candidates if c.decision.value == "prototype_candidate"],
        "watch": [c.to_dict() for c in candidates if c.decision.value == "watch_longer"],
    }
    set_cached("candidates", candidates_data)

    elapsed = time.time() - t0
    logger.info("Pipeline cached in %.1fs", elapsed)

    return {"elapsed": elapsed, "markets": len(states), "families": len(families)}
