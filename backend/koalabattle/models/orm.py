from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
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

    players: Mapped[list[PlayerRow]] = relationship(
        back_populates="match", cascade="all, delete-orphan", lazy="selectin"
    )
    events: Mapped[list[BattleEventRow]] = relationship(
        back_populates="match",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="BattleEventRow.sequence",
    )
    decisions: Mapped[list[AgentDecisionRow]] = relationship(
        back_populates="match",
        cascade="all, delete-orphan",
        lazy="selectin",
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
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)

    match: Mapped[MatchRow] = relationship(back_populates="events")


class AgentDecisionRow(Base):
    __tablename__ = "agent_decisions"
    __table_args__ = (
        UniqueConstraint(
            "match_id", "side", "decision_sequence", name="uq_decisions_match_side_sequence"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    side: Mapped[str] = mapped_column(String(2), nullable=False)
    turn: Mapped[int] = mapped_column(Integer, nullable=False)
    decision_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    decision_json: Mapped[str] = mapped_column(Text, nullable=False)
    state_json: Mapped[str] = mapped_column(Text, nullable=False)
    legal_actions_json: Mapped[str] = mapped_column(Text, nullable=False)
    generated_prompt: Mapped[str] = mapped_column(Text, nullable=False)
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
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)

    match: Mapped[MatchRow] = relationship(back_populates="decisions")


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
