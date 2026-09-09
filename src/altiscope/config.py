"""Runtime settings, from environment variables with the ALTISCOPE_ prefix (or .env)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ALTISCOPE_", env_file=".env", extra="ignore", env_ignore_empty=True
    )

    database_url: str = "postgresql://altiscope:altiscope@localhost:5432/altiscope"
    github_api_base: str = "https://api.github.com"
    github_token: str | None = None
    github_app_id: int | None = None
    github_app_private_key_path: Path | None = None
    models_config: Path = Path("config/models.yaml")
    prompts_dir: Path = Path("prompts")
    migrations_dir: Path = Path("migrations")
    llm_payload_retention: Literal["full", "hashes_only"] = "full"


def load_settings() -> Settings:
    return Settings()
