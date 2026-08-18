from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .style import ProductionStyle

PRODUCTION_SCHEMA_VERSION = "2.0"
TIMELINE_VERSION = "2.0"


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Track(StrEnum):
    VISUAL = "visual"
    COMMENTARY = "commentary"
    VOICE = "voice"
    CAPTIONS = "captions"
    SFX = "sfx"
    MUSIC = "music"
    DIRECTOR = "director"


class DirectorState(StrEnum):
    PRE_SHOW = "pre-show"
    MATCH_INTRO = "match-intro"
    TEAM_REVEAL = "team-reveal"
    BATTLE = "battle"
    BETWEEN_GAMES = "between-games"
    RESULT = "result"
    CHAMPION = "champion"
    PAUSED = "paused"
    ENDED = "ended"


class ProductionStatus(StrEnum):
    DRAFT = "draft"
    LIVE = "live"
    FINALIZING = "finalizing"
    FINALIZED = "finalized"
    # Legacy Phase 6 values remain readable.
    PREPARING = "preparing"
    READY = "ready"
    PARTIAL = "partial"
    FAILED = "failed"


class SpeechProviderKind(StrEnum):
    SYSTEM = "system"
    OPENAI = "openai"
    OPENAI_COMPATIBLE = "openai-compatible"
    FAKE = "fake"


class CaptionSegment(FrozenModel):
    text: str = Field(min_length=1, max_length=160)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)


class ProductionCue(FrozenModel):
    id: str = Field(min_length=1, max_length=120)
    track: Track
    kind: str = Field(min_length=1, max_length=80)
    start_ms: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    event_sequence: int | None = Field(default=None, ge=1)
    turn: int | None = Field(default=None, ge=0)
    side: str | None = Field(default=None, pattern=r"^p[12]$")
    payload: dict[str, Any] = Field(default_factory=dict)


class ProductionProfile(FrozenModel):
    id: str
    display_name: str
    version: str = "1.0"
    intro_enabled: bool = True
    speech_enabled: bool = True
    captions_enabled: bool = True
    sfx_enabled: bool = True
    music_enabled: bool = False
    wait_for_speech: bool = True
    commentary_max_characters: int = Field(default=320, ge=40, le=1000)
    caption_max_characters: int = Field(default=42, ge=12, le=80)
    #: Minimum presentation slot for one deterministic replay turn. Speech or animation may
    #: extend it, but a short turn never creates an accidental variable-length pause.
    turn_target_ms: int = Field(default=20_000, ge=1_000, le=120_000)
    #: Kept for compatibility with persisted profiles. New timelines apply this only between
    #: turns, never between individual event sequences.
    event_gap_ms: int = Field(default=120, ge=0, le=5000)
    turn_gap_ms: int | None = Field(default=None, ge=0, le=5000)
    intro_duration_ms: int = Field(default=2_200, ge=0, le=30_000)
    result_duration_ms: int = Field(default=1_800, ge=0, le=30_000)
    outro_duration_ms: int = Field(default=600, ge=0, le=30_000)
    aspect_ratio: str = Field(default="16:9", pattern=r"^(16:9|9:16)$")
    interruption_policy: str = Field(
        default="finish-current", pattern=r"^(finish-current|interrupt)$"
    )
    ducking_db: float = Field(default=-12.0, ge=-30, le=0)

    @property
    def turn_pause_ms(self) -> int:
        return self.event_gap_ms if self.turn_gap_ms is None else self.turn_gap_ms


class VoicePreset(FrozenModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    display_name: str = Field(min_length=1, max_length=120)
    provider: SpeechProviderKind
    voice: str = Field(min_length=1, max_length=120)
    model: str | None = Field(default=None, max_length=160)
    language: str | None = Field(default=None, max_length=20)
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    instructions: str | None = Field(default=None, max_length=500)
    enabled: bool = True


class SpeechRequest(FrozenModel):
    text: str = Field(min_length=1, max_length=4096)
    provider: SpeechProviderKind
    model: str
    voice: str
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    language: str | None = None
    instructions: str | None = None
    format: str = Field(default="wav", pattern=r"^wav$")

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return " ".join(value.split())


class SpeechArtifact(FrozenModel):
    cache_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    media_url: str
    media_type: str = "audio/wav"
    duration_ms: int = Field(ge=1)
    byte_size: int = Field(ge=1)
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    cache_hit: bool = False


class SpeechProviderStatus(FrozenModel):
    id: SpeechProviderKind
    configured: bool
    available: bool
    paid: bool
    detail: str
    supports_timestamps: bool = False
    voices: tuple[str, ...] = ()


class ProductionTimeline(FrozenModel):
    id: UUID
    match_id: UUID
    profile: ProductionProfile
    timeline_version: str = TIMELINE_VERSION
    revision: int = Field(default=1, ge=1)
    status: ProductionStatus = ProductionStatus.DRAFT
    director_state: DirectorState = DirectorState.PRE_SHOW
    cues: tuple[ProductionCue, ...] = ()
    voice_assignments: dict[str, str] = Field(default_factory=dict)
    #: Presentation only. Productions saved before styles existed validate with the
    #: built-in Koala Broadcast defaults, so old archives keep rendering unchanged.
    style: ProductionStyle = Field(default_factory=ProductionStyle)
    #: Optional display title for the video. Never renames the historical match.
    title: str | None = Field(default=None, min_length=1, max_length=90)
    overrides: dict[str, Any] = Field(default_factory=dict)
    authoritative_client_id: str | None = None
    duration_ms: int = Field(default=0, ge=0)
    finalized_at: datetime | None = None
    content_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    created_at: datetime
    updated_at: datetime


class CreateProduction(FrozenModel):
    profile_id: str = "live-stream"
    voice_assignments: dict[str, str] = Field(default_factory=dict)
    #: A built-in or saved style preset id. Player branding is filled in from the match's
    #: agents afterwards, so a new production already looks right before any editing.
    style_id: str | None = Field(default=None, max_length=60)
    style: ProductionStyle | None = None
    title: str | None = Field(default=None, min_length=1, max_length=90)


class UpdateProduction(FrozenModel):
    """A non-destructive presentation edit. Cannot reach battle events or decisions."""

    style: ProductionStyle | None = None
    title: str | None = Field(default=None, min_length=1, max_length=90)
    clear_title: bool = False


class DuplicateProduction(FrozenModel):
    title: str | None = Field(default=None, min_length=1, max_length=90)
    style_id: str | None = Field(default=None, max_length=60)


class PrepareSpeechRequest(FrozenModel):
    force: bool = False
    allow_paid: bool = False


class VoicePreviewRequest(FrozenModel):
    preset_id: str = Field(min_length=1, max_length=80)
    text: str = Field(default="KoalaBattle voice preview.", min_length=1, max_length=240)
    allow_paid: bool = False


class DirectorCommand(FrozenModel):
    command: str = Field(
        pattern=r"^(start|pause|resume|next|show-intro|show-team-reveal|show-result|show-champion|end)$"
    )
    client_id: str | None = Field(default=None, max_length=120)
