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


@app.on_event("startup")
async def startup_event():
    """Start the background scheduler when the web app launches."""
    from abbot.scheduler.jobs import start_scheduler
    start_scheduler()
    logger.info("Abbot started with background scheduler")


@app.on_event("shutdown")
async def shutdown_event():
    from abbot.scheduler.jobs import stop_scheduler
    stop_scheduler()

# Static files and templates
_base = Path(__file__).parent
app.mount("/static", StaticFiles(directory=_base / "static"), name="static")
templates = Jinja2Templates(directory=_base / "templates")


# --- Routes ---


@app.get("/", response_class=HTMLResponse)
async def overview(request: Request):
    """Main overview dashboard."""
    from abbot.monitor.performance import generate_daily_summary
    from sqlalchemy import select, func
    from sqlalchemy.orm import Session
    from abbot.db.engine import get_engine
    from abbot.db.models.pipeline import StoredMonkConfig, MonkTrade
    from abbot.db.models.raw import IngestLog

    summary = generate_daily_summary()
    engine = get_engine()

    with Session(engine) as session:
        # Monk counts
        all_configs = session.execute(select(StoredMonkConfig)).scalars().all()
        active = [c for c in all_configs if c.lifecycle_status in ("paper", "probation", "live", "scaled") and c.approval_status == "approved"]
        pending = [c for c in all_configs if c.approval_status == "pending"]
        paper = sum(1 for c in active if c.lifecycle_status == "paper")
        live = sum(1 for c in active if c.lifecycle_status in ("live", "scaled"))

        # Viable strategies (configs with blueprint)
        viable = sum(1 for c in all_configs if c.strategy_blueprint and c.strategy_blueprint.get("viable"))

        # Trade stats
        total_pnl = session.execute(
            select(func.coalesce(func.sum(MonkTrade.pnl), 0))
            .where(MonkTrade.status == "closed")
        ).scalar() or 0
        total_trades = session.execute(
            select(func.count()).select_from(MonkTrade)
        ).scalar() or 0
        open_positions = session.execute(
            select(func.count()).select_from(MonkTrade).where(MonkTrade.status == "open")
        ).scalar() or 0

        # Recent ingests
        recent_ingests = session.execute(
            select(IngestLog).order_by(IngestLog.started_at.desc()).limit(5)
        ).scalars().all()

    # State distribution — skip on overview (too expensive), show placeholder
    state_dist = {}

    # Family counts from DB (fast)
    from sqlalchemy import text as sql_text
    with Session(engine) as session:
        total_families = session.execute(sql_text("SELECT count(*) FROM raw_series_snapshots")).scalar() or 0
    prioritized = viable  # Approximation for overview

    return templates.TemplateResponse(request, "overview.html", {
        "summary": summary,
        "active_monks": len(active),
        "pending_monks": len(pending),
        "paper_monks": paper,
        "live_monks": live,
        "viable_strategies": viable,
        "total_pnl": float(total_pnl),
        "total_trades": total_trades,
        "open_positions": open_positions,
        "total_families": total_families,
        "prioritized": prioritized,
        "state_dist": state_dist,
        "recent_ingests": recent_ingests,
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


# --- Monks page ---


@app.get("/monks", response_class=HTMLResponse)
async def monks_page(request: Request):
    """Monk management: configs, positions, and performance."""
    from sqlalchemy import select, func
    from sqlalchemy.orm import Session
    from abbot.db.engine import get_engine
    from abbot.db.models.pipeline import StoredMonkConfig, MonkTrade

    engine = get_engine()
    with Session(engine) as session:
        configs = session.execute(
            select(StoredMonkConfig).order_by(StoredMonkConfig.created_at.desc())
        ).scalars().all()

        trades = session.execute(
            select(MonkTrade).order_by(MonkTrade.opened_at.desc()).limit(50)
        ).scalars().all()

        # Aggregate P&L per monk
        pnl_by_monk = dict(session.execute(
            select(MonkTrade.monk_name, func.sum(MonkTrade.pnl))
            .where(MonkTrade.status == "closed")
            .group_by(MonkTrade.monk_name)
        ).fetchall())

        # Trade counts per monk
        trades_by_monk = dict(session.execute(
            select(MonkTrade.monk_name, func.count())
            .group_by(MonkTrade.monk_name)
        ).fetchall())

        # Open positions per monk
        open_by_monk = dict(session.execute(
            select(MonkTrade.monk_name, func.count())
            .where(MonkTrade.status == "open")
            .group_by(MonkTrade.monk_name)
        ).fetchall())

    return templates.TemplateResponse(request, "monks.html", {
        "configs": configs,
        "trades": trades,
        "pnl_by_monk": pnl_by_monk,
        "trades_by_monk": trades_by_monk,
        "open_by_monk": open_by_monk,
    })


# --- Settings page ---


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Scoring configuration."""
    from abbot.config import get_scoring_config
    config = get_scoring_config(reload=True)
    return templates.TemplateResponse(request, "settings.html", {
        "scoring": config,
    })


# --- API endpoints for interactive controls ---


@app.post("/api/ingest/run")
async def api_ingest_run(request: Request):
    """Trigger a focused ingest cycle."""
    from abbot.scheduler.jobs import _run_focused_ingest
    import threading
    threading.Thread(target=_run_focused_ingest, daemon=True).start()
    return HTMLResponse('<div class="badge badge-green">Ingest started</div>')


@app.post("/api/pipeline/run")
async def api_pipeline_run(request: Request):
    """Trigger a full pipeline run."""
    from abbot.scheduler.jobs import _run_monks
    import threading
    threading.Thread(target=_run_monks, daemon=True).start()
    return HTMLResponse('<div class="badge badge-green">Monk scan started</div>')


@app.post("/api/monk/approve/{monk_id}")
async def api_monk_approve(monk_id: int):
    """Approve a Monk for paper trading."""
    from sqlalchemy.orm import Session as DBSession
    from abbot.db.engine import get_engine
    from abbot.db.models.pipeline import StoredMonkConfig
    engine = get_engine()
    with DBSession(engine) as session:
        config = session.get(StoredMonkConfig, monk_id)
        if config:
            config.approval_status = "approved"
            config.lifecycle_status = "paper"
            config.deployment_mode = "paper_only"
            session.commit()
            return HTMLResponse(f'<div class="badge badge-green">Approved</div>')
    return HTMLResponse('<div class="badge badge-red">Not found</div>')


@app.post("/api/monk/reject/{monk_id}")
async def api_monk_reject(monk_id: int):
    """Reject a Monk."""
    from sqlalchemy.orm import Session as DBSession
    from abbot.db.engine import get_engine
    from abbot.db.models.pipeline import StoredMonkConfig
    engine = get_engine()
    with DBSession(engine) as session:
        config = session.get(StoredMonkConfig, monk_id)
        if config:
            config.approval_status = "rejected"
            config.lifecycle_status = "retired"
            session.commit()
    return HTMLResponse('<div class="badge badge-red">Rejected</div>')


@app.post("/api/monk/pause/{monk_id}")
async def api_monk_pause(monk_id: int):
    """Pause a running Monk."""
    from sqlalchemy.orm import Session as DBSession
    from abbot.db.engine import get_engine
    from abbot.db.models.pipeline import StoredMonkConfig
    engine = get_engine()
    with DBSession(engine) as session:
        config = session.get(StoredMonkConfig, monk_id)
        if config:
            config.lifecycle_status = "paused"
            session.commit()
    return HTMLResponse('<div class="badge badge-yellow">Paused</div>')


@app.post("/api/monk/kill/{monk_id}")
async def api_monk_kill(monk_id: int):
    """Kill (retire) a Monk permanently."""
    from sqlalchemy.orm import Session as DBSession
    from abbot.db.engine import get_engine
    from abbot.db.models.pipeline import StoredMonkConfig
    engine = get_engine()
    with DBSession(engine) as session:
        config = session.get(StoredMonkConfig, monk_id)
        if config:
            config.lifecycle_status = "retired"
            config.approval_status = "revoked"
            session.commit()
    return HTMLResponse('<div class="badge badge-red">Killed</div>')


@app.post("/api/scoring/update")
async def api_scoring_update(request: Request):
    """Update scoring weights from form data."""
    from abbot.config import get_scoring_config, save_scoring_config, ScoringConfig

    form = await request.form()
    current = get_scoring_config(reload=True)

    # Update weights from form
    fw = current.family_worthiness.model_dump()
    for key in fw:
        val = form.get(f"fw_{key}")
        if val:
            fw[key] = float(val)
    current.family_worthiness = type(current.family_worthiness)(**fw)

    # Update thresholds
    for key in ["ignore_below", "prioritize_above"]:
        val = form.get(f"ft_{key}")
        if val:
            setattr(current.family_thresholds, key, float(val))

    save_scoring_config(current)
    return HTMLResponse('<div class="badge badge-green">Scoring config saved</div>')
