from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING
from urllib.error import URLError
from urllib.request import urlopen
from uuid import UUID

from koalabattle import __version__
from koalabattle.agents import (
    Agent,
    ApiAgent,
    ManualAgent,
    ManualDecisionBroker,
    MatchCostBudget,
    RandomAgent,
)
from koalabattle.agents.providers import (
    AnthropicProvider,
    DeepSeekProvider,
    FakeProvider,
    GeminiProvider,
    LLMProvider,
    OpenAICompatibleProvider,
    OpenAIProvider,
    ProviderModel,
)
from koalabattle.config import Settings
from koalabattle.core.models import (
    AgentConfiguration,
    AgentDecision,
    AgentLifecycleState,
    AgentRequest,
    AgentType,
    GenericMatchResult,
    GenericResultStatus,
    MatchArchive,
    MatchConfig,
    MatchStatus,
    MatchSummary,
    PlayerConfig,
    ProviderKind,
    Side,
    TeamSource,
)
from koalabattle.core.pricing import PricingTable
from koalabattle.engines.base import EngineEventSink
from koalabattle.engines.showdown import ShowdownBattleEngine
from koalabattle.formats import FormatCatalogService, describe_format
from koalabattle.orchestration.runtime import MatchSupervisor, RealtimeHub
from koalabattle.provider_credentials import ProviderCredentialStore
from koalabattle.storage import BattleRepository
from koalabattle.teams import (
    ShowdownTeamValidator,
    TeamBuildAudit,
    TeamBuilder,
    TeamBuildRequest,
    TeamRepository,
    TeamSnapshot,
    TeamValidationResult,
    unwrap_team_text,
)
from koalabattle.tournaments.models import CreateTournament, TournamentArchive, TournamentStatus
from koalabattle.tournaments.repository import TournamentRepository

if TYPE_CHECKING:
    from koalabattle.challenges.models import DraftControllerSnapshot


class BattleService:
    def __init__(
        self,
        repository: BattleRepository,
        settings: Settings,
        tournament_repository: TournamentRepository | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.tournaments = tournament_repository or TournamentRepository(repository.database)
        self.teams = TeamRepository(repository.database)
        self.team_validator = ShowdownTeamValidator(settings.team_validator_url)
        self.team_builder = TeamBuilder(self.teams, self.team_validator)
        self.formats = FormatCatalogService(settings.team_validator_url)
        self.hub = RealtimeHub()
        self.pricing = PricingTable(settings.pricing_table_json, settings.pricing_version)
        # Provider credentials never enter MatchConfig, the database, logs, or API responses.
        # Docker mounts the gitignored host .env as the optional persistent credentials file.
        self.provider_credentials = ProviderCredentialStore(settings.provider_credentials_file)
        self._runtime_provider_keys: dict[ProviderKind, str | None] = {
            provider: value for provider, value in self.provider_credentials.load().items()
        }
        self._persisted_provider_keys = set(self._runtime_provider_keys)
        self._runtime_provider_base_urls: dict[ProviderKind, str] = {}
        self._challenge_terminal_hook: Callable[[UUID, MatchArchive], Awaitable[None]] | None = None
        self.supervisor = MatchSupervisor(
            repository,
            self.hub,
            self._engine_factory,
            self._build_agents,
            concurrency_limit=settings.max_concurrent_matches,
            eligible=self._eligible_for_start,
            on_start=self._match_starting,
            on_terminal=self._match_terminal,
        )

    def set_challenge_terminal_hook(
        self, hook: Callable[[UUID, MatchArchive], Awaitable[None]]
    ) -> None:
        self._challenge_terminal_hook = hook

    async def start(self) -> tuple[UUID, ...]:
        await self.formats.refresh()
        interrupted = await self.supervisor.start()
        await self.schedule_tournaments()
        return interrupted

    def _engine_factory(self) -> ShowdownBattleEngine:
        return ShowdownBattleEngine(
            self.settings.showdown_websocket_url,
            self.settings.showdown_auth_url,
        )

    async def create_match(
        self,
        config: MatchConfig,
        *,
        tournament_id: UUID | None = None,
        series_id: UUID | None = None,
        challenge_run_id: UUID | None = None,
        challenge_stage_id: str | None = None,
    ) -> MatchArchive:
        hydrated_players: list[PlayerConfig] = []
        for player in config.players:
            if player.team_source is TeamSource.SHOWDOWN_RANDOM:
                hydrated_players.append(player)
                continue
            if player.team_snapshot_id is None:
                raise ValueError(f"{player.side.value} is missing a validated team snapshot")
            snapshot = await self.teams.get(player.team_snapshot_id)
            if snapshot is None:
                raise ValueError(f"team snapshot {player.team_snapshot_id} was not found")
            if snapshot.format != config.format:
                raise ValueError(
                    f"team snapshot {snapshot.id} is for {snapshot.format}, not {config.format}"
                )
            hydrated_players.append(
                player.model_copy(
                    update={
                        "team_source": snapshot.source,
                        "team_export": snapshot.normalized_export,
                        "team_packed": snapshot.packed_team,
                    }
                )
            )
        config = config.model_copy(update={"players": tuple(hydrated_players)})
        self._validate_provider_configuration(config)
        return await self.supervisor.create_match(
            config,
            engine_version=self._engine_factory().version,
            showdown_version=self.settings.showdown_version,
            poke_env_version="0.15.0",
            tournament_id=tournament_id,
            series_id=series_id,
            challenge_run_id=challenge_run_id,
            challenge_stage_id=challenge_stage_id,
        )

    async def validate_team(
        self,
        *,
        name: str,
        team_text: str,
        format_id: str,
        source: TeamSource,
        save: bool,
    ) -> tuple[TeamValidationResult, TeamSnapshot | None]:
        team_text = unwrap_team_text(team_text)
        validation = await self.team_validator.validate(team_text, format_id)
        snapshot = None
        if validation.valid and save:
            snapshot = await self.teams.create_snapshot(
                name=name,
                source=source,
                submitted_text=team_text,
                validation=validation,
            )
        return validation, snapshot

    async def build_team(
        self, request: TeamBuildRequest
    ) -> tuple[TeamBuildAudit, TeamSnapshot | None]:
        player = PlayerConfig(
            side=Side.P1,
            display_name=request.participant,
            agent_type=AgentType.API,
            provider=request.provider.value,
            model=request.model,
            configuration=request.configuration,
        )
        provider = self._provider_for(player)
        return await self.team_builder.build(request, provider)

    def _build_agents(
        self,
        config: MatchConfig,
        sink: EngineEventSink,
        manual_broker: ManualDecisionBroker,
    ) -> dict[Side, Agent]:
        agents: dict[Side, Agent] = {}
        match_budget = MatchCostBudget(config.limits.maximum_total_cost)

        async def state_callback(
            side: Side,
            state: AgentLifecycleState,
            turn: int,
            payload: dict[str, object],
        ) -> None:
            await sink.emit(
                "agent_progress" if "progress" in payload else "agent_state",
                turn,
                {"side": side.value, "state": state.value, **payload},
            )

        for index, player in enumerate(config.players):
            seed = None if config.random_seed is None else config.random_seed + index
            if player.agent_type is AgentType.RANDOM:
                agents[player.side] = RandomAgent(seed)
            elif player.agent_type in {AgentType.MANUAL, AgentType.HUMAN}:
                agents[player.side] = ManualAgent(manual_broker)
            else:
                agents[player.side] = ApiAgent(
                    self._provider_for(player),
                    player.model or "",
                    player.configuration,
                    state_callback=state_callback,
                    pricing=self.pricing,
                    manual_fallback=ManualAgent(manual_broker),
                    match_budget=match_budget,
                    seed=seed,
                )
        return agents

    def _validate_provider_configuration(self, config: MatchConfig) -> None:
        for player in config.players:
            if player.agent_type is AgentType.API:
                self._provider_for(player)

    def _provider_for(self, player: PlayerConfig) -> LLMProvider:
        if player.provider is None:
            raise ValueError("API agent provider is missing")
        kind = ProviderKind(player.provider)
        if kind is ProviderKind.OPENAI:
            key = self._required_key(kind, self._provider_key(kind, self.settings.openai_api_key))
            return OpenAIProvider(key)
        if kind is ProviderKind.GEMINI:
            key = self._required_key(kind, self._provider_key(kind, self.settings.gemini_api_key))
            return GeminiProvider(key)
        if kind is ProviderKind.ANTHROPIC:
            key = self._required_key(
                kind, self._provider_key(kind, self.settings.anthropic_api_key)
            )
            return AnthropicProvider(key)
        if kind is ProviderKind.DEEPSEEK:
            key = self._required_key(kind, self._provider_key(kind, self.settings.deepseek_api_key))
            return DeepSeekProvider(key)
        if kind is ProviderKind.OPENAI_COMPATIBLE:
            base_url = player.configuration.base_url or self._runtime_provider_base_urls.get(kind)
            if not base_url:
                raise ValueError(
                    "openai-compatible is missing a base URL; configure it in Settings or the match"
                )
            return OpenAICompatibleProvider(
                base_url,
                self._provider_key(kind, self.settings.openai_compatible_api_key),
            )
        if not self.settings.enable_fake_provider:
            raise ValueError("Fake provider is disabled; set KOALABATTLE_ENABLE_FAKE_PROVIDER=true")
        return FakeProvider(player.configuration.fake_scenario)

    def provider_for_draft(self, controller: DraftControllerSnapshot) -> LLMProvider:
        return self._provider_for(
            PlayerConfig(
                side=Side.P1,
                display_name="Challenge draft controller",
                agent_type=AgentType.API,
                provider=controller.provider.value if controller.provider else None,
                model=controller.model,
                configuration=controller.configuration,
            )
        )

    @staticmethod
    def _required_key(kind: ProviderKind, value: str | None) -> str:
        if not value:
            variable = f"KOALABATTLE_{kind.value.upper()}_API_KEY"
            raise ValueError(f"{kind.value} is not configured; set {variable}")
        return value

    def _provider_key(self, kind: ProviderKind, environment_value: str | None) -> str | None:
        if kind in self._runtime_provider_keys:
            return self._runtime_provider_keys[kind]
        return environment_value

    def configure_provider(
        self,
        provider: ProviderKind,
        api_key: str | None,
        base_url: str | None,
        *,
        clear: bool = False,
    ) -> dict[str, object]:
        normalized_base_url: str | None = None
        if base_url is not None:
            normalized_base_url = base_url.strip().rstrip("/")
            if normalized_base_url:
                # Reuse AgentConfiguration's URL validation without persisting the value in a
                # player or match archive.
                AgentConfiguration(base_url=normalized_base_url)

        key = api_key.strip() if api_key else ""
        if clear:
            self.provider_credentials.save(provider, None)
            # An explicit clear must override a key inherited by this already-running container.
            self._runtime_provider_keys[provider] = None
            self._persisted_provider_keys.discard(provider)
        elif key:
            self.provider_credentials.save(provider, key)
            self._runtime_provider_keys[provider] = key
            if self.provider_credentials.enabled:
                self._persisted_provider_keys.add(provider)

        if clear:
            self._runtime_provider_base_urls.pop(provider, None)
        elif base_url is not None:
            if normalized_base_url:
                self._runtime_provider_base_urls[provider] = normalized_base_url
            else:
                self._runtime_provider_base_urls.pop(provider, None)

        status = next(item for item in self.provider_status() if item["id"] == provider.value)
        return {
            "provider": provider.value,
            "configured": status["configured"],
            "source": status["source"],
        }

    def provider_status(self) -> tuple[dict[str, object], ...]:
        catalog: dict[ProviderKind, dict[str, object]] = {
            ProviderKind.OPENAI: {
                "label": "OpenAI",
                "default_model": "gpt-5-mini",
                "default_base_url": "https://api.openai.com/v1",
                "requires_api_key": True,
                "environment_variable": "OPENAI_API_KEY",
            },
            ProviderKind.GEMINI: {
                "label": "Google Gemini",
                "default_model": "gemini-2.5-flash",
                "default_base_url": None,
                "requires_api_key": True,
                "environment_variable": "GEMINI_API_KEY",
            },
            ProviderKind.ANTHROPIC: {
                "label": "Anthropic",
                "default_model": "claude-sonnet-4-5",
                "default_base_url": None,
                "requires_api_key": True,
                "environment_variable": "ANTHROPIC_API_KEY",
            },
            ProviderKind.DEEPSEEK: {
                "label": "DeepSeek",
                "default_model": "deepseek-v4-flash",
                "known_models": ["deepseek-v4-flash", "deepseek-v4-pro"],
                "default_base_url": "https://api.deepseek.com",
                "requires_api_key": True,
                "environment_variable": "DEEPSEEK_API_KEY",
            },
            ProviderKind.OPENAI_COMPATIBLE: {
                "label": "OpenAI-compatible",
                "default_model": "local-model",
                "known_models": [],
                "default_base_url": self._runtime_provider_base_urls.get(
                    ProviderKind.OPENAI_COMPATIBLE
                ),
                "requires_api_key": False,
                "environment_variable": "KOALABATTLE_OPENAI_COMPATIBLE_API_KEY",
            },
            ProviderKind.FAKE: {
                "label": "Deterministic Fake",
                "default_model": "fake-battle-v1",
                "known_models": ["fake-battle-v1"],
                "default_base_url": None,
                "requires_api_key": False,
                "environment_variable": None,
            },
        }
        for item in catalog.values():
            item.setdefault("known_models", [])
        configured = {
            ProviderKind.OPENAI: bool(
                self._provider_key(ProviderKind.OPENAI, self.settings.openai_api_key)
            ),
            ProviderKind.GEMINI: bool(
                self._provider_key(ProviderKind.GEMINI, self.settings.gemini_api_key)
            ),
            ProviderKind.ANTHROPIC: bool(
                self._provider_key(ProviderKind.ANTHROPIC, self.settings.anthropic_api_key)
            ),
            ProviderKind.DEEPSEEK: bool(
                self._provider_key(ProviderKind.DEEPSEEK, self.settings.deepseek_api_key)
            ),
            ProviderKind.OPENAI_COMPATIBLE: True,
            ProviderKind.FAKE: self.settings.enable_fake_provider,
        }
        environment_configured = {
            ProviderKind.OPENAI: bool(self.settings.openai_api_key),
            ProviderKind.GEMINI: bool(self.settings.gemini_api_key),
            ProviderKind.ANTHROPIC: bool(self.settings.anthropic_api_key),
            ProviderKind.DEEPSEEK: bool(self.settings.deepseek_api_key),
            ProviderKind.OPENAI_COMPATIBLE: bool(self.settings.openai_compatible_api_key),
            ProviderKind.FAKE: self.settings.enable_fake_provider,
        }
        capabilities = {
            ProviderKind.OPENAI: OpenAIProvider.capabilities,
            ProviderKind.GEMINI: GeminiProvider.capabilities,
            ProviderKind.ANTHROPIC: AnthropicProvider.capabilities,
            ProviderKind.DEEPSEEK: DeepSeekProvider.capabilities,
            ProviderKind.OPENAI_COMPATIBLE: OpenAICompatibleProvider.capabilities,
            ProviderKind.FAKE: FakeProvider.capabilities,
        }
        return tuple(
            {
                "id": kind.value,
                **catalog[kind],
                "configured": configured[kind],
                "source": self._provider_source(kind, environment_configured[kind]),
                "capabilities": capabilities[kind].model_dump(mode="json"),
            }
            for kind in ProviderKind
        )

    def _provider_source(self, kind: ProviderKind, environment_configured: bool) -> str:
        if kind in self._persisted_provider_keys:
            return "saved-env"
        if self._runtime_provider_keys.get(kind) or kind in self._runtime_provider_base_urls:
            return "runtime"
        if environment_configured:
            return "environment"
        if kind is ProviderKind.OPENAI_COMPATIBLE:
            return "custom-url"
        return "none"

    async def list_provider_models(
        self, provider: ProviderKind, base_url: str | None = None
    ) -> tuple[ProviderModel, ...]:
        configuration = AgentConfiguration(
            base_url=base_url or self._runtime_provider_base_urls.get(provider)
        )
        player = PlayerConfig(
            side=Side.P1,
            display_name="Model discovery",
            agent_type=AgentType.API,
            provider=provider.value,
            model="discovery-placeholder",
            configuration=configuration,
        )
        return await self._provider_for(player).list_models()

    async def pending_for_match(self, match_id: UUID) -> tuple[AgentRequest, ...]:
        return await self.supervisor.pending_for_match(match_id)

    async def validate_manual_decision(self, request_id: UUID, raw_response: str) -> AgentDecision:
        session, pending = await self.supervisor.find_pending(request_id)
        parsed = await session.manual_broker.validate(request_id, raw_response)
        return AgentDecision(
            request_id=pending.request_id,
            match_id=pending.match_id,
            side=pending.side,
            turn=pending.turn,
            decision_sequence=pending.decision_sequence,
            action=parsed.action,
            commentary=parsed.commentary,
            provider="manual",
            model="web-chat",
        )

    async def submit_manual_decision(self, request_id: UUID, raw_response: str) -> None:
        session, _ = await self.supervisor.find_pending(request_id)
        await session.submit_manual_decision(request_id, raw_response)

    async def submit_human_decision(self, request_id: UUID, action: str) -> None:
        session, pending = await self.supervisor.find_pending(request_id)
        player = next(item for item in session.archive.config.players if item.side is pending.side)
        if player.agent_type is not AgentType.HUMAN:
            raise ValueError("decision request belongs to a Manual Web Chat controller")
        await session.manual_broker.submit_action(request_id, action)

    async def pause_match(self, match_id: UUID) -> None:
        await self.supervisor.pause_match(match_id)

    async def resume_match(self, match_id: UUID) -> MatchArchive:
        archive = await self.repository.get_match(match_id)
        if archive is None:
            raise KeyError(str(match_id))
        await self.supervisor.resume_match(match_id)
        updated = await self.repository.get_match(match_id)
        assert updated is not None
        return updated

    async def cancel_match(self, match_id: UUID) -> None:
        await self.supervisor.cancel_match(match_id)

    async def create_tournament(self, payload: CreateTournament) -> TournamentArchive:
        if payload.max_concurrent_matches > self.settings.max_concurrent_matches:
            payload = payload.model_copy(
                update={"max_concurrent_matches": self.settings.max_concurrent_matches}
            )
        for participant in payload.participants:
            player = PlayerConfig(
                side=Side.P1,
                display_name=participant.display_name,
                agent_type=participant.agent.agent_type,
                provider=participant.agent.provider,
                model=participant.agent.model,
                configuration=participant.agent.configuration,
                team_source=participant.agent.team_source,
                team_snapshot_id=participant.agent.team_snapshot_id,
            )
            if player.agent_type is AgentType.API:
                self._provider_for(player)
            template_format = payload.match_template.format
            descriptor = describe_format(template_format)
            if descriptor is not None and descriptor.custom_team_required:
                if player.team_snapshot_id is None:
                    raise ValueError(
                        f"participant {participant.display_name} requires a validated "
                        f"{descriptor.name} team"
                    )
                snapshot = await self.teams.get(player.team_snapshot_id)
                if snapshot is None or snapshot.format != template_format:
                    raise ValueError(
                        f"participant {participant.display_name} has no valid "
                        f"{descriptor.name} snapshot"
                    )
        return await self.tournaments.create(payload)

    async def start_tournament(self, tournament_id: UUID) -> TournamentArchive:
        archive = await self.tournaments.start(tournament_id)
        await self.schedule_tournaments(tournament_id)
        await self.hub.publish_overview(
            {"kind": "tournament_started", "tournament_id": str(tournament_id)}
        )
        return await self.tournaments.get(tournament_id) or archive

    async def pause_tournament(self, tournament_id: UUID) -> None:
        await self.tournaments.set_status(tournament_id, TournamentStatus.PAUSED)
        self.supervisor._wake.set()  # noqa: SLF001

    async def resume_tournament(self, tournament_id: UUID) -> None:
        await self.tournaments.set_status(tournament_id, TournamentStatus.RUNNING)
        await self.schedule_tournaments(tournament_id)
        self.supervisor._wake.set()  # noqa: SLF001

    async def cancel_tournament(self, tournament_id: UUID) -> None:
        await self.tournaments.set_status(tournament_id, TournamentStatus.CANCELLED)
        matches = await self.repository.list_matches(limit=250, tournament_id=tournament_id)
        for match in matches:
            if match.status not in {
                MatchStatus.COMPLETED,
                MatchStatus.CANCELLED,
                MatchStatus.FAILED,
                MatchStatus.INTERRUPTED,
            }:
                await self.cancel_match(match.id)

    async def schedule_tournaments(self, tournament_id: UUID | None = None) -> None:
        for series_id in await self.tournaments.ready_series(tournament_id):
            await self.schedule_series(series_id)

    async def schedule_series(self, series_id: UUID) -> MatchArchive:
        (
            tournament_id,
            template,
            participant_a,
            participant_b,
            game_number,
        ) = await self.tournaments.series_execution(series_id)
        if not await self.tournaments.budget_allows_start(tournament_id):
            raise ValueError("tournament cost limit reached")
        if template.engine != "pokemon-showdown":
            raise ValueError(f"engine {template.engine!r} is not installed")
        try:
            config = MatchConfig(
                name=(
                    f"{participant_a.display_name} vs {participant_b.display_name} - "
                    f"Game {game_number}"
                ),
                format=template.format,
                generation=template.generation,
                players=(
                    PlayerConfig(
                        side=Side.P1,
                        display_name=participant_a.display_name,
                        agent_type=participant_a.agent.agent_type,
                        provider=participant_a.agent.provider,
                        model=participant_a.agent.model,
                        configuration=participant_a.agent.configuration,
                        team_source=participant_a.agent.team_source,
                        team_snapshot_id=participant_a.agent.team_snapshot_id,
                    ),
                    PlayerConfig(
                        side=Side.P2,
                        display_name=participant_b.display_name,
                        agent_type=participant_b.agent.agent_type,
                        provider=participant_b.agent.provider,
                        model=participant_b.agent.model,
                        configuration=participant_b.agent.configuration,
                        team_source=participant_b.agent.team_source,
                        team_snapshot_id=participant_b.agent.team_snapshot_id,
                    ),
                ),
                random_seed=template.engine_configuration.get("random_seed"),
                fair_prompt_mode=template.fair_prompt_mode,
                prompt_profile=template.prompt_profile,
                context_profile=template.context_profile,
                memory_policy=template.memory_policy,
                banter_enabled=template.banter_enabled,
                team_policy=template.team_policy,
                limits=template.limits,
            )
            self._validate_provider_configuration(config)
            if not await self.tournaments.mark_series_queued(series_id):
                raise ValueError("series has already been claimed")
            return await self.create_match(
                config,
                tournament_id=tournament_id,
                series_id=series_id,
            )
        except ValueError as error:
            if str(error) == "series has already been claimed":
                raise
            await self.tournaments.set_status(tournament_id, TournamentStatus.FAILED)
            raise
        except Exception:
            await self.tournaments.set_status(tournament_id, TournamentStatus.FAILED)
            raise

    async def _eligible_for_start(self, summary: MatchSummary) -> bool:
        if summary.tournament_id is None:
            return True
        tournament = await self.tournaments.get(summary.tournament_id)
        if tournament is None or tournament.status is not TournamentStatus.RUNNING:
            return False
        if not await self.tournaments.budget_allows_start(summary.tournament_id):
            return False
        active_for_tournament = sum(
            1
            for session in self.supervisor.sessions.values()
            if session.archive.tournament_id == summary.tournament_id
        )
        return active_for_tournament < tournament.max_concurrent_matches

    async def _match_starting(self, summary: MatchSummary) -> None:
        if summary.series_id is not None:
            await self.tournaments.mark_series_running(summary.series_id)

    async def _match_terminal(self, match_id: UUID, archive: MatchArchive) -> None:
        if archive.challenge_run_id is not None and self._challenge_terminal_hook is not None:
            await self._challenge_terminal_hook(match_id, archive)
        if archive.tournament_id is None or archive.series_id is None:
            return
        _, _, participant_a, participant_b, _ = await self.tournaments.series_execution(
            archive.series_id
        )
        if archive.status is MatchStatus.COMPLETED:
            if archive.winner is Side.P1:
                result = GenericMatchResult(
                    status=GenericResultStatus.COMPLETED,
                    winner_participant_id=participant_a.id,
                    score_metadata={"turns": archive.turns},
                )
            elif archive.winner is Side.P2:
                result = GenericMatchResult(
                    status=GenericResultStatus.COMPLETED,
                    winner_participant_id=participant_b.id,
                    score_metadata={"turns": archive.turns},
                )
            else:
                result = GenericMatchResult(
                    status=GenericResultStatus.DRAW,
                    draw=True,
                    score_metadata={"turns": archive.turns},
                )
        elif archive.status is MatchStatus.CANCELLED:
            result = GenericMatchResult(
                status=GenericResultStatus.CANCELLED,
                reason=archive.error or "match cancelled",
            )
        else:
            result = GenericMatchResult(
                status=GenericResultStatus.FAILED,
                reason=archive.error or archive.status.value,
            )
        tournament_id = await self.tournaments.record_match_result(match_id, result)
        if tournament_id is not None:
            await self.schedule_tournaments(tournament_id)
            await self.hub.publish_overview(
                {"kind": "tournament_updated", "tournament_id": str(tournament_id)}
            )

    async def admin_overview(self) -> dict[str, object]:
        counts = await self.repository.match_counts()
        tournaments = await self.tournaments.list(limit=100)
        return {
            "active_matches": sum(
                counts.get(status, 0)
                for status in (
                    MatchStatus.STARTING,
                    MatchStatus.RUNNING,
                    MatchStatus.WAITING,
                    MatchStatus.PAUSED,
                )
            ),
            "queued_matches": counts.get(MatchStatus.QUEUED, 0),
            "concurrency_limit": self.settings.max_concurrent_matches,
            "active_tournaments": sum(
                item.status in {TournamentStatus.RUNNING, TournamentStatus.PAUSED}
                for item in tournaments
            ),
            "provider_failures": counts.get(MatchStatus.FAILED, 0),
            "showdown": await self._showdown_health(),
            "backend": {"status": "ok", "version": __version__},
        }

    async def _showdown_health(self) -> dict[str, object]:
        url = self.settings.showdown_websocket_url.replace("ws://", "http://").replace(
            "wss://", "https://"
        )
        url = url.split("/showdown/websocket", 1)[0]

        def probe() -> bool:
            try:
                with urlopen(url, timeout=1.5) as response:  # noqa: S310
                    return 200 <= int(response.status) < 500
            except (OSError, URLError):
                return False

        healthy = await asyncio.to_thread(probe)
        return {"status": "healthy" if healthy else "unavailable", "url": url}

    async def close(self) -> None:
        await self.supervisor.close()
