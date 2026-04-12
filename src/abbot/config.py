"""Application configuration.

Settings: from .env (secrets, DB URL)
ScoringConfig: from configs/scoring/v1.toml (weights, thresholds)

Usage:
    from abbot.config import get_settings, get_scoring_config
    settings = get_settings()
    scoring = get_scoring_config()
"""

import tomllib
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings

# Project root (where pyproject.toml lives)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Application settings from environment variables."""

    kalshi_api_key_id: str = ""
    kalshi_private_key_path: Path = Path("~/.kalshi/private_key.pem")
    database_url: str = ""
    app_name: str = "Abbot"
    debug: bool = False

    @property
    def database_url_sync(self) -> str:
        url = self.database_url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


class FamilyWorthinessWeights(BaseModel):
    repeatability: float = 0.25
    cadence: float = 0.15
    liquidity: float = 0.20
    spread: float = 0.15
    clarity: float = 0.10
    automation_fit: float = 0.15

    def as_dict(self) -> dict[str, float]:
        return self.model_dump()


class FamilyThresholds(BaseModel):
    ignore_below: float = 0.2
    watch_above: float = 0.2
    prioritize_above: float = 0.6


class StateThresholds(BaseModel):
    early_threshold: float = 0.2
    forming_threshold: float = 0.4
    actionable_threshold: float = 0.6
    exhausted_threshold: float = 0.8


class MonkCandidateCriteria(BaseModel):
    min_occurrences: int = 5
    min_recurrence_score: float = 0.4
    min_distinctness_score: float = 0.3


class ScoringConfig(BaseModel):
    """All scoring weights and thresholds, loaded from TOML."""

    family_worthiness: FamilyWorthinessWeights = FamilyWorthinessWeights()
    family_thresholds: FamilyThresholds = FamilyThresholds()
    state_classification: StateThresholds = StateThresholds()
    monk_candidate: MonkCandidateCriteria = MonkCandidateCriteria()


_scoring_config: ScoringConfig | None = None


def get_scoring_config(reload: bool = False) -> ScoringConfig:
    """Load scoring config from TOML. Cached after first load.

    Args:
        reload: Force reload from disk (e.g., after UI saves new weights).
    """
    global _scoring_config
    if _scoring_config is not None and not reload:
        return _scoring_config

    toml_path = PROJECT_ROOT / "configs" / "scoring" / "v1.toml"
    if toml_path.exists():
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        _scoring_config = ScoringConfig.model_validate(data)
    else:
        _scoring_config = ScoringConfig()

    return _scoring_config


def save_scoring_config(config: ScoringConfig) -> None:
    """Save scoring config back to TOML."""
    global _scoring_config
    toml_path = PROJECT_ROOT / "configs" / "scoring" / "v1.toml"

    lines = [
        "# Abbot Scoring Configuration v1",
        "# Weights and thresholds for the pipeline. Adjustable via UI or direct edit.",
        "",
        "[family_worthiness]",
    ]
    for k, v in config.family_worthiness.as_dict().items():
        lines.append(f"{k} = {v}")

    lines += ["", "[family_thresholds]"]
    for k, v in config.family_thresholds.model_dump().items():
        lines.append(f"{k} = {v}")

    lines += ["", "[state_classification]"]
    for k, v in config.state_classification.model_dump().items():
        lines.append(f"{k} = {v}")

    lines += ["", "[monk_candidate]"]
    for k, v in config.monk_candidate.model_dump().items():
        lines.append(f"{k} = {v}")

    lines.append("")
    toml_path.write_text("\n".join(lines))
    _scoring_config = config


@lru_cache
def get_settings() -> Settings:
    return Settings()
