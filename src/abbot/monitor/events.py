"""Phase 12: Event types and recording.

Central audit trail for everything that happens in Abbot.
Every significant action produces an event that is stored
and queryable. Surface significance, preserve everything.
"""

import json
import logging
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import BigInteger, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from abbot.db.models import Base
from abbot.db.engine import get_engine

logger = logging.getLogger(__name__)


class EventType(StrEnum):
    """All event types in the system."""

    # Ingestion
    INGEST_STARTED = "ingest_started"
    INGEST_COMPLETED = "ingest_completed"
    INGEST_FAILED = "ingest_failed"

    # Distillation
    DISTILL_RUN = "distill_run"
    FAMILY_DECISION = "family_decision"

    # Scanning
    SCAN_RUN = "scan_run"
    STATE_CHANGE = "state_change"
    TRANSITION_DETECTED = "transition_detected"

    # Candidates
    CANDIDATE_DISCOVERED = "candidate_discovered"
    CANDIDATE_PROMOTED = "candidate_promoted"

    # Monk lifecycle
    CONFIG_GENERATED = "config_generated"
    TEST_COMPLETED = "test_completed"
    MONK_APPROVED = "monk_approved"
    MONK_REJECTED = "monk_rejected"
    MONK_DEPLOYED = "monk_deployed"
    MONK_PAUSED = "monk_paused"
    MONK_KILLED = "monk_killed"
    MONK_RETURNED_TO_PAPER = "monk_returned_to_paper"

    # Execution
    ORDER_PLACED = "order_placed"
    ORDER_FILLED = "order_filled"
    ORDER_CANCELED = "order_canceled"
    ORDER_FAILED = "order_failed"

    # Risk
    RISK_ALERT = "risk_alert"
    STOP_TRIGGERED = "stop_triggered"

    # System
    SYSTEM_ERROR = "system_error"
    SCHEDULE_RUN = "schedule_run"


class EventSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AuditEvent(Base):
    """Persistent audit trail event."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    source: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g., "monk-01", "ingest", "system"
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String(32), nullable=True)  # "monk", "market", "family"
    entity_id: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


def record_event(
    event_type: EventType,
    source: str,
    message: str,
    severity: EventSeverity = EventSeverity.INFO,
    data: dict | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> None:
    """Record an audit event to the database."""
    engine = get_engine()
    with Session(engine) as session:
        event = AuditEvent(
            event_type=event_type.value,
            severity=severity.value,
            source=source,
            message=message,
            data=data,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        session.add(event)
        session.commit()

    if severity in (EventSeverity.WARNING, EventSeverity.ERROR, EventSeverity.CRITICAL):
        logger.warning("[%s] %s: %s", event_type.value, source, message)
    else:
        logger.debug("[%s] %s: %s", event_type.value, source, message)


def get_recent_events(
    limit: int = 50,
    event_type: str | None = None,
    severity: str | None = None,
    entity_id: str | None = None,
) -> list[AuditEvent]:
    """Query recent audit events."""
    from sqlalchemy import select

    engine = get_engine()
    with Session(engine) as session:
        stmt = select(AuditEvent).order_by(AuditEvent.created_at.desc())

        if event_type:
            stmt = stmt.where(AuditEvent.event_type == event_type)
        if severity:
            stmt = stmt.where(AuditEvent.severity == severity)
        if entity_id:
            stmt = stmt.where(AuditEvent.entity_id == entity_id)

        stmt = stmt.limit(limit)
        return list(session.execute(stmt).scalars().all())
