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
    """Start the background scheduler and ensure cache table exists."""
    from abbot.pipeline.cache import ensure_cache_table
    ensure_cache_table()
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
    """Distillation results with domain filtering. Reads from cache."""
    from abbot.pipeline.cache import get_cached

    domain_filter = request.query_params.get("domain")
    cached = get_cached("distillation")

    if cached:
        data = cached["data"]
        prioritize = data.get("prioritize", [])
        watch = data.get("watch", [])
        domains = data.get("domains", [])
        total = data.get("total", 0)
        ignore_count = data.get("ignore_count", 0)

        if domain_filter:
            prioritize = [f for f in prioritize if f.get("domain") == domain_filter]
            watch = [f for f in watch if f.get("domain") == domain_filter]
    else:
        # Fallback: compute live
        from abbot.pipeline.distill import run_distillation
        families = run_distillation()
        domains = sorted(set(f.domain.value for f in families if f.decision.value != "ignore"))
        total = len(families)
        ignore_count = sum(1 for f in families if f.decision.value == "ignore")
        prioritize = [f.to_dict() for f in families if f.decision.value == "prioritize"]
        watch = [f.to_dict() for f in families if f.decision.value == "watch"]
        if domain_filter:
            prioritize = [f for f in prioritize if f.get("domain") == domain_filter]
            watch = [f for f in watch if f.get("domain") == domain_filter]

    return templates.TemplateResponse(request, "distill.html", {
        "prioritize": prioritize,
        "watch": watch[:30],
        "total": total,
        "ignore_count": ignore_count,
        "domains": domains,
        "domain_filter": domain_filter,
        "from_cache": cached is not None,
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
    """Market scan results. Reads from cache."""
    from abbot.pipeline.cache import get_cached

    state_filter = request.query_params.get("state")
    cached = get_cached("scan")

    if cached:
        data = cached["data"]
        all_states = data.get("states", [])
        dist = data.get("distribution", {})
        total = data.get("total", 0)
        features_map = data.get("features_map", {})

        if state_filter == "all":
            filtered = all_states
        elif state_filter:
            filtered = [s for s in all_states if s.get("state") == state_filter]
        else:
            filtered = all_states  # Already non-ignore from cache

        # Convert dicts to objects for template compatibility
        class StateView:
            pass
        state_objs = []
        for s in filtered[:100]:
            obj = StateView()
            obj.ticker = s.get("ticker", "")
            obj.event_ticker = s.get("event_ticker", "")
            obj.series_ticker = s.get("series_ticker")
            obj.score = s.get("score", 0)
            obj.confidence = s.get("confidence", 0)
            obj.reason_codes = s.get("reason_codes", [])
            # Create a mock state enum
            class MockState:
                def __init__(self, v): self.value = v
            obj.state = MockState(s.get("state", "ignore"))
            state_objs.append(obj)
    else:
        # Fallback: compute live
        from abbot.pipeline.features import compute_features
        from abbot.pipeline.state import classify_all
        features = compute_features()
        states = classify_all(features)
        features_map = {f.ticker: {"volume": f.volume, "last_price": f.last_price, "spread": f.spread} for f in features}
        dist = {}
        for s in states:
            dist[s.state.value] = dist.get(s.state.value, 0) + 1
        non_ignore = [s for s in states if s.state.value != "ignore"]
        non_ignore.sort(key=lambda s: s.score, reverse=True)
        state_objs = non_ignore[:100]
        total = len(states)

    return templates.TemplateResponse(request, "scan.html", {
        "states": state_objs,
        "distribution": dist,
        "total": total,
        "state_filter": state_filter,
        "features_map": features_map,
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


@app.get("/strategies", response_class=HTMLResponse)
async def strategies_page(request: Request):
    """Strategy discovery — what Abbot mined from the data."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from abbot.db.engine import get_engine
    from abbot.db.models.pipeline import StoredMonkConfig
    from abbot.pipeline.strategy import StrategyBlueprint

    engine = get_engine()
    with Session(engine) as session:
        configs = session.execute(
            select(StoredMonkConfig).where(StoredMonkConfig.strategy_blueprint.isnot(None))
        ).scalars().all()

    viable = []
    not_viable = []

    for c in configs:
        bp_data = c.strategy_blueprint
        if not bp_data:
            continue

        # Create a lightweight object for the template
        class BPView:
            pass

        bp = BPView()
        for key, val in bp_data.items():
            if key == "price_scan":
                # Convert price scan dicts to objects
                scans = []
                for p in (val or []):
                    ps = BPView()
                    for k2, v2 in p.items():
                        setattr(ps, k2, v2)
                    scans.append(ps)
                bp.price_scan = scans
            else:
                setattr(bp, key, val)

        # Flatten nested dicts with defaults
        strat = bp_data.get("strategy", {})
        bp.recommended_side = strat.get("side", "yes")
        bp.optimal_entry = strat.get("optimal_entry", 0.5)
        bp.entry_price_min = strat.get("entry_price_min", 0)
        bp.entry_price_max = strat.get("entry_price_max", 1)

        conf = bp_data.get("confidence", {})
        bp.sample_sufficient = conf.get("sample_sufficient", False)
        bp.train_test_consistent = conf.get("train_test_consistent", False)
        bp.statistical_significance = conf.get("p_value", 1.0)
        bp.time_consistency = conf.get("time_consistency", 0)
        train = bp_data.get("train", {})
        bp.train_win_rate = train.get("win_rate", 0)
        bp.train_total_pnl = train.get("pnl", 0)
        bp.train_profit_factor = train.get("profit_factor", 0)
        bp.train_trade_count = train.get("trades", 0)
        test = bp_data.get("test", {})
        bp.test_win_rate = test.get("win_rate", 0)
        bp.test_total_pnl = test.get("pnl", 0)
        bp.test_profit_factor = test.get("profit_factor", 0)
        bp.test_trade_count = test.get("trades", 0)
        bp.rejection_reason = bp_data.get("rejection_reason", "")
        bp.family_id = bp_data.get("family_id", "")
        bp.family_title = bp_data.get("family_title", "")
        bp.viable = bp_data.get("viable", False)
        sample = bp_data.get("sample", {})
        bp.total_settled = sample.get("total_settled", 0)
        bp.train_count = sample.get("train", 0)
        bp.test_count = sample.get("test", 0)

        # Sort price scan by EV and filter
        if hasattr(bp, 'price_scan'):
            bp.price_scan = sorted(
                [p for p in bp.price_scan if getattr(p, 'trade_count', 0) >= 10 and getattr(p, 'expected_value', 0) > 0],
                key=lambda p: getattr(p, 'expected_value', 0),
                reverse=True,
            )[:10]  # Top 10 only
        else:
            bp.price_scan = []

        if bp_data.get("viable"):
            viable.append(bp)
        else:
            not_viable.append(bp)

    return templates.TemplateResponse(request, "strategies.html", {
        "viable": viable,
        "not_viable": not_viable,
    })


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


@app.post("/api/cache/refresh")
async def api_cache_refresh():
    """Recompute and cache all pipeline results."""
    from abbot.pipeline.cache import run_and_cache_pipeline
    import threading
    threading.Thread(target=run_and_cache_pipeline, daemon=True).start()
    return HTMLResponse('<div class="badge badge-green">Cache refresh started</div>')


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
