"""SQLAlchemy engine and session setup.

Connects to Neon PostgreSQL via DATABASE_URL from .env.
Uses psycopg (v3) driver.

Usage:
    from abbot.db.engine import get_engine, get_session

    engine = get_engine()
    with get_session() as session:
        session.execute(...)
"""

from functools import lru_cache

from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import Session, sessionmaker

from abbot.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """Create and cache the SQLAlchemy engine."""
    settings = get_settings()
    return create_engine(
        settings.database_url_sync,
        pool_pre_ping=True,
        echo=settings.debug,
    )


def get_session() -> Session:
    """Create a new database session."""
    engine = get_engine()
    factory = sessionmaker(bind=engine)
    return factory()
