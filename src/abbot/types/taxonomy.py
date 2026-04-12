"""Hierarchy: Universe -> Platform -> Domain -> Family -> Instrument.

Platform and Domain are fixed enums (known universe).
Family and Instrument are dynamic models (discovered by the system).
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class Platform(StrEnum):
    """Supported trading platforms. Frozen to Kalshi for MVP."""

    KALSHI = "kalshi"


class Domain(StrEnum):
    """Broad market categories within a platform.

    This initial set covers Kalshi's known domains. New values are added
    during Phase 5 (distillation) as structure is discovered.
    """

    ECONOMICS = "economics"
    POLITICS = "politics"
    WEATHER = "weather"
    CRYPTO = "crypto"
    FINANCE = "finance"
    SCIENCE = "science"
    CULTURE = "culture"
    TECH = "tech"
    SPORTS = "sports"
    OTHER = "other"


class Family(BaseModel):
    """A repeatable market structure within a domain.

    Families are discovered by the distillation engine (Phase 5), not
    predefined. Examples: "monthly CPI prints", "fed rate decisions",
    "hurricane landfalls".
    """

    family_id: str
    name: str
    domain: Domain
    platform: Platform = Platform.KALSHI
    description: str = ""
    created_at: datetime | None = None


class Instrument(BaseModel):
    """A single Kalshi market/contract.

    Maps to a specific tradable market on the platform.
    """

    ticker: str
    event_ticker: str | None = None
    series_ticker: str | None = None
    title: str = ""
    family_id: str | None = None  # None until classified by distillation
    platform: Platform = Platform.KALSHI
