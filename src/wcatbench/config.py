"""Settings read from the environment (`WCATBENCH_*`). Keys for paid services are never settings: see core.secrets."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WCATBENCH_", extra="ignore")

    home: Path = Field(
        default=Path.home() / ".local" / "share" / "wcatbench",
        description="Datasets, store builds and runs live here.",
    )
    log_format: Literal["console", "json"] = "console"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
