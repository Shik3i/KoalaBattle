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
    team_validator_url: str = "http://localhost:8002"
    showdown_version: str = "b22742debfdce6e640193384f5731b9030f9cb6e"
    orchestrator_local_base_url: str = "http://127.0.0.1:1234/v1"
    orchestrator_default_model: str = "google/gemma-4-e4b"
    asset_root: Path = Path("data/assets")
    #: User-uploaded logos, backgrounds, watermarks and fonts. Runtime media, never
    #: committed; see docs/ASSETS.md for the backup implications.
    branding_root: Path = Path("data/branding")
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
    speech_provider: str = "system"
    speech_audio_root: Path = Path("data/audio")
    speech_edge_enabled: bool = True
    speech_edge_voice_p1: str = "en-US-EmmaMultilingualNeural"
    speech_edge_voice_p2: str = "en-US-BrianMultilingualNeural"
    speech_max_concurrency: int = Field(default=8, ge=1, le=16)
    speech_max_text_characters: int = Field(default=1000, ge=1, le=4096)
    speech_openai_model: str = "gpt-4o-mini-tts"
    speech_openai_base_url: str | None = None
    speech_openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "KOALABATTLE_SPEECH_OPENAI_API_KEY", "KOALABATTLE_OPENAI_API_KEY", "OPENAI_API_KEY"
        ),
    )
    video_root: Path = Path("data/videos")
    video_max_concurrency: int = Field(default=1, ge=1, le=4)
    video_frame_workers: int = Field(default=4, ge=1, le=8)
    video_worker_enabled: bool = True
    video_frontend_url: str = "http://localhost:3000"
    video_api_url: str = "http://localhost:8001"
    video_ffmpeg_path: str = "ffmpeg"
    video_ffprobe_path: str = "ffprobe"
    video_chromium_path: Path | None = None
    video_native_transport: str = Field(
        default="auto",
        pattern=r"^(auto|webcodecs|mjpeg|raw-rgba)$",
    )
    video_min_free_bytes: int = Field(default=1_073_741_824, ge=50_000_000)
    obs_host: str = "127.0.0.1"
    obs_port: int = Field(default=4455, ge=1, le=65535)
    obs_password: str | None = None
    obs_scene: str = "KoalaBattle"
    obs_browser_source: str = "KoalaBattle"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
