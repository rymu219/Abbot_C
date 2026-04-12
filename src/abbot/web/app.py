"""Phase 14: Abbot Web UI.

FastAPI app with server-rendered HTML (Jinja2 + HTMX).
Calm, legible, operator-first. No external tools needed.
"""

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

app = FastAPI(title="Abbot", docs_url=None, redoc_url=None)

# Static files and templates
_base = Path(__file__).parent
app.mount("/static", StaticFiles(directory=_base / "static"), name="static")
templates = Jinja2Templates(directory=_base / "templates")


# --- Routes ---


@app.get("/", response_class=HTMLResponse)
async def overview(request: Request):
    """Main overview dashboard."""
    from abbot.monitor.performance import generate_daily_summary

    summary = generate_daily_summary()
    return templates.TemplateResponse(request, "overview.html", {
        "summary": summary,
    })


@app.get("/distill", response_class=HTMLResponse)
async def distill_page(request: Request):
    """Distillation results."""
    from abbot.pipeline.distill import run_distillation

    families = run_distillation()
    prioritize = [f for f in families if f.decision.value == "prioritize"]
    watch = [f for f in families if f.decision.value == "watch"]

    return templates.TemplateResponse(request, "distill.html", {
        "prioritize": prioritize,
        "watch": watch[:30],
        "total": len(families),
        "ignore_count": sum(1 for f in families if f.decision.value == "ignore"),
    })


@app.get("/candidates", response_class=HTMLResponse)
async def candidates_page(request: Request):
    """Monk candidates."""
    from abbot.pipeline.distill import run_distillation
    from abbot.pipeline.features import compute_features
    from abbot.pipeline.state import classify_all
    from abbot.pipeline.candidates import discover_candidates

    families = run_distillation()
    eligible = [f.series_ticker for f in families if f.decision.value != "ignore"]
    features = compute_features(prioritized_series=eligible)
    states = classify_all(features)
    candidates = discover_candidates(families, states)

    build = [c for c in candidates if c.decision.value == "build_candidate"]
    proto = [c for c in candidates if c.decision.value == "prototype_candidate"]

    return templates.TemplateResponse(request, "candidates.html", {
        "build": build,
        "prototype": proto[:20],
        "total": len(candidates),
    })


@app.get("/activity", response_class=HTMLResponse)
async def activity_page(request: Request):
    """Activity and audit trail."""
    from abbot.monitor.events import get_recent_events

    try:
        events = get_recent_events(limit=50)
    except Exception:
        events = []

    # Also get ingest log
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from abbot.db.engine import get_engine
    from abbot.db.models.raw import IngestLog

    engine = get_engine()
    with Session(engine) as session:
        ingests = session.execute(
            select(IngestLog).order_by(IngestLog.started_at.desc()).limit(20)
        ).scalars().all()

    return templates.TemplateResponse(request, "activity.html", {
        "events": events,
        "ingests": ingests,
    })


@app.get("/scan", response_class=HTMLResponse)
async def scan_page(request: Request):
    """Current market scan results."""
    from abbot.pipeline.features import compute_features
    from abbot.pipeline.state import classify_all

    features = compute_features()
    states = classify_all(features)

    non_ignore = [s for s in states if s.state.value != "ignore"]
    non_ignore.sort(key=lambda s: s.score, reverse=True)

    dist = {}
    for s in states:
        dist[s.state.value] = dist.get(s.state.value, 0) + 1

    return templates.TemplateResponse(request, "scan.html", {
        "states": non_ignore[:50],
        "distribution": dist,
        "total": len(states),
    })
