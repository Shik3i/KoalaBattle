from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="KOALABATTLE_",
        extra="ignore",
        populate_by_name=True,
    )

    database_url: str = "sqlite+aiosqlite:///./data/koalabattle.db"
    showdown_websocket_url: str = "ws://localhost:8000/showdown/websocket"
    showdown_auth_url: str = "https://play.pokemonshowdown.com/action.php?"
    showdown_version: str = "b22742debfdce6e640193384f5731b9030f9cb6e"
    asset_root: Path = Path("data/assets")
    cors_origins: Annotated[tuple[str, ...], NoDecode] = (
        "http://localhost:5173",
        "http://localhost:3000",
    )
    log_level: str = "INFO"
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("KOALABATTLE_OPENAI_API_KEY", "OPENAI_API_KEY"),
    )
    gemini_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("KOALABATTLE_GEMINI_API_KEY", "GEMINI_API_KEY"),
    )
    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("KOALABATTLE_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    )
    deepseek_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("KOALABATTLE_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"),
    )
    openai_compatible_api_key: str | None = None
    enable_fake_provider: bool = False
    max_concurrent_matches: int = Field(default=2, ge=1, le=64)
    pricing_version: str = "unconfigured"
    pricing_table_json: str = "{}"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
