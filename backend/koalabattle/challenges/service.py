from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, ValidationError

from koalabattle.agents.providers import ProviderRequest
from koalabattle.agents.providers.base import safe_error_detail
from koalabattle.core.models import (
    MatchArchive,
    MatchConfig,
    MatchStatus,
    PlayerConfig,
    Side,
    TeamPolicy,
    TeamSource,
)
from koalabattle.service import BattleService

from .domain import deterministic_random_choice, generate_offer, minimum_completion_cost
from .models import (
    BattleControllerSnapshot,
    ChallengeDefinition,
    ChallengeRun,
    ChallengeRunStats,
    ChallengeRunView,
    ChallengeStage,
    ChallengeStageResult,
    ChallengeStatus,
    CreateChallengeRun,
    DraftCandidate,
    DraftControllerKind,
    DraftPick,
    EvSpread,
    PricingCatalogSnapshot,
    PricingStatus,
    PublicChallengeStage,
)
from .pricing import DraftPriceCatalog, DraftPriceStore, showdown_id
from .repository import ChallengeRepository
from .species import ShowdownSpeciesCatalog, SpeciesMetadata

CONTENT_ROOT = Path(__file__).with_name("content")


class _AgentDraftAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str


def _definition(definition_id: str) -> ChallengeDefinition:
    path = CONTENT_ROOT / f"{definition_id}.json"
    if not path.is_file():
        raise KeyError(definition_id)
    return ChallengeDefinition.model_validate_json(path.read_text(encoding="utf-8"))


def _public_stage(stage: ChallengeStage) -> PublicChallengeStage:
    return PublicChallengeStage.model_validate(
        {
            "id": stage.id,
            "name": stage.name,
            "title": stage.title,
            "theme": stage.theme,
            "level": stage.level,
        }
    )


def _ev_line(spread: EvSpread) -> str | None:
    names = (
        ("HP", spread.hp),
        ("Atk", spread.atk),
        ("Def", spread.defense),
        ("SpA", spread.spa),
        ("SpD", spread.spd),
        ("Spe", spread.spe),
    )
    values = [f"{value} {name}" for name, value in names if value]
    return f"EVs: {' / '.join(values)}" if values else None


def _team_scaffold(run: ChallengeRun) -> str | None:
    if len(run.picks) != run.definition.draft_rules.roster_size:
        return None
    blocks: list[str] = []
    for pick in run.picks:
        lines = [pick.candidate.species]
        ev_line = _ev_line(run.ev_allocations.get(pick.candidate.entry_id, EvSpread()))
        if ev_line:
            lines.append(ev_line)
        lines.extend(("Ability: [choose a legal ability]", "- [choose four legal moves]"))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _with_zero_ev_confirmation(team_export: str) -> str:
    """Add Showdown's stat-neutral marker without changing saved Training Camp EVs."""
    blocks = [block.strip() for block in team_export.strip().split("\n\n") if block.strip()]
    normalized: list[str] = []
    for block in blocks:
        lines = block.splitlines()
        ev_index = next(
            (index for index, line in enumerate(lines) if line.startswith("EVs:")), None
        )
        if ev_index is None:
            lines.insert(1, "EVs: 1 HP")
        else:
            values = re.findall(r"(\d+) (?:HP|Atk|Def|SpA|SpD|Spe)", lines[ev_index])
            if values and sum(int(value) for value in values) == 0:
                lines[ev_index] = "EVs: 1 HP"
        normalized.append("\n".join(lines))
    return "\n\n".join(normalized)


def _with_level(team_export: str, level: int) -> str:
    blocks = [block.strip() for block in team_export.strip().split("\n\n") if block.strip()]
    normalized: list[str] = []
    for block in blocks:
        lines = block.splitlines()
        level_indexes = [index for index, line in enumerate(lines) if line.startswith("Level:")]
        if level_indexes:
            lines[level_indexes[0]] = f"Level: {level}"
            for index in reversed(level_indexes[1:]):
                lines.pop(index)
        else:
            lines.insert(1, f"Level: {level}")
        if level < 100:
            ev_index = next(
                (index for index, line in enumerate(lines) if line.startswith("EVs:")), None
            )
            if ev_index is None:
                lines.insert(2, "EVs: 1 HP")
            else:
                parts = lines[ev_index].removeprefix("EVs:").strip().split(" / ")
                parsed = [re.fullmatch(r"(\d+) (HP|Atk|Def|SpA|SpD|Spe)", part) for part in parts]
                if all(match is not None for match in parsed) and all(
                    int(match.group(1)) % 4 == 0 for match in parsed if match is not None
                ):
                    changed = False
                    for index, match in enumerate(parsed):
                        assert match is not None
                        value = int(match.group(1))
                        if value < 252:
                            parts[index] = f"{value + 1} {match.group(2)}"
                            changed = True
                            break
                    if not changed:
                        used = {match.group(2) for match in parsed if match is not None}
                        stat = next(
                            item
                            for item in ("HP", "Atk", "Def", "SpA", "SpD", "Spe")
                            if item not in used
                        )
                        parts.append(f"1 {stat}")
                    lines[ev_index] = f"EVs: {' / '.join(parts)}"
        normalized.append("\n".join(lines))
    return "\n\n".join(normalized)


def redact_challenge_match(archive: MatchArchive) -> MatchArchive:
    if archive.challenge_run_id is None:
        return archive
    players = tuple(
        player.model_copy(
            update={"team_snapshot_id": None, "team_export": None, "team_packed": None}
        )
        if player.side is Side.P2
        else player
        for player in archive.config.players
    )
    return archive.model_copy(
        update={"config": archive.config.model_copy(update={"players": players})}
    )


class ChallengeService:
    def __init__(
        self,
        repository: ChallengeRepository,
        prices: DraftPriceStore,
        species: ShowdownSpeciesCatalog,
        battles: BattleService,
    ) -> None:
        self.repository = repository
        self.prices = prices
        self.species = species
        self.battles = battles

    async def pricing_status(self) -> PricingStatus:
        try:
            catalog = self.prices.load()
        except ValueError as error:
            return PricingStatus(
                available=True, ready=False, path=str(self.prices.path), errors=(str(error),)
            )
        if catalog is None:
            return PricingStatus(
                available=False,
                ready=False,
                path=str(self.prices.path),
                errors=("No normalized draft pricing catalog is installed.",),
            )
        source_verified, verification_detail = self.prices.verify_source(catalog)
        try:
            metadata = await self.species.entries()
        except RuntimeError as error:
            return PricingStatus(
                available=True,
                ready=False,
                path=str(self.prices.path),
                catalog_hash=catalog.catalog_hash,
                board_name=catalog.board_name,
                context=catalog.context,
                imported_at=catalog.imported_at,
                parsed_entries=catalog.parsed_entries,
                source_verified=source_verified,
                verification_detail=verification_detail,
                errors=(str(error),),
            )
        candidates, excluded = self._candidates(catalog, metadata)
        banned = sum(item.state == "banned" for item in catalog.entries)
        missing = sum(item.state == "missing" for item in catalog.entries)
        unsupported = sum(item["state"] not in {"banned", "missing"} for item in excluded)
        default_rules = _definition("kanto-gym-gauntlet").draft_rules
        cheapest_by_species: dict[str, int] = {}
        for candidate in candidates:
            cheapest_by_species[candidate.base_species_id] = min(
                cheapest_by_species.get(candidate.base_species_id, candidate.points),
                candidate.points,
            )
        enough_species = len(cheapest_by_species) >= default_rules.roster_size
        cheapest_default = sum(
            sorted(cheapest_by_species.values())[: default_rules.roster_size]
        )
        budget_ready = enough_species and cheapest_default <= default_rules.starting_credits
        ready = source_verified and enough_species and budget_ready
        readiness_errors: list[str] = []
        if not source_verified:
            readiness_errors.append(f"Pricing source verification failed. {verification_detail}")
        if not enough_species:
            readiness_errors.append(
                f"At least {default_rules.roster_size} Species-Clause-safe priced entries "
                "are required."
            )
        elif not budget_ready:
            readiness_errors.append(
                f"The cheapest legal roster costs {cheapest_default} Draft Credits, above the "
                f"default budget of {default_rules.starting_credits}."
            )
        return PricingStatus(
            available=True,
            ready=ready,
            path=str(self.prices.path),
            catalog_hash=catalog.catalog_hash,
            board_name=catalog.board_name,
            context=catalog.context,
            imported_at=catalog.imported_at,
            parsed_entries=catalog.parsed_entries,
            eligible_entries=len(metadata),
            priced_entries=len(candidates),
            banned_entries=banned,
            missing_entries=missing,
            unsupported_entries=unsupported,
            source_verified=source_verified,
            verification_detail=verification_detail,
            excluded_entries=tuple(excluded),
            errors=tuple(readiness_errors),
        )

    @staticmethod
    def _candidates(
        catalog: DraftPriceCatalog, metadata: tuple[SpeciesMetadata, ...]
    ) -> tuple[tuple[DraftCandidate, ...], list[dict[str, str]]]:
        by_id = {entry.id: entry for entry in metadata}
        candidates: list[DraftCandidate] = []
        excluded: list[dict[str, str]] = []
        for price in catalog.entries:
            species = by_id.get(price.entry_id)
            if price.state != "priced" or price.points is None:
                excluded.append(
                    {
                        "species": price.species,
                        "state": price.state,
                        "reason": price.reason or price.state,
                    }
                )
                continue
            if species is None:
                excluded.append(
                    {
                        "species": price.species,
                        "state": "unsupported form",
                        "reason": "no exact pinned Showdown species match",
                    }
                )
                continue
            if (
                species.battle_only
                or species.cosmetic
                or species.unavailable
                or species.is_mega
                or species.is_gmax
            ):
                excluded.append(
                    {
                        "species": price.species,
                        "state": "unavailable",
                        "reason": "temporary or special-mechanic form excluded in V1",
                    }
                )
                continue
            candidates.append(
                DraftCandidate(
                    entry_id=price.entry_id,
                    species=species.name,
                    showdown_id=species.id,
                    base_species_id=species.base_species_id,
                    national_dex_number=species.national_dex_number,
                    introduction_generation=species.introduction_generation,
                    types=species.types,
                    base_stat_total=species.base_stat_total,
                    points=price.points,
                )
            )
        return tuple(sorted(candidates, key=lambda item: item.entry_id)), excluded

    async def create(self, payload: CreateChallengeRun) -> ChallengeRunView:
        catalog = self.prices.load()
        if catalog is None:
            raise ValueError("draft pricing is unavailable; import a local board first")
        source_verified, verification_detail = self.prices.verify_source(catalog)
        if not source_verified:
            raise ValueError(f"draft pricing verification failed: {verification_detail}")
        if payload.expected_catalog_hash and payload.expected_catalog_hash != catalog.catalog_hash:
            raise ValueError("pricing catalog changed; refresh setup before creating the run")
        metadata = await self.species.entries()
        candidates, _ = self._candidates(catalog, metadata)
        definition = _definition(payload.definition_id)
        if payload.draft_rules is not None:
            definition = definition.model_copy(update={"draft_rules": payload.draft_rules})
        if payload.training_rules is not None:
            definition = definition.model_copy(update={"training_rules": payload.training_rules})
        if len(candidates) < definition.draft_rules.roster_size:
            raise ValueError("pricing coverage cannot fill the configured roster")
        now = datetime.now(UTC)
        run = ChallengeRun(
            id=uuid4(),
            name=payload.name,
            definition=definition,
            status=ChallengeStatus.DRAFTING,
            seed=payload.seed,
            pricing=PricingCatalogSnapshot(
                schema_version=catalog.schema_version,
                parser_version=catalog.parser_version,
                board_name=catalog.board_name,
                context=catalog.context,
                imported_at=catalog.imported_at,
                source_sha256=catalog.source_sha256,
                catalog_hash=catalog.catalog_hash,
                parsed_entries=catalog.parsed_entries,
                mechanics_assumptions=catalog.mechanics_assumptions,
                candidates=candidates,
            ),
            draft_controller=payload.draft_controller,
            battle_controller=payload.battle_controller,
            opponent_controller=payload.opponent_controller,
            credits_remaining=definition.draft_rules.starting_credits,
            rerolls_remaining=definition.draft_rules.rerolls,
            created_at=now,
            updated_at=now,
        )
        required_credits = minimum_completion_cost(run)
        if required_credits > run.credits_remaining:
            raise ValueError(
                f"the cheapest legal {definition.draft_rules.roster_size}-Pokemon roster costs "
                f"{required_credits} Draft Credits; increase the budget or import broader coverage"
            )
        run = run.model_copy(update={"current_offer": generate_offer(run)})
        await self.repository.create(run)
        if run.draft_controller.kind is DraftControllerKind.RANDOM:
            while run.status is ChallengeStatus.DRAFTING:
                offer = run.current_offer
                assert offer is not None
                run = await self.pick(
                    run.id,
                    deterministic_random_choice(run).entry_id,
                    offer.fingerprint,
                    run.revision,
                    selected_by=DraftControllerKind.RANDOM,
                )
        return self.view(run)

    async def reconcile(self) -> tuple[UUID, ...]:
        reconciled: list[UUID] = []
        offset = 0
        while summaries := await self.repository.list(limit=250, offset=offset):
            for summary in summaries:
                run = await self.repository.get(summary.id)
                if run is None or run.active_match_id is None:
                    continue
                refreshed = await self._refresh_active(run)
                if refreshed.revision != run.revision:
                    reconciled.append(run.id)
            offset += len(summaries)
        return tuple(reconciled)

    async def _refresh_active(self, run: ChallengeRun) -> ChallengeRun:
        if run.active_match_id is None:
            return run
        match = await self.battles.repository.get_match(run.active_match_id)
        if match is None:
            async with self.repository.lock(run.id):
                current = await self.require(run.id)
                if current.active_match_id != run.active_match_id:
                    return current
                return await self.repository.save(
                    current.model_copy(
                        update={
                            "status": ChallengeStatus.STAGE_RESULT,
                            "active_match_id": None,
                            "error": "linked match is missing after restart",
                        }
                    ),
                    expected_revision=current.revision,
                )
        if match.status in {
            MatchStatus.COMPLETED,
            MatchStatus.FAILED,
            MatchStatus.CANCELLED,
            MatchStatus.INTERRUPTED,
        }:
            await self.on_match_terminal(match.id, match)
            return await self.require(run.id)
        target = (
            ChallengeStatus.BATTLING
            if match.status
            in {
                MatchStatus.STARTING,
                MatchStatus.RUNNING,
                MatchStatus.WAITING,
                MatchStatus.PAUSED,
            }
            else ChallengeStatus.BATTLE_QUEUED
        )
        if run.status is target:
            return run
        async with self.repository.lock(run.id):
            current = await self.require(run.id)
            if current.active_match_id != match.id or current.status is target:
                return current
            return await self.repository.save(
                current.model_copy(update={"status": target}),
                expected_revision=current.revision,
            )

    async def require(self, run_id: UUID) -> ChallengeRun:
        run = await self.repository.get(run_id)
        if run is None:
            raise KeyError(str(run_id))
        return run

    async def get(self, run_id: UUID) -> ChallengeRunView:
        run = await self.require(run_id)
        return self.view(await self._refresh_active(run))

    def view(self, run: ChallengeRun) -> ChallengeRunView:
        stages = tuple(_public_stage(stage) for stage in run.definition.stages)
        current = stages[run.current_stage_index] if run.current_stage_index < len(stages) else None
        wins = sum(item.status == "won" for item in run.stage_results)
        losses = sum(item.status == "lost" for item in run.stage_results)
        draws = sum(item.status == "draw" for item in run.stage_results)
        technical_failures = sum(
            item.status in {"failed", "cancelled", "interrupted"}
            for item in run.stage_results
        )
        latency_results = [
            item
            for item in run.stage_results
            if item.average_decision_latency_ms is not None and item.decision_count
        ]
        latency_decisions = sum(item.decision_count for item in latency_results)
        average_latency = (
            sum(
                (item.average_decision_latency_ms or 0) * item.decision_count
                for item in latency_results
            )
            / latency_decisions
            if latency_decisions
            else None
        )
        visible_candidates = {
            pick.candidate.entry_id: pick.candidate for pick in run.picks
        }
        if run.current_offer is not None:
            visible_candidates.update(
                (candidate.entry_id, candidate) for candidate in run.current_offer.options
            )
        return ChallengeRunView(
            run=run.model_copy(
                update={
                    "pricing": run.pricing.model_copy(
                        update={"candidates": tuple(visible_candidates.values())}
                    ),
                    "definition": run.definition.model_copy(
                        update={
                            "stages": tuple(
                                stage.model_copy(update={"opponent_team": "[private stage team]"})
                                for stage in run.definition.stages
                            )
                        }
                    )
                }
            ),
            stages=stages,
            current_stage=current,
            team_export_scaffold=_team_scaffold(run),
            minimum_completion_cost=minimum_completion_cost(run),
            statistics=ChallengeRunStats(
                stages_cleared=wins,
                wins=wins,
                losses=losses,
                draws=draws,
                total_battles=len(run.stage_results),
                technical_failures=technical_failures,
                total_turns=sum(item.turns for item in run.stage_results),
                duration_seconds=sum(item.duration_seconds for item in run.stage_results),
                estimated_cost=sum(item.estimated_cost for item in run.stage_results),
                average_decision_latency_ms=average_latency,
                credits_spent=run.definition.draft_rules.starting_credits - run.credits_remaining,
                credits_remaining=run.credits_remaining,
                rerolls_used=run.definition.draft_rules.rerolls - run.rerolls_remaining,
                ev_used=sum(spread.total for spread in run.ev_allocations.values()),
            ),
        )

    async def pick(
        self,
        run_id: UUID,
        entry_id: str,
        fingerprint: str,
        expected_revision: int,
        *,
        selected_by: DraftControllerKind | None = None,
    ) -> ChallengeRun:
        async with self.repository.lock(run_id):
            run = await self.require(run_id)
            if run.revision != expected_revision:
                raise ValueError(f"stale challenge revision: current {run.revision}")
            if run.status is not ChallengeStatus.DRAFTING or run.current_offer is None:
                raise ValueError("challenge is not waiting for a draft pick")
            if run.current_offer.fingerprint != fingerprint:
                raise ValueError("draft offer is stale")
            candidate = next(
                (item for item in run.current_offer.options if item.entry_id == entry_id), None
            )
            if candidate is None:
                raise ValueError("entry is not one of the persisted legal choices")
            controller = selected_by or run.draft_controller.kind
            if controller is not run.draft_controller.kind:
                raise ValueError("draft controller changed while this decision was in progress")
            if selected_by is None and controller is not DraftControllerKind.HUMAN:
                raise ValueError("this draft is controlled by an agent or deterministic random")
            picks = (
                *run.picks,
                DraftPick(
                    round=len(run.picks) + 1,
                    offer_fingerprint=fingerprint,
                    candidate=candidate,
                    selected_by=controller,
                ),
            )
            complete = len(picks) == run.definition.draft_rules.roster_size
            updated = run.model_copy(
                update={
                    "picks": picks,
                    "credits_remaining": run.credits_remaining - candidate.points,
                    "status": ChallengeStatus.TRAINING if complete else ChallengeStatus.DRAFTING,
                    "current_offer": None,
                    "offer_nonce": 0,
                }
            )
            if not complete:
                updated = updated.model_copy(update={"current_offer": generate_offer(updated)})
            return await self.repository.save(updated, expected_revision=run.revision)

    async def reroll(
        self,
        run_id: UUID,
        fingerprint: str,
        expected_revision: int,
        *,
        selected_by: DraftControllerKind | None = None,
    ) -> ChallengeRun:
        async with self.repository.lock(run_id):
            run = await self.require(run_id)
            if run.revision != expected_revision:
                raise ValueError(f"stale challenge revision: current {run.revision}")
            if run.status is not ChallengeStatus.DRAFTING or run.current_offer is None:
                raise ValueError("challenge is not waiting for a draft action")
            if selected_by is None and run.draft_controller.kind is not DraftControllerKind.HUMAN:
                raise ValueError("only a human draft controller can request a reroll directly")
            if selected_by is not None and selected_by is not run.draft_controller.kind:
                raise ValueError("draft controller changed while this decision was in progress")
            if run.current_offer.fingerprint != fingerprint:
                raise ValueError("draft offer is stale")
            if run.rerolls_remaining <= 0:
                raise ValueError("no rerolls remain")
            nonce = run.offer_nonce + 1
            updated = run.model_copy(
                update={
                    "rerolls_remaining": run.rerolls_remaining - 1,
                    "offer_nonce": nonce,
                    "current_offer": None,
                }
            )
            updated = updated.model_copy(
                update={"current_offer": generate_offer(updated, nonce=nonce)}
            )
            return await self.repository.save(updated, expected_revision=run.revision)

    async def agent_action(self, run_id: UUID, expected_revision: int) -> ChallengeRun:
        run = await self.require(run_id)
        if run.revision != expected_revision:
            raise ValueError(f"stale challenge revision: current {run.revision}")
        if run.draft_controller.kind is not DraftControllerKind.AGENT or run.current_offer is None:
            raise ValueError("run is not waiting for an agent draft action")
        provider = self.battles.provider_for_draft(run.draft_controller)
        legal = [f"pick:{item.entry_id}" for item in run.current_offer.options]
        if run.rerolls_remaining:
            legal.append("reroll")
        prompt = json.dumps(
            {
                "task": "Select exactly one legal draft action. Return JSON only; no reasoning.",
                "challenge_rules": {
                    "format": run.definition.format,
                    "draft": run.definition.draft_rules.model_dump(mode="json"),
                    "training": run.definition.training_rules.model_dump(mode="json"),
                },
                "remaining_credits": run.credits_remaining,
                "remaining_slots": run.definition.draft_rules.roster_size - len(run.picks),
                "rerolls_remaining": run.rerolls_remaining,
                "previous_picks": [pick.candidate.model_dump(mode="json") for pick in run.picks],
                "offer": run.current_offer.model_dump(mode="json"),
                "legal_actions": legal,
                "response_schema": {"action": "one exact legal action"},
            },
            indent=2,
        )
        request = ProviderRequest(
            prompt=prompt,
            system_prompt=(
                "You are a Pokemon draft controller. Return one strict JSON object "
                "and no hidden reasoning."
            ),
            model=run.draft_controller.model or "",
            timeout_seconds=run.draft_controller.configuration.timeout_seconds,
            max_output_tokens=min(run.draft_controller.configuration.max_output_tokens, 256),
            temperature=run.draft_controller.configuration.temperature,
            reasoning_effort=run.draft_controller.configuration.reasoning_effort,
            output_schema_name="koalabattle_draft_action",
            output_schema={
                "type": "object",
                "properties": {"action": {"type": "string", "enum": legal}},
                "required": ["action"],
                "additionalProperties": False,
            },
        )
        last_error = "invalid agent response"
        for _ in range(run.draft_controller.configuration.max_retries + 1):
            try:
                async with asyncio.timeout(request.timeout_seconds):
                    response = await provider.generate(request)
            except TimeoutError:
                last_error = "agent draft provider timed out"
                continue
            except Exception as error:
                last_error = f"agent draft provider failed: {safe_error_detail(error)}"
                continue
            try:
                parsed = _AgentDraftAction.model_validate_json(response.text)
            except ValidationError as error:
                last_error = f"agent draft response is invalid: {error}"
                continue
            if parsed.action not in legal:
                last_error = "agent selected an action that is no longer legal"
                continue
            if parsed.action == "reroll":
                return await self.reroll(
                    run.id,
                    run.current_offer.fingerprint,
                    run.revision,
                    selected_by=DraftControllerKind.AGENT,
                )
            return await self.pick(
                run.id,
                parsed.action.removeprefix("pick:"),
                run.current_offer.fingerprint,
                run.revision,
                selected_by=DraftControllerKind.AGENT,
            )
        raise ValueError(last_error)

    async def take_over_draft(self, run_id: UUID, expected_revision: int) -> ChallengeRun:
        async with self.repository.lock(run_id):
            run = await self.require(run_id)
            if run.revision != expected_revision:
                raise ValueError(f"stale challenge revision: current {run.revision}")
            if run.status is not ChallengeStatus.DRAFTING or run.current_offer is None:
                raise ValueError("challenge is not waiting for a draft decision")
            if run.draft_controller.kind is not DraftControllerKind.AGENT:
                raise ValueError("only an Agent draft can be taken over manually")
            updated = run.model_copy(
                update={
                    "draft_controller_history": (
                        *run.draft_controller_history,
                        run.draft_controller,
                    ),
                    "draft_controller": run.draft_controller.model_copy(
                        update={"kind": DraftControllerKind.HUMAN, "provider": None, "model": None}
                    ),
                    "error": None,
                }
            )
            return await self.repository.save(updated, expected_revision=run.revision)

    async def save_training(
        self, run_id: UUID, allocations: dict[str, EvSpread], expected_revision: int
    ) -> ChallengeRun:
        async with self.repository.lock(run_id):
            run = await self.require(run_id)
            if run.revision != expected_revision:
                raise ValueError(f"stale challenge revision: current {run.revision}")
            if run.status not in {ChallengeStatus.TRAINING, ChallengeStatus.TEAM_REVIEW}:
                raise ValueError("challenge is not in Training Camp")
            expected = {pick.candidate.entry_id for pick in run.picks}
            if set(allocations) != expected:
                raise ValueError("EV allocations must contain every drafted entry exactly once")
            rules = run.definition.training_rules
            for entry_id, spread in allocations.items():
                if spread.total > rules.per_pokemon_max:
                    raise ValueError(f"{entry_id} exceeds the per-Pokemon EV limit")
                if any(
                    value > rules.per_stat_max
                    for value in spread.model_dump(by_alias=True).values()
                ):
                    raise ValueError(f"{entry_id} exceeds the per-stat EV limit")
            if sum(spread.total for spread in allocations.values()) > rules.global_ev_budget:
                raise ValueError("global EV budget exceeded")
            updated = run.model_copy(
                update={
                    "ev_allocations": allocations,
                    "status": ChallengeStatus.TEAM_REVIEW,
                }
            )
            return await self.repository.save(updated, expected_revision=run.revision)

    async def finalize_team(
        self, run_id: UUID, team_text: str, expected_revision: int
    ) -> ChallengeRun:
        async with self.repository.lock(run_id):
            run = await self.require(run_id)
            if run.revision != expected_revision:
                raise ValueError(f"stale challenge revision: current {run.revision}")
            if run.status is not ChallengeStatus.TEAM_REVIEW:
                raise ValueError("challenge is not waiting for team finalization")
            validation = await self.battles.team_validator.validate(
                _with_zero_ev_confirmation(team_text), run.definition.format
            )
            if not validation.valid:
                raise ValueError("Showdown rejected the team: " + "; ".join(validation.errors))
            actual = validation.structured_team
            expected = {pick.candidate.showdown_id: pick.candidate.entry_id for pick in run.picks}
            if len(actual) != len(expected):
                raise ValueError("final team must contain every drafted Pokemon exactly once")
            seen: set[str] = set()
            for pokemon in actual:
                species_id = showdown_id(str(pokemon.get("species") or pokemon.get("name") or ""))
                entry_id = expected.get(species_id)
                if entry_id is None or entry_id in seen:
                    raise ValueError(
                        "final team species/forms do not exactly match the drafted roster"
                    )
                seen.add(entry_id)
                raw_evs = pokemon.get("evs") if isinstance(pokemon.get("evs"), dict) else {}
                actual_evs = EvSpread.model_validate(raw_evs)
                expected_evs = run.ev_allocations[entry_id]
                zero_ev_confirmation = expected_evs.total == 0 and actual_evs == EvSpread(hp=1)
                if actual_evs != expected_evs and not zero_ev_confirmation:
                    raise ValueError(f"final team EVs for {species_id} do not match Training Camp")
            snapshot = await self.battles.teams.create_snapshot(
                name=f"{run.name} · source roster",
                source=TeamSource.IMPORTED,
                submitted_text=team_text,
                validation=validation,
            )
            updated = run.model_copy(
                update={"team_snapshot_id": snapshot.id, "status": ChallengeStatus.READY}
            )
            return await self.repository.save(updated, expected_revision=run.revision)

    @staticmethod
    def _player(
        controller: BattleControllerSnapshot, side: Side, name: str, snapshot_id: UUID
    ) -> PlayerConfig:
        return PlayerConfig(
            side=side,
            display_name=name,
            agent_type=controller.agent_type,
            provider=controller.provider.value if controller.provider else None,
            model=controller.model,
            configuration=controller.configuration,
            team_source=TeamSource.PRESET,
            team_snapshot_id=snapshot_id,
        )

    async def launch_stage(
        self, run_id: UUID, expected_revision: int
    ) -> tuple[ChallengeRun, MatchArchive]:
        async with self.repository.lock(run_id):
            run = await self.require(run_id)
            if run.revision != expected_revision:
                raise ValueError(f"stale challenge revision: current {run.revision}")
            if run.status not in {ChallengeStatus.READY, ChallengeStatus.STAGE_RESULT}:
                raise ValueError("challenge is not ready to launch a stage")
            if run.team_snapshot_id is None or run.current_stage_index >= len(
                run.definition.stages
            ):
                raise ValueError("challenge has no launchable stage")
            source = await self.battles.teams.get(run.team_snapshot_id)
            if source is None:
                raise ValueError("finalized source team snapshot is missing")
            stage = run.definition.stages[run.current_stage_index]
            player_validation = await self.battles.team_validator.validate(
                _with_level(source.normalized_export, stage.level), run.definition.format
            )
            opponent_validation = await self.battles.team_validator.validate(
                _with_level(stage.opponent_team, stage.level), run.definition.format
            )
            if not player_validation.valid:
                raise ValueError(
                    "derived player stage team is invalid: " + "; ".join(player_validation.errors)
                )
            if not opponent_validation.valid:
                raise ValueError(
                    "campaign stage team is invalid: " + "; ".join(opponent_validation.errors)
                )
            player_snapshot = await self.battles.teams.create_snapshot(
                name=f"{run.name} · {stage.name} · level {stage.level}",
                source=TeamSource.PRESET,
                submitted_text=player_validation.normalized_export or "",
                validation=player_validation,
            )
            opponent_snapshot = await self.battles.teams.create_snapshot(
                name=f"{run.definition.name} · {stage.name} · level {stage.level}",
                source=TeamSource.PRESET,
                submitted_text=opponent_validation.normalized_export or "",
                validation=opponent_validation,
            )
            config = MatchConfig(
                name=f"{run.name} · {stage.title} {stage.name}",
                format=run.definition.format,
                players=(
                    self._player(run.battle_controller, Side.P1, run.name, player_snapshot.id),
                    self._player(
                        run.opponent_controller, Side.P2, stage.name, opponent_snapshot.id
                    ),
                ),
                random_seed=run.seed + run.current_stage_index,
                team_policy=TeamPolicy.FIXED,
                allow_terastallization=False,
            )
            match = await self.battles.create_match(
                config,
                challenge_run_id=run.id,
                challenge_stage_id=stage.id,
            )
            updated = run.model_copy(
                update={
                    "status": ChallengeStatus.BATTLE_QUEUED,
                    "active_match_id": match.id,
                    "error": None,
                }
            )
            stored = await self.repository.save(updated, expected_revision=run.revision)
            return stored, match

    async def on_match_terminal(self, match_id: UUID, archive: MatchArchive) -> None:
        if archive.challenge_run_id is None:
            return
        async with self.repository.lock(archive.challenge_run_id):
            run = await self.require(archive.challenge_run_id)
            if run.active_match_id != match_id:
                return
            stage_index = run.current_stage_index
            stage = run.definition.stages[stage_index]
            outcome: Literal["won", "lost", "draw", "failed", "cancelled", "interrupted"]
            if archive.status is MatchStatus.COMPLETED:
                outcome = (
                    "won"
                    if archive.winner is Side.P1
                    else "lost"
                    if archive.winner is Side.P2
                    else "draw"
                )
            elif archive.status is MatchStatus.CANCELLED:
                outcome = "cancelled"
            elif archive.status is MatchStatus.INTERRUPTED:
                outcome = "interrupted"
            else:
                outcome = "failed"
            result = ChallengeStageResult(
                stage_id=stage.id,
                stage_index=stage_index,
                match_id=match_id,
                status=outcome,
                winner=archive.winner.value if archive.winner else None,
                turns=archive.turns,
                duration_seconds=max(
                    0, (archive.updated_at - archive.created_at).total_seconds()
                ),
                estimated_cost=sum(
                    record.decision.estimated_cost.amount or 0 for record in archive.decisions
                ),
                average_decision_latency_ms=(
                    sum(latencies) / len(latencies)
                    if (
                        latencies := [
                            record.decision.latency_ms
                            for record in archive.decisions
                            if record.decision.latency_ms is not None
                        ]
                    )
                    else None
                ),
                decision_count=len(archive.decisions),
                started_at=archive.created_at,
                completed_at=archive.updated_at,
            )
            won = outcome == "won"
            next_index = stage_index + 1 if won else stage_index
            completed = won and next_index == len(run.definition.stages)
            updated = run.model_copy(
                update={
                    "status": ChallengeStatus.COMPLETED
                    if completed
                    else ChallengeStatus.STAGE_RESULT,
                    "current_stage_index": next_index,
                    "active_match_id": None,
                    "stage_results": (*run.stage_results, result),
                    "completed_at": datetime.now(UTC) if completed else None,
                    "error": archive.error if outcome in {"failed", "interrupted"} else None,
                }
            )
            await self.repository.save(updated, expected_revision=run.revision)

    async def cancel(self, run_id: UUID, expected_revision: int) -> ChallengeRun:
        active_match_id: UUID | None
        async with self.repository.lock(run_id):
            run = await self.require(run_id)
            if run.revision != expected_revision:
                raise ValueError(f"stale challenge revision: current {run.revision}")
            if run.status in {ChallengeStatus.COMPLETED, ChallengeStatus.CANCELLED}:
                raise ValueError(f"challenge is already {run.status.value}")
            active_match_id = run.active_match_id
            updated = run.model_copy(
                update={"status": ChallengeStatus.CANCELLED, "active_match_id": None}
            )
            stored = await self.repository.save(updated, expected_revision=run.revision)
        if active_match_id is not None:
            await self.battles.cancel_match(active_match_id)
        return stored
