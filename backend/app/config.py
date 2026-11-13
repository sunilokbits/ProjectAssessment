from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]


def _env(name: str, default: str):
    return Field(default_factory=lambda: os.getenv(name, default))


class Settings(BaseModel):
    """Environment is read when Settings() is instantiated (not at import time)."""

    database_url: str = _env("PAT_DATABASE_URL", f"sqlite:///{(ROOT / 'backend' / 'assessment.db').as_posix()}")
    domain_packs_dir: Path = Field(default_factory=lambda: Path(os.getenv("PAT_DOMAIN_PACKS_DIR", str(ROOT / "domain_packs"))))
    # Claude model used for optional AI features (detection, clarification questions).
    ai_model: str = _env("PAT_AI_MODEL", "claude-opus-5-5")
    cors_origins: list[str] = Field(default_factory=lambda: os.getenv(
        "PAT_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","))
    sync_packs_on_startup: bool = Field(default_factory=lambda: os.getenv("PAT_SYNC_PACKS_ON_STARTUP", "true") == "true")


@lru_cache
def get_settings() -> Settings:
    return Settings()
