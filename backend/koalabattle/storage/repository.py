from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from koalabattle.core.models import (
    SCHEMA_VERSION,
    AgentDecision,
    AgentRequest,
    BattleEvent,
    DecisionRecord,
    MatchArchive,
    MatchConfig,
    MatchStatus,
    MatchSummary,
    Side,
)
from koalabattle.models.orm import AgentDecisionRow, BattleEventRow, MatchRow, PlayerRow
from koalabattle.orchestration.lifecycle import ACTIVE_MATCH_STATUSES, validate_transition

from .database import Database


def _json(value: object) -> str:
    if isinstance(value, BaseModel):
        return value.model_dump_json()
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


class BattleRepository:
    def __init__(self, database: Database) -> None:
        self.database = database
        self._event_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def create_match(
        self,
        match_id: UUID,
        config: MatchConfig,
        *,
        engine: str,
        engine_version: str | None,
        showdown_version: str | None,
        poke_env_version: str | None,
        tournament_id: UUID | None = None,
        series_id: UUID | None = None,
    ) -> MatchArchive:
        now = datetime.now(UTC)
        row = MatchRow(
            id=str(match_id),
            created_at=now,
            updated_at=now,
            status=MatchStatus.CREATED.value,
            format=config.format,
            generation=config.generation,
            turns=0,
            engine=engine,
            engine_version=engine_version,
            showdown_version=showdown_version,
            poke_env_version=poke_env_version,
            schema_version=SCHEMA_VERSION,
            random_seed=config.random_seed,
            config_json=_json(config),
            tournament_id=str(tournament_id) if tournament_id else None,
            series_id=str(series_id) if series_id else None,
        )
        row.players = [
            PlayerRow(
                side=player.side.value,
                display_name=player.display_name,
                agent_type=player.agent_type.value,
                provider=player.provider,
                model=player.model,
                configuration_json=_json(player.configuration),
            )
            for player in config.players
        ]
        async with self.database.sessions() as session:
            session.add(row)
            await session.commit()
        archive = await self.get_match(match_id)
        assert archive is not None
        return archive

    async def set_status(self, match_id: UUID, status: MatchStatus) -> None:
        async with self.database.sessions() as session:
            row = await session.get(MatchRow, str(match_id))
            if row is None:
                raise KeyError(str(match_id))
            validate_transition(MatchStatus(row.status), status)
            row.status = status.value
            if status is MatchStatus.STARTING:
                row.queue_position = None
            row.updated_at = datetime.now(UTC)
            await session.commit()

    async def enqueue_match(self, match_id: UUID) -> int:
        async with self.database.sessions() as session:
            row = await session.get(MatchRow, str(match_id))
            if row is None:
                raise KeyError(str(match_id))
            validate_transition(MatchStatus(row.status), MatchStatus.QUEUED)
            current = await session.scalar(select(func.max(MatchRow.queue_position)))
            position = int(current or 0) + 1
            row.status = MatchStatus.QUEUED.value
            row.queue_position = position
            row.updated_at = datetime.now(UTC)
            await session.commit()
            return position

    async def reconcile_interrupted_matches(self) -> tuple[UUID, ...]:
        interrupted: list[UUID] = []
        active_values = tuple(status.value for status in ACTIVE_MATCH_STATUSES)
        async with self.database.sessions() as session:
            rows = (
                await session.scalars(select(MatchRow).where(MatchRow.status.in_(active_values)))
            ).all()
            now = datetime.now(UTC)
            for row in rows:
                row.status = MatchStatus.INTERRUPTED.value
                row.error = "Backend restarted while the runtime session was active."
                row.updated_at = now
                interrupted.append(UUID(row.id))
            await session.commit()
        return tuple(interrupted)

    async def queued_matches(self) -> tuple[MatchSummary, ...]:
        async with self.database.sessions() as session:
            rows = (
                await session.scalars(
                    select(MatchRow)
                    .where(MatchRow.status == MatchStatus.QUEUED.value)
                    .order_by(MatchRow.queue_position, MatchRow.created_at)
                )
            ).all()
            return tuple(self._summary(row) for row in rows)

    async def append_event(self, event: BattleEvent) -> BattleEvent:
        match_key = str(event.match_id)
        async with self._event_locks[match_key]:
            async with self.database.sessions() as session:
                current = await session.scalar(
                    select(func.max(BattleEventRow.sequence)).where(
                        BattleEventRow.match_id == match_key
                    )
                )
                stored = event.model_copy(update={"sequence": int(current or 0) + 1})
                row = BattleEventRow(
                    match_id=match_key,
                    sequence=stored.sequence,
                    turn=stored.turn,
                    event_type=stored.event_type,
                    created_at=stored.created_at,
                    logical_offset_ms=stored.logical_offset_ms,
                    payload_json=_json(stored.payload),
                    schema_version=stored.schema_version,
                )
                session.add(row)
                match = await session.get(MatchRow, match_key)
                if match is None:
                    raise KeyError(match_key)
                match.updated_at = datetime.now(UTC)
                await session.flush()
                stored = stored.model_copy(update={"id": row.id})
                await session.commit()
                return stored

    async def record_decision(
        self,
        request: AgentRequest,
        decision: AgentDecision,
        *,
        validation_errors: tuple[str, ...] = (),
    ) -> DecisionRecord:
        effective_validation_errors = validation_errors or decision.validation_errors
        archive = await self.get_match(request.match_id)
        if archive is None:
            raise KeyError(str(request.match_id))
        agent_configuration = next(
            player.configuration for player in archive.config.players if player.side is request.side
        )
        parsed = {
            "action": decision.action,
            "commentary": decision.commentary,
        }
        row = AgentDecisionRow(
            match_id=str(request.match_id),
            request_id=str(request.request_id),
            side=request.side.value,
            turn=request.turn,
            decision_sequence=request.decision_sequence,
            request_json=_json(request),
            decision_json=_json(decision),
            state_json=_json(request.state),
            legal_actions_json=_json(
                [action.model_dump(mode="json") for action in request.legal_actions]
            ),
            generated_prompt=request.prompt,
            raw_response=decision.raw_response,
            parsed_response_json=_json(parsed),
            selected_action=decision.action,
            commentary=decision.commentary,
            validation_json=_json(list(effective_validation_errors)),
            latency_ms=decision.latency_ms,
            provider_metadata_json=_json(decision.provider_metadata),
            provider=decision.provider,
            model=decision.model,
            agent_configuration_json=_json(agent_configuration),
            prompt_schema_version=request.prompt_schema_version,
            prompt_template_version=request.prompt_template_version,
            information_profile=request.information_profile,
            usage_json=_json(decision.usage) if decision.usage is not None else None,
            retry_attempts_json=_json(
                [attempt.model_dump(mode="json") for attempt in decision.retry_attempts]
            ),
            fallback_json=_json(decision.fallback) if decision.fallback is not None else None,
            estimated_cost=decision.estimated_cost.amount,
            cost_currency=decision.estimated_cost.currency,
            pricing_version=decision.estimated_cost.pricing_version,
            error_category=decision.error_category.value if decision.error_category else None,
            error_detail=decision.error_detail,
            schema_version=decision.schema_version,
        )
        async with self.database.sessions() as session:
            session.add(row)
            await session.flush()
            record_id = row.id
            await session.commit()
        return DecisionRecord(
            id=record_id,
            request=request,
            decision=decision,
            generated_prompt=request.prompt,
            raw_response=decision.raw_response,
            parsed_response=parsed,
            validation_errors=effective_validation_errors,
        )

    async def complete_match(
        self,
        match_id: UUID,
        *,
        winner: Side | None,
        turns: int,
        raw_showdown_log: str | None,
    ) -> None:
        async with self.database.sessions() as session:
            row = await session.get(MatchRow, str(match_id))
            if row is None:
                raise KeyError(str(match_id))
            validate_transition(MatchStatus(row.status), MatchStatus.COMPLETED)
            row.status = MatchStatus.COMPLETED.value
            row.winner = winner.value if winner else None
            row.turns = turns
            row.raw_showdown_log = raw_showdown_log
            row.updated_at = datetime.now(UTC)
            await session.commit()

    async def fail_match(self, match_id: UUID, error: str) -> None:
        async with self.database.sessions() as session:
            row = await session.get(MatchRow, str(match_id))
            if row is None:
                raise KeyError(str(match_id))
            validate_transition(MatchStatus(row.status), MatchStatus.FAILED)
            row.status = MatchStatus.FAILED.value
            row.error = error
            row.updated_at = datetime.now(UTC)
            await session.commit()

    async def cancel_match(self, match_id: UUID) -> None:
        async with self.database.sessions() as session:
            row = await session.get(MatchRow, str(match_id))
            if row is None:
                raise KeyError(str(match_id))
            validate_transition(MatchStatus(row.status), MatchStatus.CANCELLED)
            row.status = MatchStatus.CANCELLED.value
            row.updated_at = datetime.now(UTC)
            await session.commit()

    async def get_match(self, match_id: UUID) -> MatchArchive | None:
        async with self.database.sessions() as session:
            row = await session.scalar(
                select(MatchRow)
                .where(MatchRow.id == str(match_id))
                .options(
                    selectinload(MatchRow.players),
                    selectinload(MatchRow.events),
                    selectinload(MatchRow.decisions),
                )
            )
            return self._archive(row) if row else None

    async def list_matches(
        self,
        limit: int = 100,
        *,
        offset: int = 0,
        status: MatchStatus | None = None,
        tournament_id: UUID | None = None,
        standalone: bool | None = None,
        search: str | None = None,
    ) -> tuple[MatchSummary, ...]:
        async with self.database.sessions() as session:
            statement = select(MatchRow)
            if status is not None:
                statement = statement.where(MatchRow.status == status.value)
            if tournament_id is not None:
                statement = statement.where(MatchRow.tournament_id == str(tournament_id))
            if standalone is True:
                statement = statement.where(MatchRow.tournament_id.is_(None))
            elif standalone is False:
                statement = statement.where(MatchRow.tournament_id.is_not(None))
            if search:
                term = f"%{search.casefold()}%"
                statement = statement.where(
                    or_(
                        func.lower(MatchRow.id).like(term),
                        func.lower(MatchRow.config_json).like(term),
                    )
                )
            rows = (
                await session.scalars(
                    statement.order_by(MatchRow.created_at.desc()).offset(offset).limit(limit)
                )
            ).all()
            costs: dict[str, float] = {}
            if rows:
                cost_rows = (
                    await session.execute(
                        select(
                            AgentDecisionRow.match_id,
                            func.coalesce(func.sum(AgentDecisionRow.estimated_cost), 0.0),
                        )
                        .where(AgentDecisionRow.match_id.in_([row.id for row in rows]))
                        .group_by(AgentDecisionRow.match_id)
                    )
                ).all()
                costs = {match_id: float(cost or 0) for match_id, cost in cost_rows}
            return tuple(self._summary(row, float(costs.get(row.id, 0))) for row in rows)

    async def match_counts(self) -> dict[MatchStatus, int]:
        async with self.database.sessions() as session:
            rows = (
                await session.execute(
                    select(MatchRow.status, func.count()).group_by(MatchRow.status)
                )
            ).all()
            return {MatchStatus(value): int(count) for value, count in rows}

    @staticmethod
    def _summary(row: MatchRow, estimated_cost: float = 0) -> MatchSummary:
        return MatchSummary(
            id=UUID(row.id),
            created_at=row.created_at.replace(tzinfo=row.created_at.tzinfo or UTC),
            updated_at=row.updated_at.replace(tzinfo=row.updated_at.tzinfo or UTC),
            status=MatchStatus(row.status),
            config=MatchConfig.model_validate_json(row.config_json),
            engine=row.engine,
            winner=Side(row.winner) if row.winner else None,
            turns=row.turns,
            error=row.error,
            tournament_id=UUID(row.tournament_id) if row.tournament_id else None,
            series_id=UUID(row.series_id) if row.series_id else None,
            queue_position=row.queue_position,
            estimated_cost=estimated_cost,
        )

    @staticmethod
    def _archive(row: MatchRow) -> MatchArchive:
        config = MatchConfig.model_validate_json(row.config_json)
        events = tuple(
            BattleEvent(
                id=event.id,
                match_id=UUID(event.match_id),
                sequence=event.sequence,
                turn=event.turn,
                event_type=event.event_type,
                created_at=event.created_at.replace(tzinfo=event.created_at.tzinfo or UTC),
                logical_offset_ms=event.logical_offset_ms,
                payload=json.loads(event.payload_json),
                schema_version=event.schema_version,
            )
            for event in sorted(row.events, key=lambda item: item.sequence)
        )
        decisions = tuple(
            DecisionRecord(
                id=decision.id,
                request=AgentRequest.model_validate_json(decision.request_json),
                decision=AgentDecision.model_validate_json(decision.decision_json),
                generated_prompt=decision.generated_prompt,
                raw_response=decision.raw_response,
                parsed_response=json.loads(decision.parsed_response_json or "null"),
                validation_errors=tuple(json.loads(decision.validation_json)),
            )
            for decision in sorted(row.decisions, key=lambda item: item.decision_sequence)
        )
        return MatchArchive(
            id=UUID(row.id),
            created_at=row.created_at.replace(tzinfo=row.created_at.tzinfo or UTC),
            updated_at=row.updated_at.replace(tzinfo=row.updated_at.tzinfo or UTC),
            status=MatchStatus(row.status),
            config=config,
            engine=row.engine,
            engine_version=row.engine_version,
            showdown_version=row.showdown_version,
            poke_env_version=row.poke_env_version,
            schema_version=row.schema_version,
            winner=Side(row.winner) if row.winner else None,
            turns=row.turns,
            raw_showdown_log=row.raw_showdown_log,
            error=row.error,
            tournament_id=UUID(row.tournament_id) if row.tournament_id else None,
            series_id=UUID(row.series_id) if row.series_id else None,
            queue_position=row.queue_position,
            events=events,
            decisions=decisions,
        )
