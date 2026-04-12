"""SQLAlchemy ORM models for Abbot.

All models inherit from Base. Import Base for Alembic autogenerate support.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all Abbot ORM models."""

    pass


# Import all model modules so they register with Base.metadata
from abbot.db.models import raw  # noqa: F401, E402
from abbot.db.models import pipeline  # noqa: F401, E402
from abbot.monitor import events  # noqa: F401, E402  (AuditEvent model)
