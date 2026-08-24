from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    LargeBinary,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class MatchRow(Base):
    __tablename__ = "matches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    format: Mapped[str] = mapped_column(String(80), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    winner: Mapped[str | None] = mapped_column(String(2))
    turns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    engine: Mapped[str] = mapped_column(String(80), nullable=False)
    engine_version: Mapped[str | None] = mapped_column(String(80))
    showdown_version: Mapped[str | None] = mapped_column(String(80))
    poke_env_version: Mapped[str | None] = mapped_column(String(40))
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    random_seed: Mapped[int | None] = mapped_column(Integer)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)
    raw_showdown_log: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    tournament_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tournaments.id", ondelete="SET NULL"), index=True
    )
    series_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tournament_series.id", ondelete="SET NULL"), index=True
    )
    queue_position: Mapped[int | None] = mapped_column(Integer, index=True)
    challenge_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("challenge_runs.id", ondelete="SET NULL"), index=True
    )
    challenge_stage_id: Mapped[str | None] = mapped_column(String(60), index=True)

    players: Mapped[list[PlayerRow]] = relationship(
        back_populates="match", cascade="all, delete-orphan", lazy="raise"
    )
    events: Mapped[list[BattleEventRow]] = relationship(
        back_populates="match",
        cascade="all, delete-orphan",
        lazy="raise",
        order_by="BattleEventRow.sequence",
    )
    decisions: Mapped[list[AgentDecisionRow]] = relationship(
        back_populates="match",
        cascade="all, delete-orphan",
        lazy="raise",
        order_by="AgentDecisionRow.decision_sequence",
    )


class PlayerRow(Base):
    __tablename__ = "players"
    __table_args__ = (UniqueConstraint("match_id", "side", name="uq_players_match_side"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    side: Mapped[str] = mapped_column(String(2), nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    agent_type: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(80))
    model: Mapped[str | None] = mapped_column(String(160))
    configuration_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    team_json: Mapped[str | None] = mapped_column(Text)

    match: Mapped[MatchRow] = relationship(back_populates="players")


class BattleEventRow(Base):
    __tablename__ = "battle_events"
    __table_args__ = (
        UniqueConstraint("match_id", "sequence", name="uq_battle_events_match_sequence"),
        Index("ix_battle_events_match_turn", "match_id", "turn"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    turn: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    logical_offset_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    #: zlib-compressed payload JSON. Snapshots re-serialize both full teams and made
    #: up 82% of this table, so payloads are stored compressed and — unless this row
    #: is a keyframe — against the previous payload of the same event type as the
    #: dictionary. See `koalabattle.storage.payloads` for why that is safe here.
    payload_z: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    #: True when `payload_z` decodes on its own. The bytes do not reveal this.
    payload_keyframe: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)

    match: Mapped[MatchRow] = relationship(back_populates="events")


class AgentDecisionRow(Base):
    __tablename__ = "agent_decisions"
    __table_args__ = (
        UniqueConstraint(
            "match_id", "side", "decision_sequence", name="uq_decisions_match_side_sequence"
        ),
        Index("ix_agent_decisions_match_turn", "match_id", "turn"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    side: Mapped[str] = mapped_column(String(2), nullable=False)
    turn: Mapped[int] = mapped_column(Integer, nullable=False)
    decision_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    #: The full `AgentRequest`, including its state, legal actions and rendered
    #: prompt. Those three used to be mirrored into `state_json`,
    #: `legal_actions_json` and `generated_prompt` columns as well; the copies had
    #: no reader and cost ~380MB across a modest history (migration 0013).
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    decision_json: Mapped[str] = mapped_column(Text, nullable=False)
    raw_response: Mapped[str | None] = mapped_column(Text)
    parsed_response_json: Mapped[str | None] = mapped_column(Text)
    selected_action: Mapped[str] = mapped_column(String(80), nullable=False)
    commentary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    validation_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    provider_metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    provider: Mapped[str | None] = mapped_column(String(80))
    model: Mapped[str | None] = mapped_column(String(200))
    agent_configuration_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    prompt_schema_version: Mapped[str] = mapped_column(String(40), nullable=False, default="1.0")
    prompt_template_version: Mapped[str] = mapped_column(
        String(80), nullable=False, default="phase1"
    )
    information_profile: Mapped[str] = mapped_column(String(40), nullable=False, default="standard")
    usage_json: Mapped[str | None] = mapped_column(Text)
    retry_attempts_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    fallback_json: Mapped[str | None] = mapped_column(Text)
    estimated_cost: Mapped[float | None] = mapped_column(Float)
    cost_currency: Mapped[str | None] = mapped_column(String(8))
    pricing_version: Mapped[str | None] = mapped_column(String(80))
    error_category: Mapped[str | None] = mapped_column(String(40))
    error_detail: Mapped[str | None] = mapped_column(Text)
    knowledge_json: Mapped[str | None] = mapped_column(Text)
    context_json: Mapped[str | None] = mapped_column(Text)
    context_metrics_json: Mapped[str | None] = mapped_column(Text)
    prompt_profile_id: Mapped[str | None] = mapped_column(String(80))
    prompt_profile_version: Mapped[str | None] = mapped_column(String(40))
    context_schema_version: Mapped[str | None] = mapped_column(String(40))
    knowledge_schema_version: Mapped[str | None] = mapped_column(String(40))
    history_policy_version: Mapped[str | None] = mapped_column(String(80))
    memory_policy: Mapped[str | None] = mapped_column(String(40))
    memory_policy_version: Mapped[str | None] = mapped_column(String(40))
    strategy_memory_before: Mapped[str | None] = mapped_column(String(400))
    strategy_memory_after: Mapped[str | None] = mapped_column(String(400))
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)

    match: Mapped[MatchRow] = relationship(back_populates="decisions")


class VoicePresetRow(Base):
    __tablename__ = "voice_presets"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    voice: Mapped[str] = mapped_column(String(120), nullable=False)
    model: Mapped[str | None] = mapped_column(String(160))
    language: Mapped[str | None] = mapped_column(String(20))
    speed: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    instructions: Mapped[str | None] = mapped_column(String(500))
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    voice_mode: Mapped[str] = mapped_column(String(30), nullable=False, default="system")
    persona_id: Mapped[str | None] = mapped_column(String(80))
    delivery_profile: Mapped[str | None] = mapped_column(String(60))
    disclosure_label: Mapped[str | None] = mapped_column(String(180))
    reference_audio_path: Mapped[str | None] = mapped_column(String(260))
    reference_text: Mapped[str | None] = mapped_column(String(1000))
    x_vector_only_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VoicePoolRow(Base):
    __tablename__ = "voice_pools"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    voice_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProductionRow(Base):
    __tablename__ = "productions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    match_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    profile_id: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    profile_version: Mapped[str] = mapped_column(String(20), nullable=False)
    timeline_version: Mapped[str] = mapped_column(String(20), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    director_state: Mapped[str] = mapped_column(String(40), nullable=False)
    timeline_json: Mapped[str] = mapped_column(Text, nullable=False)
    voice_assignments_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    overrides_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    authoritative_client_id: Mapped[str | None] = mapped_column(String(120))
    # Presentation only. Editing these never touches the battle events the timeline was
    # built from, which is what lets one match carry several independent productions.
    style_id: Mapped[str] = mapped_column(String(60), nullable=False, default="koala-broadcast")
    style_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    title: Mapped[str | None] = mapped_column(String(90))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BrandAssetRow(Base):
    __tablename__ = "brand_assets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    media_type: Mapped[str] = mapped_column(String(60), nullable=False)
    # Relative to the branding media root and generated from the asset id, never from the
    # uploaded filename.
    relative_path: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StylePresetRow(Base):
    __tablename__ = "style_presets"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    display_name: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    style_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SpeechCacheRow(Base):
    __tablename__ = "speech_cache"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    voice: Mapped[str] = mapped_column(String(120), nullable=False)
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(260), nullable=False, unique=True)
    media_type: Mapped[str] = mapped_column(String(80), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VideoExportJobRow(Base):
    __tablename__ = "video_export_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    production_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("productions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    match_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("matches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    backend: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    preset_id: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), unique=True)
    output_relative_path: Mapped[str | None] = mapped_column(String(500), unique=True)
    job_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TeamSnapshotRow(Base):
    __tablename__ = "team_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    format: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    submitted_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_export: Mapped[str] = mapped_column(Text, nullable=False)
    packed_team: Mapped[str] = mapped_column(Text, nullable=False)
    structured_team_json: Mapped[str] = mapped_column(Text, nullable=False)
    generation_audit_json: Mapped[str | None] = mapped_column(Text)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TeamBuildAuditRow(Base):
    __tablename__ = "team_build_audits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    participant: Mapped[str] = mapped_column(String(80), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    format: Mapped[str] = mapped_column(String(40), nullable=False)
    prompt_profile_version: Mapped[str] = mapped_column(String(80), nullable=False)
    rendered_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    raw_responses_json: Mapped[str] = mapped_column(Text, nullable=False)
    validation_errors_json: Mapped[str] = mapped_column(Text, nullable=False)
    repair_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    team_snapshot_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("team_snapshots.id", ondelete="SET NULL"), index=True
    )
    usage_json: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DraftPoolSnapshotRow(Base):
    """Content-addressed store for immutable draft pools.

    A generated draft pool (up to ~1,200 candidates with stats/moves/sets) never
    changes once built for a given `catalog_hash`. Storing it once here, keyed by
    that hash, and referencing it from `ChallengeRunRow.state_json` instead of
    re-embedding it, keeps every pick/reroll/stage-transition save small.
    """

    __tablename__ = "draft_pool_snapshots"

    catalog_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChallengeRunRow(Base):
    __tablename__ = "challenge_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    definition_id: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    definition_version: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    current_stage_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_match_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("matches.id", ondelete="SET NULL"), index=True
    )
    state_json: Mapped[str] = mapped_column(Text, nullable=False)
    #: Denormalized copies of the few `ChallengeRunSummary` fields that are not already
    #: columns. The run list renders ~10 fields per row; without these it had to read and
    #: fully validate every run's `state_json` (hundreds of KB each) just to reach them.
    definition_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    stage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stages_cleared: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MatchTemplateRow(Base):
    __tablename__ = "match_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    engine: Mapped[str] = mapped_column(String(80), nullable=False)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)
    presentation_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TournamentPresetRow(Base):
    __tablename__ = "tournament_presets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TournamentRow(Base):
    __tablename__ = "tournaments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    format: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    best_of: Mapped[int] = mapped_column(Integer, nullable=False)
    max_concurrent_matches: Mapped[int] = mapped_column(Integer, nullable=False)
    maximum_total_cost: Mapped[float | None] = mapped_column(Float)
    max_draw_replays: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    manual_scheduling: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    match_template_json: Mapped[str] = mapped_column(Text, nullable=False)
    presentation_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    scoring_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    current_round: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    winner_participant_id: Mapped[str | None] = mapped_column(String(36))
    error: Mapped[str | None] = mapped_column(Text)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TournamentParticipantRow(Base):
    __tablename__ = "tournament_participants"
    __table_args__ = (
        UniqueConstraint("tournament_id", "seed", name="uq_tournament_participant_seed"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tournament_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class TournamentSeriesRow(Base):
    __tablename__ = "tournament_series"
    __table_args__ = (
        UniqueConstraint(
            "tournament_id", "round_number", "bracket_position", name="uq_series_bracket_slot"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tournament_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    bracket_position: Mapped[int] = mapped_column(Integer, nullable=False)
    queue_order: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    participant_a_id: Mapped[str | None] = mapped_column(String(36))
    participant_b_id: Mapped[str | None] = mapped_column(String(36))
    dependency_a_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tournament_series.id", ondelete="SET NULL")
    )
    dependency_b_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tournament_series.id", ondelete="SET NULL")
    )
    best_of: Mapped[int] = mapped_column(Integer, nullable=False)
    wins_a: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wins_b: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    draws: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    games_played: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_games: Mapped[int] = mapped_column(Integer, nullable=False)
    winner_participant_id: Mapped[str | None] = mapped_column(String(36))
    result_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def json_default(value: Any) -> str:
    raise TypeError(f"cannot serialize {type(value).__name__}")
