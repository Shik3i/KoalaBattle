from __future__ import annotations

import json
import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from koalabattle.core.models import GenericMatchResult, GenericResultStatus, MatchStatus
from koalabattle.models.orm import (
    AgentDecisionRow,
    MatchRow,
    MatchTemplateRow,
    TournamentParticipantRow,
    TournamentPresetRow,
    TournamentRow,
    TournamentSeriesRow,
)
from koalabattle.storage.database import Database

from .domain import round_robin_series, single_elimination_series
from .models import (
    TOURNAMENT_SCHEMA_VERSION,
    AgentPresetSnapshot,
    CreateTournament,
    MatchTemplateSnapshot,
    SeriesStatus,
    StoredTemplate,
    StoredTournamentPreset,
    TournamentArchive,
    TournamentFormat,
    TournamentParticipant,
    TournamentPresentation,
    TournamentScoring,
    TournamentSeries,
    TournamentStanding,
    TournamentStatistics,
    TournamentStatus,
    TournamentSummary,
)


def _utc(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=value.tzinfo or UTC) if value else None


@dataclass(slots=True)
class _StandingAccumulator:
    participant: TournamentParticipant
    played: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    points: float = 0


class TournamentRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create(self, payload: CreateTournament) -> TournamentArchive:
        tournament_id = uuid4()
        now = datetime.now(UTC)
        participants = list(payload.participants)
        if payload.randomize_seeds:
            random.Random(payload.random_seed).shuffle(participants)
        used = (
            set()
            if payload.randomize_seeds
            else {item.seed for item in participants if item.seed is not None}
        )
        available = iter(seed for seed in range(1, len(participants) + 1) if seed not in used)
        rows: list[TournamentParticipantRow] = []
        for participant in participants:
            seed = (
                next(available)
                if payload.randomize_seeds
                else participant.seed
                if participant.seed is not None
                else next(available)
            )
            rows.append(
                TournamentParticipantRow(
                    id=str(uuid4()),
                    tournament_id=str(tournament_id),
                    display_name=participant.display_name,
                    seed=seed,
                    agent_snapshot_json=participant.agent.model_dump_json(),
                    metadata_json=json.dumps(participant.metadata, separators=(",", ":")),
                )
            )
        tournament = TournamentRow(
            id=str(tournament_id),
            name=payload.name,
            format=payload.format.value,
            status=TournamentStatus.DRAFT.value,
            best_of=payload.best_of,
            max_concurrent_matches=payload.max_concurrent_matches,
            maximum_total_cost=payload.maximum_total_cost,
            max_draw_replays=payload.max_draw_replays,
            manual_scheduling=payload.manual_scheduling,
            match_template_json=payload.match_template.model_dump_json(),
            presentation_json=payload.presentation.model_dump_json(),
            scoring_json=payload.scoring.model_dump_json(),
            current_round=0,
            schema_version=TOURNAMENT_SCHEMA_VERSION,
            created_at=now,
            updated_at=now,
        )
        async with self.database.sessions() as session:
            session.add(tournament)
            await session.flush()
            session.add_all(rows)
            await session.commit()
        archive = await self.get(tournament_id)
        assert archive is not None
        return archive

    async def start(self, tournament_id: UUID) -> TournamentArchive:
        async with self.database.sessions() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            tournament = await session.get(TournamentRow, str(tournament_id))
            if tournament is None:
                raise KeyError(str(tournament_id))
            if TournamentStatus(tournament.status) not in {
                TournamentStatus.DRAFT,
                TournamentStatus.READY,
            }:
                raise ValueError(f"tournament is already {tournament.status}")
            participant_rows = (
                await session.scalars(
                    select(TournamentParticipantRow)
                    .where(TournamentParticipantRow.tournament_id == str(tournament_id))
                    .order_by(TournamentParticipantRow.seed)
                )
            ).all()
            participants = tuple(self._participant(row) for row in participant_rows)
            specs = (
                single_elimination_series(participants)
                if TournamentFormat(tournament.format) is TournamentFormat.SINGLE_ELIMINATION
                else round_robin_series(participants)
            )
            now = datetime.now(UTC)
            target_wins = tournament.best_of // 2 + 1
            session.add_all(
                [
                    TournamentSeriesRow(
                        id=str(spec.id),
                        tournament_id=str(tournament_id),
                        round_number=spec.round_number,
                        bracket_position=spec.bracket_position,
                        queue_order=spec.queue_order,
                        status=spec.status.value,
                        participant_a_id=(
                            str(spec.participant_a_id) if spec.participant_a_id else None
                        ),
                        participant_b_id=(
                            str(spec.participant_b_id) if spec.participant_b_id else None
                        ),
                        dependency_a_id=str(spec.dependency_a_id) if spec.dependency_a_id else None,
                        dependency_b_id=str(spec.dependency_b_id) if spec.dependency_b_id else None,
                        best_of=tournament.best_of,
                        wins_a=0,
                        wins_b=0,
                        draws=0,
                        games_played=0,
                        max_games=tournament.best_of + tournament.max_draw_replays,
                        winner_participant_id=(
                            str(spec.winner_participant_id)
                            if spec.winner_participant_id
                            else None
                        ),
                        result_json=(
                            json.dumps({"status": "bye", "target_wins": target_wins})
                            if spec.winner_participant_id
                            else None
                        ),
                        created_at=now,
                        updated_at=now,
                    )
                    for spec in specs
                ]
            )
            tournament.status = TournamentStatus.RUNNING.value
            tournament.started_at = now
            tournament.updated_at = now
            tournament.current_round = 1
            await session.commit()
        archive = await self.get(tournament_id)
        assert archive is not None
        return archive

    async def set_status(self, tournament_id: UUID, status: TournamentStatus) -> None:
        allowed = {
            TournamentStatus.RUNNING: {
                TournamentStatus.PAUSED,
                TournamentStatus.COMPLETED,
                TournamentStatus.CANCELLED,
                TournamentStatus.FAILED,
            },
            TournamentStatus.PAUSED: {
                TournamentStatus.RUNNING,
                TournamentStatus.CANCELLED,
                TournamentStatus.FAILED,
            },
            TournamentStatus.DRAFT: {
                TournamentStatus.READY,
                TournamentStatus.CANCELLED,
            },
            TournamentStatus.READY: {
                TournamentStatus.RUNNING,
                TournamentStatus.CANCELLED,
            },
        }
        async with self.database.sessions() as session:
            row = await session.get(TournamentRow, str(tournament_id))
            if row is None:
                raise KeyError(str(tournament_id))
            current = TournamentStatus(row.status)
            if current is not status and status not in allowed.get(current, set()):
                raise ValueError(
                    f"invalid tournament transition: {current.value} -> {status.value}"
                )
            row.status = status.value
            row.updated_at = datetime.now(UTC)
            if status is TournamentStatus.COMPLETED:
                row.completed_at = row.updated_at
            await session.commit()

    async def ready_series(self, tournament_id: UUID | None = None) -> tuple[UUID, ...]:
        async with self.database.sessions() as session:
            statement = (
                select(TournamentSeriesRow.id)
                .join(TournamentRow, TournamentRow.id == TournamentSeriesRow.tournament_id)
                .where(
                    TournamentSeriesRow.status == SeriesStatus.READY.value,
                    TournamentRow.status == TournamentStatus.RUNNING.value,
                    TournamentRow.manual_scheduling.is_(False),
                )
                .order_by(TournamentSeriesRow.queue_order)
            )
            if tournament_id is not None:
                statement = statement.where(
                    TournamentSeriesRow.tournament_id == str(tournament_id)
                )
            return tuple(UUID(value) for value in (await session.scalars(statement)).all())

    async def series_execution(
        self, series_id: UUID
    ) -> tuple[UUID, MatchTemplateSnapshot, TournamentParticipant, TournamentParticipant, int]:
        async with self.database.sessions() as session:
            series = await session.get(TournamentSeriesRow, str(series_id))
            if series is None:
                raise KeyError(str(series_id))
            tournament = await session.get(TournamentRow, series.tournament_id)
            if (
                tournament is None
                or series.participant_a_id is None
                or series.participant_b_id is None
            ):
                raise ValueError("series is not executable")
            participant_a = await session.get(TournamentParticipantRow, series.participant_a_id)
            participant_b = await session.get(TournamentParticipantRow, series.participant_b_id)
            if participant_a is None or participant_b is None:
                raise ValueError("series participant snapshot is missing")
            return (
                UUID(tournament.id),
                MatchTemplateSnapshot.model_validate_json(tournament.match_template_json),
                self._participant(participant_a),
                self._participant(participant_b),
                series.games_played + 1,
            )

    async def mark_series_queued(self, series_id: UUID) -> None:
        async with self.database.sessions() as session:
            row = await session.get(TournamentSeriesRow, str(series_id))
            if row is None:
                raise KeyError(str(series_id))
            if SeriesStatus(row.status) is not SeriesStatus.READY:
                raise ValueError(f"series is {row.status}, not ready")
            row.status = SeriesStatus.QUEUED.value
            row.updated_at = datetime.now(UTC)
            await session.commit()

    async def mark_series_running(self, series_id: UUID) -> None:
        async with self.database.sessions() as session:
            row = await session.get(TournamentSeriesRow, str(series_id))
            if row is None:
                raise KeyError(str(series_id))
            if SeriesStatus(row.status) in {SeriesStatus.QUEUED, SeriesStatus.READY}:
                row.status = SeriesStatus.RUNNING.value
                row.updated_at = datetime.now(UTC)
                await session.commit()

    async def record_match_result(
        self, match_id: UUID, result: GenericMatchResult
    ) -> UUID | None:
        async with self.database.sessions() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            match = await session.get(MatchRow, str(match_id))
            if match is None:
                raise KeyError(str(match_id))
            if match.series_id is None or match.tournament_id is None:
                return None
            series = await session.get(TournamentSeriesRow, match.series_id)
            tournament = await session.get(TournamentRow, match.tournament_id)
            if series is None or tournament is None:
                raise ValueError("tournament ownership is incomplete")
            recorded = json.loads(series.result_json or "{}")
            recorded_match_ids = set(recorded.get("match_ids", []))
            if str(match_id) in recorded_match_ids:
                return UUID(tournament.id)
            recorded_match_ids.add(str(match_id))
            series.games_played += 1
            if result.status is GenericResultStatus.COMPLETED:
                if str(result.winner_participant_id) == series.participant_a_id:
                    series.wins_a += 1
                elif str(result.winner_participant_id) == series.participant_b_id:
                    series.wins_b += 1
                else:
                    raise ValueError("match winner is not a participant in its series")
            elif result.status is GenericResultStatus.DRAW:
                series.draws += 1
            else:
                series.status = SeriesStatus.FAILED.value
                tournament.status = TournamentStatus.FAILED.value
                tournament.error = result.reason or f"series match {result.status.value}"

            target_wins = series.best_of // 2 + 1
            winner: str | None = None
            if series.wins_a >= target_wins:
                winner = series.participant_a_id
            elif series.wins_b >= target_wins:
                winner = series.participant_b_id
            exhausted = series.games_played >= series.max_games or (
                TournamentFormat(tournament.format) is TournamentFormat.ROUND_ROBIN
                and result.status is GenericResultStatus.DRAW
                and series.best_of == 1
            )
            elimination_draw_exhausted = (
                exhausted
                and winner is None
                and TournamentFormat(tournament.format)
                is TournamentFormat.SINGLE_ELIMINATION
            )
            if elimination_draw_exhausted:
                series.status = SeriesStatus.FAILED.value
                tournament.status = TournamentStatus.FAILED.value
                tournament.error = "Elimination series exhausted its draw replay limit."
            elif winner is not None or exhausted:
                series.status = SeriesStatus.COMPLETED.value
                series.winner_participant_id = winner
            elif series.status != SeriesStatus.FAILED.value:
                series.status = SeriesStatus.READY.value

            recorded.update(
                {
                    "match_ids": sorted(recorded_match_ids),
                    "last_result": result.model_dump(mode="json"),
                    "target_wins": target_wins,
                    "exhausted": exhausted,
                }
            )
            series.result_json = json.dumps(recorded, separators=(",", ":"), default=str)
            now = datetime.now(UTC)
            series.updated_at = now
            tournament.updated_at = now
            tournament.current_round = max(tournament.current_round, series.round_number)

            if series.status == SeriesStatus.COMPLETED.value:
                await self._advance_dependents(session, series, now)
                await self._complete_tournament_if_ready(session, tournament, now)
            await session.commit()
            return UUID(tournament.id)

    async def _advance_dependents(
        self, session: AsyncSession, series: TournamentSeriesRow, now: datetime
    ) -> None:
        dependents = (
            await session.scalars(
                select(TournamentSeriesRow).where(
                    (TournamentSeriesRow.dependency_a_id == series.id)
                    | (TournamentSeriesRow.dependency_b_id == series.id)
                )
            )
        ).all()
        for dependent in dependents:
            if dependent.dependency_a_id == series.id:
                dependent.participant_a_id = series.winner_participant_id
            if dependent.dependency_b_id == series.id:
                dependent.participant_b_id = series.winner_participant_id
            if dependent.participant_a_id and dependent.participant_b_id:
                dependent.status = SeriesStatus.READY.value
            dependent.updated_at = now

    async def _complete_tournament_if_ready(
        self, session: AsyncSession, tournament: TournamentRow, now: datetime
    ) -> None:
        remaining = await session.scalar(
            select(func.count())
            .select_from(TournamentSeriesRow)
            .where(
                TournamentSeriesRow.tournament_id == tournament.id,
                TournamentSeriesRow.status != SeriesStatus.COMPLETED.value,
            )
        )
        if int(remaining or 0) == 0:
            tournament.status = TournamentStatus.COMPLETED.value
            tournament.completed_at = now
            if TournamentFormat(tournament.format) is TournamentFormat.SINGLE_ELIMINATION:
                final = await session.scalar(
                    select(TournamentSeriesRow)
                    .where(TournamentSeriesRow.tournament_id == tournament.id)
                    .order_by(TournamentSeriesRow.round_number.desc())
                    .limit(1)
                )
                tournament.winner_participant_id = (
                    final.winner_participant_id if final is not None else None
                )

    async def tournament_limit(self, tournament_id: UUID) -> int | None:
        async with self.database.sessions() as session:
            row = await session.get(TournamentRow, str(tournament_id))
            if row is None or row.status != TournamentStatus.RUNNING.value:
                return None
            return row.max_concurrent_matches

    async def estimated_cost(self, tournament_id: UUID) -> float:
        async with self.database.sessions() as session:
            value = await session.scalar(
                select(func.coalesce(func.sum(AgentDecisionRow.estimated_cost), 0.0))
                .join(MatchRow, MatchRow.id == AgentDecisionRow.match_id)
                .where(MatchRow.tournament_id == str(tournament_id))
            )
            return float(value or 0)

    async def budget_allows_start(self, tournament_id: UUID) -> bool:
        async with self.database.sessions() as session:
            row = await session.get(TournamentRow, str(tournament_id))
            if row is None or TournamentStatus(row.status) is not TournamentStatus.RUNNING:
                return False
            if row.maximum_total_cost is None:
                return True
            spent = await session.scalar(
                select(func.coalesce(func.sum(AgentDecisionRow.estimated_cost), 0.0))
                .join(MatchRow, MatchRow.id == AgentDecisionRow.match_id)
                .where(MatchRow.tournament_id == row.id)
            )
            if float(spent or 0) < row.maximum_total_cost:
                return True
            row.status = TournamentStatus.PAUSED.value
            row.error = "Tournament cost limit reached; queued matches were not started."
            row.updated_at = datetime.now(UTC)
            await session.commit()
            return False

    async def get(self, tournament_id: UUID) -> TournamentArchive | None:
        async with self.database.sessions() as session:
            tournament = await session.get(TournamentRow, str(tournament_id))
            if tournament is None:
                return None
            participant_rows = (
                await session.scalars(
                    select(TournamentParticipantRow)
                    .where(TournamentParticipantRow.tournament_id == tournament.id)
                    .order_by(TournamentParticipantRow.seed)
                )
            ).all()
            series_rows = (
                await session.scalars(
                    select(TournamentSeriesRow)
                    .where(TournamentSeriesRow.tournament_id == tournament.id)
                    .order_by(
                        TournamentSeriesRow.round_number,
                        TournamentSeriesRow.bracket_position,
                    )
                )
            ).all()
            match_rows = (
                await session.scalars(
                    select(MatchRow)
                    .where(MatchRow.tournament_id == tournament.id)
                    .order_by(MatchRow.created_at)
                )
            ).all()
            decision_rows = (
                await session.execute(
                    select(
                        func.count(AgentDecisionRow.id),
                        func.coalesce(func.sum(AgentDecisionRow.estimated_cost), 0.0),
                        func.coalesce(func.sum(AgentDecisionRow.latency_ms), 0),
                        func.coalesce(func.sum(AgentDecisionRow.id * 0 + 1), 0),
                    )
                    .join(MatchRow, MatchRow.id == AgentDecisionRow.match_id)
                    .where(MatchRow.tournament_id == tournament.id)
                )
            ).one()
            participants = tuple(self._participant(row) for row in participant_rows)
            matches_by_series: dict[str, list[UUID]] = {}
            for match in match_rows:
                if match.series_id:
                    matches_by_series.setdefault(match.series_id, []).append(UUID(match.id))
            series = tuple(
                self._series(row, tuple(matches_by_series.get(row.id, []))) for row in series_rows
            )
            standings = self._standings(
                participants,
                series_rows,
                TournamentScoring.model_validate_json(tournament.scoring_json),
            )
            decisions_count = int(decision_rows[0] or 0)
            latency_sum = int(decision_rows[2] or 0)
            usage = await self._usage_totals(session, tournament.id)
            statistics = TournamentStatistics(
                matches_played=sum(
                    1 for match in match_rows if match.status == MatchStatus.COMPLETED.value
                ),
                series_played=sum(
                    1 for item in series_rows if item.status == SeriesStatus.COMPLETED.value
                ),
                total_turns=sum(match.turns for match in match_rows),
                input_tokens=usage[0],
                output_tokens=usage[1],
                estimated_cost=float(decision_rows[1] or 0),
                average_decision_latency_ms=(
                    latency_sum / decisions_count if decisions_count else None
                ),
            )
            return TournamentArchive(
                id=UUID(tournament.id),
                name=tournament.name,
                format=TournamentFormat(tournament.format),
                status=TournamentStatus(tournament.status),
                best_of=tournament.best_of,
                max_concurrent_matches=tournament.max_concurrent_matches,
                maximum_total_cost=tournament.maximum_total_cost,
                max_draw_replays=tournament.max_draw_replays,
                manual_scheduling=tournament.manual_scheduling,
                match_template=MatchTemplateSnapshot.model_validate_json(
                    tournament.match_template_json
                ),
                presentation=TournamentPresentation.model_validate_json(
                    tournament.presentation_json
                ),
                scoring=TournamentScoring.model_validate_json(tournament.scoring_json),
                current_round=tournament.current_round,
                winner_participant_id=(
                    UUID(tournament.winner_participant_id)
                    if tournament.winner_participant_id
                    else None
                ),
                error=tournament.error,
                schema_version=tournament.schema_version,
                created_at=_utc(tournament.created_at),
                updated_at=_utc(tournament.updated_at),
                started_at=_utc(tournament.started_at),
                completed_at=_utc(tournament.completed_at),
                participants=participants,
                series=series,
                standings=standings,
                statistics=statistics,
            )

    async def list(self, limit: int = 100, offset: int = 0) -> tuple[TournamentSummary, ...]:
        async with self.database.sessions() as session:
            rows = (
                await session.scalars(
                    select(TournamentRow)
                    .order_by(TournamentRow.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
            summaries: list[TournamentSummary] = []
            for row in rows:
                participant_count = await session.scalar(
                    select(func.count())
                    .select_from(TournamentParticipantRow)
                    .where(TournamentParticipantRow.tournament_id == row.id)
                )
                series_count = await session.scalar(
                    select(func.count())
                    .select_from(TournamentSeriesRow)
                    .where(TournamentSeriesRow.tournament_id == row.id)
                )
                completed = await session.scalar(
                    select(func.count())
                    .select_from(TournamentSeriesRow)
                    .where(
                        TournamentSeriesRow.tournament_id == row.id,
                        TournamentSeriesRow.status == SeriesStatus.COMPLETED.value,
                    )
                )
                summaries.append(
                    TournamentSummary(
                        id=UUID(row.id),
                        name=row.name,
                        format=TournamentFormat(row.format),
                        status=TournamentStatus(row.status),
                        participant_count=int(participant_count or 0),
                        series_count=int(series_count or 0),
                        completed_series=int(completed or 0),
                        current_round=row.current_round,
                        created_at=_utc(row.created_at),
                        updated_at=_utc(row.updated_at),
                    )
                )
            return tuple(summaries)

    async def create_template(
        self, name: str, snapshot: MatchTemplateSnapshot
    ) -> StoredTemplate:
        now = datetime.now(UTC)
        row = MatchTemplateRow(
            id=str(uuid4()),
            name=name,
            engine=snapshot.engine,
            config_json=snapshot.model_dump_json(),
            presentation_json=json.dumps(snapshot.presentation, separators=(",", ":")),
            schema_version=snapshot.schema_version,
            created_at=now,
            updated_at=now,
        )
        async with self.database.sessions() as session:
            session.add(row)
            await session.commit()
        return self._template(row)

    async def list_templates(self) -> tuple[StoredTemplate, ...]:
        async with self.database.sessions() as session:
            rows = (
                await session.scalars(
                    select(MatchTemplateRow).order_by(MatchTemplateRow.name)
                )
            ).all()
            return tuple(self._template(row) for row in rows)

    async def create_preset(self, name: str, config: dict[str, object]) -> StoredTournamentPreset:
        now = datetime.now(UTC)
        row = TournamentPresetRow(
            id=str(uuid4()),
            name=name,
            config_json=json.dumps(config, separators=(",", ":"), sort_keys=True),
            schema_version=TOURNAMENT_SCHEMA_VERSION,
            created_at=now,
            updated_at=now,
        )
        async with self.database.sessions() as session:
            session.add(row)
            await session.commit()
        return self._preset(row)

    async def list_presets(self) -> tuple[StoredTournamentPreset, ...]:
        async with self.database.sessions() as session:
            rows = (
                await session.scalars(
                    select(TournamentPresetRow).order_by(TournamentPresetRow.name)
                )
            ).all()
            return tuple(self._preset(row) for row in rows)

    @staticmethod
    async def _usage_totals(session: AsyncSession, tournament_id: str) -> tuple[int, int]:
        rows = (
            await session.scalars(
                select(AgentDecisionRow.usage_json)
                .join(MatchRow, MatchRow.id == AgentDecisionRow.match_id)
                .where(MatchRow.tournament_id == tournament_id)
            )
        ).all()
        input_tokens = 0
        output_tokens = 0
        for value in rows:
            if not value:
                continue
            usage = json.loads(value)
            input_tokens += int(usage.get("input_tokens") or 0)
            output_tokens += int(usage.get("output_tokens") or 0)
        return input_tokens, output_tokens

    @staticmethod
    def _participant(row: TournamentParticipantRow) -> TournamentParticipant:
        return TournamentParticipant(
            id=UUID(row.id),
            tournament_id=UUID(row.tournament_id),
            display_name=row.display_name,
            seed=row.seed,
            agent=AgentPresetSnapshot.model_validate_json(row.agent_snapshot_json),
            metadata=json.loads(row.metadata_json),
        )

    @staticmethod
    def _series(row: TournamentSeriesRow, match_ids: tuple[UUID, ...]) -> TournamentSeries:
        return TournamentSeries(
            id=UUID(row.id),
            tournament_id=UUID(row.tournament_id),
            round_number=row.round_number,
            bracket_position=row.bracket_position,
            queue_order=row.queue_order,
            status=SeriesStatus(row.status),
            participant_a_id=UUID(row.participant_a_id) if row.participant_a_id else None,
            participant_b_id=UUID(row.participant_b_id) if row.participant_b_id else None,
            dependency_a_id=UUID(row.dependency_a_id) if row.dependency_a_id else None,
            dependency_b_id=UUID(row.dependency_b_id) if row.dependency_b_id else None,
            best_of=row.best_of,
            wins_a=row.wins_a,
            wins_b=row.wins_b,
            draws=row.draws,
            games_played=row.games_played,
            max_games=row.max_games,
            winner_participant_id=(
                UUID(row.winner_participant_id) if row.winner_participant_id else None
            ),
            match_ids=match_ids,
        )

    @staticmethod
    def _standings(
        participants: tuple[TournamentParticipant, ...],
        series: Sequence[TournamentSeriesRow],
        scoring: TournamentScoring,
    ) -> tuple[TournamentStanding, ...]:
        values = {
            str(participant.id): _StandingAccumulator(participant=participant)
            for participant in participants
        }
        for item in series:
            if item.status != SeriesStatus.COMPLETED.value:
                continue
            if not item.participant_a_id or not item.participant_b_id:
                continue
            a = values[item.participant_a_id]
            b = values[item.participant_b_id]
            a.played += 1
            b.played += 1
            if item.winner_participant_id == item.participant_a_id:
                a.wins += 1
                b.losses += 1
                a.points += scoring.win_points
                b.points += scoring.loss_points
            elif item.winner_participant_id == item.participant_b_id:
                b.wins += 1
                a.losses += 1
                b.points += scoring.win_points
                a.points += scoring.loss_points
            else:
                a.draws += 1
                b.draws += 1
                a.points += scoring.draw_points
                b.points += scoring.draw_points
        standings = [
            TournamentStanding(
                participant_id=entry.participant.id,
                display_name=entry.participant.display_name,
                seed=entry.participant.seed,
                played=entry.played,
                wins=entry.wins,
                losses=entry.losses,
                draws=entry.draws,
                points=entry.points,
            )
            for entry in values.values()
        ]
        return tuple(
            sorted(standings, key=lambda item: (-item.points, -item.wins, item.seed))
        )

    @staticmethod
    def _template(row: MatchTemplateRow) -> StoredTemplate:
        return StoredTemplate(
            id=UUID(row.id),
            name=row.name,
            snapshot=MatchTemplateSnapshot.model_validate_json(row.config_json),
            created_at=_utc(row.created_at),
            updated_at=_utc(row.updated_at),
        )

    @staticmethod
    def _preset(row: TournamentPresetRow) -> StoredTournamentPreset:
        return StoredTournamentPreset(
            id=UUID(row.id),
            name=row.name,
            config=json.loads(row.config_json),
            created_at=_utc(row.created_at),
            updated_at=_utc(row.updated_at),
        )
