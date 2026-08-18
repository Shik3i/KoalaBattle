from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from koalabattle.config import Settings
from koalabattle.core.models import (
    AgentType,
    MatchArchive,
    MatchConfig,
    MatchStatus,
    PlayerConfig,
    Side,
    TeamPolicy,
    TeamSource,
)
from koalabattle.formats.models import FormatDescriptor
from koalabattle.production import (
    CreateProduction,
    NarratorMode,
    NarratorSettings,
    ProductionService,
)
from koalabattle.production.models import ProductionStatus, ProductionTimeline
from koalabattle.service import BattleService
from koalabattle.video import CreateVideoExport, ExportStatus, VideoExportService

from .models import (
    OrchestratorCapabilities,
    OrchestratorPlan,
    OrchestratorPlayer,
    OrchestratorQuestion,
    OrchestratorRequest,
    OrchestratorRun,
    OrchestratorSettings,
    OrchestratorStatus,
    OrchestratorTeamResult,
)

_GENERATION_RE = re.compile(r"\b(?:gen(?:eration)?\s*)([1-9])\b", re.IGNORECASE)
_FORMAT_RE = re.compile(
    r"\bgen\s*([1-9])\s*(ou|uu|nu|pu|zu|lc|ubers|randombattle|customgame)\b",
    re.IGNORECASE,
)
_BEST_OF_RE = re.compile(r"\b(?:bo|best\s*of)\s*([13579])\b", re.IGNORECASE)
_MODEL_RE = re.compile(r"\b(?:model\s+)?([a-z0-9._-]+/[a-z0-9._-]+)\b", re.IGNORECASE)


class OrchestratorService:
    """Run a complete team-build -> battle -> production -> video workflow.

    The run registry is intentionally process-local: the actual match, production and video
    records remain the durable source of truth. A run is a coordination handle for an external
    agent and can always be recovered from those IDs after a process restart.
    """

    def __init__(
        self,
        battles: BattleService,
        production: ProductionService,
        video: VideoExportService,
        settings: Settings,
    ) -> None:
        self.battles = battles
        self.production = production
        self.video = video
        self.settings = settings
        self._runs: dict[UUID, OrchestratorRun] = {}
        self._tasks: dict[UUID, asyncio.Task[None]] = {}

    def capabilities(self) -> OrchestratorCapabilities:
        return OrchestratorCapabilities(
            default_model=self.settings.orchestrator_default_model,
        )

    def plan(self, request: OrchestratorRequest) -> OrchestratorPlan:
        instruction = request.instruction.strip()
        settings = request.settings
        warnings: list[str] = []
        questions: list[OrchestratorQuestion] = []

        format_id = settings.format or _format_from_instruction(instruction)
        if format_id is None:
            if instruction:
                format_id = "gen9ou"
                warnings.append("No generation/format was explicit; defaulted to gen9ou.")
            else:
                questions.append(
                    OrchestratorQuestion(
                        field="settings.format",
                        question="Which Showdown format should run, for example gen1ou?",
                        reason="A battle format is required before teams can be built.",
                    )
                )
                format_id = "gen9ou"

        descriptor = self.battles.formats.get(format_id)
        if descriptor is None:
            questions.append(
                OrchestratorQuestion(
                    field="settings.format",
                    question=f"Which supported format should replace {format_id}?",
                    reason=f"{format_id} is not present in the pinned Showdown catalog.",
                )
            )
            descriptor = None
        elif not descriptor.supported:
            questions.append(
                OrchestratorQuestion(
                    field="settings.format",
                    question=f"Which supported singles format should replace {descriptor.id}?",
                    reason=descriptor.unsupported_reason or "The format is not runnable here.",
                )
            )

        if descriptor is not None and settings.build_teams and descriptor.random_team:
            if settings.format is None and _mentions_team_building(instruction):
                format_id = f"gen{descriptor.generation}ou"
                descriptor = self.battles.formats.get(format_id)
                warnings.append(
                    f"Random-team format was replaced with {format_id} because both AIs "
                    "must build teams."
                )
            else:
                questions.append(
                    OrchestratorQuestion(
                        field="settings.build_teams",
                        question="Should I build teams, or should Showdown provide random teams?",
                        reason=(
                            f"{format_id} supplies random teams and rejects custom team exports."
                        ),
                    )
                )

        if descriptor is not None and settings.build_teams and not descriptor.random_team:
            missing = [
                player.display_name
                for player in settings.players
                if player.team_snapshot_id is not None
            ]
            if missing:
                # Existing snapshots are a valid explicit override, but the default workflow
                # builds both teams. The question below only applies when exactly one was given.
                if len(missing) != 2:
                    questions.append(
                        OrchestratorQuestion(
                            field="settings.players.team_snapshot_id",
                            question=(
                                "Provide a validated snapshot for both players or enable "
                                "team building for both."
                            ),
                            reason=(
                                "A fixed Showdown battle cannot mix generated and missing teams."
                            ),
                        )
                    )

        if descriptor is not None and not settings.build_teams and not descriptor.random_team:
            for player in settings.players:
                if player.team_snapshot_id is None:
                    questions.append(
                        OrchestratorQuestion(
                            field=f"settings.players[{player.display_name}].team_snapshot_id",
                            question=(
                                f"Which validated Showdown team should {player.display_name} use?"
                            ),
                            reason=(
                                f"{descriptor.id} requires a custom team when build_teams is false."
                            ),
                        )
                    )

        instruction_best_of = _best_of_from_instruction(instruction)
        best_of = instruction_best_of if settings.best_of == 1 else settings.best_of
        if best_of is not None and best_of != 1:
            questions.append(
                OrchestratorQuestion(
                    field="settings.best_of",
                    question=(
                        "Only Bo1 is currently supported by this orchestration workflow. "
                        "Continue with Bo1?"
                    ),
                    reason=(
                        f"The instruction requested Bo{best_of}, but series orchestration "
                        "is not enabled yet."
                    ),
                )
            )

        settings = self._resolve_settings(settings, instruction, format_id)
        try:
            self._validate_output_settings(settings)
        except ValueError as error:
            questions.append(
                OrchestratorQuestion(
                    field="settings.video_preset_id",
                    question="Which available video preset should be used?",
                    reason=str(error),
                )
            )

        if descriptor is not None and descriptor.id != format_id:
            descriptor = self.battles.formats.get(format_id)
        return OrchestratorPlan(
            ready=not questions and descriptor is not None and descriptor.supported,
            settings=settings,
            questions=tuple(_deduplicate_questions(questions)),
            warnings=tuple(dict.fromkeys(warnings)),
            format_name=descriptor.name if descriptor is not None else None,
        )

    async def create(self, request: OrchestratorRequest) -> OrchestratorRun:
        plan = self.plan(request)
        if not plan.ready:
            detail = "; ".join(item.reason for item in plan.questions)
            raise ValueError(detail or "orchestrator settings are incomplete")
        now = datetime.now(UTC)
        run = OrchestratorRun(
            id=uuid4(),
            status=OrchestratorStatus.QUEUED,
            stage="Queued",
            progress=0,
            settings=plan.settings,
            created_at=now,
            updated_at=now,
        )
        self._runs[run.id] = run
        task = asyncio.create_task(self._execute(run.id), name=f"orchestrator-run-{run.id}")
        self._tasks[run.id] = task
        return run

    async def get(self, run_id: UUID) -> OrchestratorRun:
        run = self._runs.get(run_id)
        if run is None:
            raise KeyError(str(run_id))
        if run.video_job_id is not None and run.status not in {
            OrchestratorStatus.COMPLETED,
            OrchestratorStatus.FAILED,
            OrchestratorStatus.CANCELLED,
        }:
            await self._refresh_video_status(run_id)
        return self._runs[run_id]

    async def list(self, limit: int = 50) -> tuple[OrchestratorRun, ...]:
        runs = sorted(self._runs.values(), key=lambda item: item.created_at, reverse=True)
        return tuple(runs[:limit])

    async def cancel(self, run_id: UUID) -> OrchestratorRun:
        run = await self.get(run_id)
        if run.status in {
            OrchestratorStatus.COMPLETED,
            OrchestratorStatus.FAILED,
            OrchestratorStatus.CANCELLED,
        }:
            return run
        if run.match_id is not None:
            try:
                await self.battles.cancel_match(run.match_id)
            except (KeyError, ValueError):
                pass
        if run.video_job_id is not None:
            try:
                await self.video.cancel(run.video_job_id)
            except KeyError:
                pass
        task = self._tasks.get(run_id)
        if task is not None and not task.done():
            task.cancel()
        return await self._set(
            run_id,
            status=OrchestratorStatus.CANCELLED,
            stage="Cancelled",
            progress=run.progress,
            completed_at=datetime.now(UTC),
        )

    async def close(self) -> None:
        for task in self._tasks.values():
            if not task.done():
                task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    def _resolve_settings(
        self, settings: OrchestratorSettings, instruction: str, format_id: str
    ) -> OrchestratorSettings:
        text = instruction.casefold()
        updates: dict[str, Any] = {"format": format_id}
        if "banter" in text or "trash talk" in text or "taunt" in text:
            updates["banter_enabled"] = True
        if any(
            token in text
            for token in ("narrator", "commentator", "stadium commentary", "stadium narrator")
        ):
            updates["narrator_enabled"] = True
        if any(token in text for token in ("without narrator", "no narrator", "ohne narrator")):
            updates["narrator_enabled"] = False
        if "broadcast commentary" in text:
            updates.update(narrator_enabled=True, narrator_mode="broadcast")
        if "full commentary" in text or "vollständiger kommentar" in text:
            updates.update(narrator_enabled=True, narrator_mode="full")
        if "minimal highlights" in text or "nur highlights" in text:
            updates.update(
                narrator_enabled=True,
                narrator_profile_id="minimal-highlights-v1",
                narrator_mode="highlights",
            )
        if "battle revolution" in text or "colosseum broadcast" in text:
            updates.update(
                narrator_enabled=True,
                narrator_profile_id="battle-revolution-v1",
                narrator_mode="broadcast",
            )
        if any(token in text for token in ("video", "render", "export")):
            updates["auto_render"] = True
        model_match = _MODEL_RE.search(instruction)
        model = model_match.group(1) if model_match else None
        if "gemma" in text:
            model = self.settings.orchestrator_default_model
        if model is not None:
            updates["players"] = tuple(
                player.model_copy(update={"model": model}) for player in settings.players
            )
        players = tuple(
            self._resolve_player(player) for player in updates.get("players", settings.players)
        )
        updates["players"] = players
        return settings.model_copy(update=updates)

    def _resolve_player(self, player: OrchestratorPlayer) -> OrchestratorPlayer:
        configuration = player.configuration
        if player.provider.value == "openai-compatible" and not configuration.base_url:
            configuration = configuration.model_copy(
                update={"base_url": self.settings.orchestrator_local_base_url}
            )
        return player.model_copy(update={"configuration": configuration})

    def _validate_output_settings(self, settings: OrchestratorSettings) -> None:
        if settings.production_profile_id not in {
            profile.id for profile in self.production.profiles()
        }:
            raise ValueError(f"unknown production profile: {settings.production_profile_id}")
        if settings.video_preset_id not in {preset.id for preset in self.video.presets()}:
            raise ValueError(f"unknown video preset: {settings.video_preset_id}")

    async def _execute(self, run_id: UUID) -> None:
        try:
            run = await self.get(run_id)
            descriptor = self.battles.formats.get(run.settings.format or "")
            if descriptor is None:
                raise ValueError("resolved Showdown format disappeared from the catalog")
            team_results = await self._build_teams(run_id, run.settings, descriptor)
            await self._set(run_id, teams=team_results)
            if any(not result.success for result in team_results):
                errors = "; ".join(
                    f"{result.participant}: {', '.join(result.errors) or 'team build failed'}"
                    for result in team_results
                    if not result.success
                )
                raise ValueError(errors)

            match = await self._create_match(run.settings, descriptor, team_results)
            await self._set(
                run_id,
                status=OrchestratorStatus.QUEUED_MATCH,
                stage="Match queued",
                progress=35,
                match_id=match.id,
            )
            await self._wait_for_match(run_id, match.id)
            archive = await self.battles.repository.get_match(match.id)
            if archive is None or archive.status is not MatchStatus.COMPLETED:
                raise ValueError(archive.error if archive else "match archive disappeared")

            await self._set(
                run_id,
                status=OrchestratorStatus.PREPARING_PRODUCTION,
                stage="Preparing replay production",
                progress=65,
            )
            await self.production.create(
                match.id,
                CreateProduction(
                    profile_id=run.settings.production_profile_id,
                    narrator=NarratorSettings(
                        enabled=run.settings.narrator_enabled,
                        profile_id=run.settings.narrator_profile_id,
                        mode=NarratorMode(run.settings.narrator_mode),
                        voice_preset_id=run.settings.narrator_voice_preset_id,
                    ),
                ),
            )
            production = await self._wait_for_production(
                match.id, run.settings.production_profile_id
            )
            await self._set(run_id, production_id=production.id, progress=75)
            if not run.settings.auto_render:
                await self._set(
                    run_id,
                    status=OrchestratorStatus.COMPLETED,
                    stage="Replay production ready",
                    progress=100,
                    completed_at=datetime.now(UTC),
                )
                return

            job = await self.video.create(
                CreateVideoExport(
                    production_id=production.id,
                    preset_id=run.settings.video_preset_id,
                    output_name=(
                        f"{_safe_name(run.settings.format or 'battle')}-orchestrated-"
                        f"{str(run.id)[:8]}"
                    ),
                    encoder=run.settings.encoder,
                    render_engine=run.settings.render_engine,
                )
            )
            await self._set(
                run_id,
                status=OrchestratorStatus.QUEUED_VIDEO,
                stage="Video export queued",
                progress=80,
                video_job_id=job.id,
            )
            await self._wait_for_video(run_id, job.id)
        except asyncio.CancelledError:
            current = self._runs.get(run_id)
            if current is not None and current.status not in {
                OrchestratorStatus.CANCELLED,
                OrchestratorStatus.COMPLETED,
                OrchestratorStatus.FAILED,
            }:
                await self._set(
                    run_id,
                    status=OrchestratorStatus.CANCELLED,
                    stage="Cancelled",
                    completed_at=datetime.now(UTC),
                )
            return
        except Exception as error:
            await self._set(
                run_id,
                status=OrchestratorStatus.FAILED,
                stage="Failed",
                error=f"{type(error).__name__}: {error}",
                completed_at=datetime.now(UTC),
            )

    async def _build_teams(
        self, run_id: UUID, settings: OrchestratorSettings, descriptor: FormatDescriptor
    ) -> tuple[OrchestratorTeamResult, ...]:
        await self._set(
            run_id,
            status=OrchestratorStatus.BUILDING_TEAMS,
            stage="Building both Showdown teams in parallel",
            progress=5,
        )
        if not settings.build_teams:
            return tuple(
                OrchestratorTeamResult(
                    participant=player.display_name,
                    snapshot_id=player.team_snapshot_id,
                    success=player.team_snapshot_id is not None or descriptor.random_team,
                )
                for player in settings.players
            )

        from koalabattle.teams.models import TeamBuildRequest, TeamPromptContext

        context = TeamPromptContext(
            format_name=descriptor.name,
            generation=descriptor.generation,
            game_type=descriptor.game_type,
            mechanics=descriptor.mechanics.actionable(),
            absent_mechanics=descriptor.mechanics.unavailable(),
            has_items=descriptor.mechanics.items,
            has_abilities=descriptor.mechanics.abilities,
            has_natures=descriptor.mechanics.natures,
        )

        async def build(player: OrchestratorPlayer) -> OrchestratorTeamResult:
            try:
                audit, snapshot = await self.battles.build_team(
                    TeamBuildRequest(
                        name=f"{player.display_name} · {descriptor.id}",
                        participant=player.display_name,
                        format=descriptor.id,
                        provider=player.provider,
                        model=player.model,
                        configuration=player.configuration,
                        context=context,
                    )
                )
                errors = tuple(error for batch in audit.validation_errors for error in batch)
                return OrchestratorTeamResult(
                    participant=player.display_name,
                    audit_id=audit.id,
                    snapshot_id=snapshot.id if snapshot else None,
                    success=audit.success and snapshot is not None,
                    errors=errors,
                )
            except Exception as error:
                return OrchestratorTeamResult(
                    participant=player.display_name,
                    success=False,
                    errors=(f"{type(error).__name__}: {error}",),
                )

        return tuple(await asyncio.gather(*(build(player) for player in settings.players)))

    async def _create_match(
        self,
        settings: OrchestratorSettings,
        descriptor: FormatDescriptor,
        teams: tuple[OrchestratorTeamResult, ...],
    ) -> MatchArchive:
        players: list[PlayerConfig] = []
        for side, player, team in zip((Side.P1, Side.P2), settings.players, teams, strict=True):
            custom = not descriptor.random_team
            players.append(
                PlayerConfig(
                    side=side,
                    display_name=player.display_name,
                    agent_type=AgentType.API,
                    provider=player.provider.value,
                    model=player.model,
                    configuration=player.configuration,
                    team_source=(
                        TeamSource.AGENT_GENERATED if custom else TeamSource.SHOWDOWN_RANDOM
                    ),
                    team_snapshot_id=team.snapshot_id if custom else None,
                )
            )
        return await self.battles.create_match(
            MatchConfig(
                name=f"{descriptor.name} · orchestrated Bo1",
                format=descriptor.id,
                players=tuple(players),
                banter_enabled=settings.banter_enabled,
                team_policy=(
                    TeamPolicy.FIXED if not descriptor.random_team else TeamPolicy.SHOWDOWN_RANDOM
                ),
            )
        )

    async def _wait_for_match(self, run_id: UUID, match_id: UUID) -> None:
        while True:
            archive = await self.battles.repository.get_match(match_id)
            if archive is None:
                raise ValueError("match archive disappeared")
            if archive.status in {
                MatchStatus.RUNNING,
                MatchStatus.WAITING,
                MatchStatus.PAUSED,
            }:
                await self._set(
                    run_id,
                    status=OrchestratorStatus.RUNNING_MATCH,
                    stage=f"Bo1 running · turn {archive.turns}",
                    progress=min(60, 35 + archive.turns * 0.5),
                )
            if archive.status in {
                MatchStatus.COMPLETED,
                MatchStatus.FAILED,
                MatchStatus.CANCELLED,
                MatchStatus.INTERRUPTED,
            }:
                return
            await asyncio.sleep(1)

    async def _wait_for_production(self, match_id: UUID, profile_id: str) -> ProductionTimeline:
        while True:
            productions = await self.production.repository.list_for_match(match_id)
            candidates = [item for item in productions if item.profile.id == profile_id]
            if candidates:
                production = candidates[0]
                if production.status is ProductionStatus.FAILED:
                    raise ValueError(
                        str(production.overrides.get("finalization_error") or "production failed")
                    )
                if production.status in {
                    ProductionStatus.FINALIZED,
                    ProductionStatus.READY,
                    ProductionStatus.PARTIAL,
                }:
                    return await self.production.ensure_prepared(production.id)
            await asyncio.sleep(1)

    async def _wait_for_video(self, run_id: UUID, job_id: UUID) -> None:
        while True:
            job = await self.video.require(job_id)
            if job.status in {
                ExportStatus.RENDERING,
                ExportStatus.ENCODING,
                ExportStatus.FINALIZING,
            }:
                await self._set(
                    run_id,
                    status=OrchestratorStatus.RENDERING_VIDEO,
                    stage=job.stage,
                    progress=80 + (job.progress * 0.2),
                )
            if job.status is ExportStatus.COMPLETED:
                await self._set(
                    run_id,
                    status=OrchestratorStatus.COMPLETED,
                    stage="Battle, replay and video complete",
                    progress=100,
                    completed_at=datetime.now(UTC),
                )
                return
            if job.status in {ExportStatus.FAILED, ExportStatus.CANCELLED}:
                raise ValueError(job.error_detail or f"video export {job.status.value}")
            await asyncio.sleep(2)

    async def _refresh_video_status(self, run_id: UUID) -> None:
        run = self._runs[run_id]
        if run.video_job_id is None:
            return
        try:
            job = await self.video.require(run.video_job_id)
        except KeyError:
            return
        if job.status is ExportStatus.COMPLETED and run.status is not OrchestratorStatus.COMPLETED:
            await self._set(
                run_id,
                status=OrchestratorStatus.COMPLETED,
                stage="Battle, replay and video complete",
                progress=100,
                completed_at=datetime.now(UTC),
            )
        elif job.status in {ExportStatus.RENDERING, ExportStatus.ENCODING, ExportStatus.FINALIZING}:
            await self._set(
                run_id,
                status=OrchestratorStatus.RENDERING_VIDEO,
                stage=job.stage,
                progress=80 + job.progress * 0.2,
            )

    async def _set(self, run_id: UUID, **updates: Any) -> OrchestratorRun:
        current = self._runs[run_id]
        updated = current.model_copy(update={**updates, "updated_at": datetime.now(UTC)})
        self._runs[run_id] = updated
        return updated


def _format_from_instruction(instruction: str) -> str | None:
    match = _FORMAT_RE.search(instruction)
    if match:
        generation, suffix = match.groups()
        return f"gen{generation}{suffix.casefold()}"
    generation = _GENERATION_RE.search(instruction)
    if generation:
        suffix = "ou" if _mentions_team_building(instruction) else "randombattle"
        return f"gen{generation.group(1)}{suffix}"
    return None


def _mentions_team_building(instruction: str) -> bool:
    text = instruction.casefold()
    return any(token in text for token in ("team", "teams", "team bauen", "team bauen lassen"))


def _best_of_from_instruction(instruction: str) -> int | None:
    match = _BEST_OF_RE.search(instruction)
    return int(match.group(1)) if match else None


def _deduplicate_questions(
    questions: list[OrchestratorQuestion],
) -> tuple[OrchestratorQuestion, ...]:
    seen: set[tuple[str, str]] = set()
    result: list[OrchestratorQuestion] = []
    for question in questions:
        key = (question.field, question.question)
        if key not in seen:
            seen.add(key)
            result.append(question)
    return tuple(result)


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")[:80] or "battle"
