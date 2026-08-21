from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, ValidationError

from koalabattle.agents.providers import ProviderRequest
from koalabattle.agents.providers.base import safe_error_detail
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
from koalabattle.service import BattleService

from .domain import (
    attach_offer,
    can_generate_offer,
    deterministic_random_choice,
    unseen_identity_count,
)
from .models import (
    DRAFT_RULES_VERSION,
    BattleControllerSnapshot,
    ChallengeBattleSummary,
    ChallengeDefinition,
    ChallengeDifficulty,
    ChallengeRun,
    ChallengeRunStats,
    ChallengeRunView,
    ChallengeStage,
    ChallengeStageResult,
    ChallengeStatus,
    CreateChallengeRun,
    DraftCandidate,
    DraftControllerKind,
    DraftHistoryEntry,
    DraftPick,
    DraftPoolSnapshot,
    EvSpread,
    PublicChallengeStage,
    player_stage_level,
)
from .repository import ChallengeRepository
from .species import ShowdownSpeciesCatalog, SpeciesMetadata, showdown_id

CONTENT_ROOT = Path(__file__).with_name("content")
AUTO_ADVANCE_DELAYS = {"quick-sim": 3.0, "fast-watch": 4.5, "normal": 3.0}


def _event_pokemon(value: object) -> tuple[str, str] | None:
    if not isinstance(value, str):
        return None
    match = re.match(r"^(p[12])[a-z]?:\s*(.+)$", value)
    if match is None:
        return None
    return match.group(1), match.group(2).strip()


def derive_battle_summary(archive: MatchArchive) -> ChallengeBattleSummary:
    """Derive post-battle participation from immutable Showdown events."""
    aliases: dict[tuple[str, str], str] = {}
    participants: dict[str, list[str]] = {"p1": [], "p2": []}
    fainted: dict[str, list[str]] = {"p1": [], "p2": []}

    def append_unique(items: list[str], value: str) -> None:
        if value not in items:
            items.append(value)

    for event in archive.events:
        if event.event_type == "pokemon_switched":
            actor = _event_pokemon(event.payload.get("actor"))
            if actor is None:
                continue
            side, nickname = actor
            details = event.payload.get("details")
            species = (
                str(details).split(",", 1)[0].strip()
                if isinstance(details, str) and details.strip()
                else nickname
            )
            aliases[(side, nickname)] = species
            append_unique(participants[side], species)
        elif event.event_type == "pokemon_fainted":
            target = _event_pokemon(event.payload.get("target"))
            if target is None:
                continue
            side, nickname = target
            append_unique(fainted[side], aliases.get((side, nickname), nickname))
    return ChallengeBattleSummary(
        match_id=archive.id,
        player_participants=tuple(participants["p1"]),
        opponent_participants=tuple(participants["p2"]),
        player_fainted=tuple(fainted["p1"]),
        opponent_fainted=tuple(fainted["p2"]),
    )


class _AgentDraftAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str


def _definition(definition_id: str) -> ChallengeDefinition:
    path = CONTENT_ROOT / f"{definition_id}.json"
    if not path.is_file():
        raise KeyError(definition_id)
    return ChallengeDefinition.model_validate_json(path.read_text(encoding="utf-8"))


def _public_stage(stage: ChallengeStage, difficulty: ChallengeDifficulty) -> PublicChallengeStage:
    return PublicChallengeStage.model_validate(
        {
            "id": stage.id,
            "name": stage.name,
            "title": stage.title,
            "theme": stage.theme,
            "level": stage.level,
            "player_level": player_stage_level(stage.level, difficulty),
            "specialty": stage.specialty,
            "trainer_asset_id": stage.trainer_asset_id,
            "visual_accent": stage.visual_accent,
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


def _recommended_ev_spread(candidate: DraftCandidate) -> EvSpread:
    """Return the same deterministic first-choice preset shown by Training Camp."""
    stats = candidate.base_stats
    if stats is None:
        return EvSpread(atk=252, spd=4, spe=252)
    physical = stats.atk >= stats.spa
    offense = stats.atk if physical else stats.spa
    defensive = max(stats.defense, stats.spd)
    if defensive > offense + 10:
        if stats.defense >= stats.spd:
            return EvSpread.model_validate({"hp": 252, "def": 252, "spd": 4})
        return EvSpread.model_validate({"hp": 252, "def": 4, "spd": 252})
    is_fast = stats.spe >= 90 or stats.spe >= defensive
    if physical:
        return EvSpread(atk=252, spd=4, spe=252) if is_fast else EvSpread(hp=252, atk=252, spd=4)
    return EvSpread(spa=252, spd=4, spe=252) if is_fast else EvSpread(hp=252, spa=252, spd=4)


def _recommended_role(candidate: DraftCandidate) -> tuple[str, str]:
    """Deterministic nature + held item matching the auto-applied EV preset.

    Opponent stages ship complete competitive sets, so the automatically prepared
    player team gets the same class of set instead of an itemless neutral one. The
    drafted species, abilities, and EVs are untouched; both remain editable in
    Advanced team setup before the roster is locked.
    """
    stats = candidate.base_stats
    if stats is None:
        return "Adamant", "Life Orb"
    physical = stats.atk >= stats.spa
    offense = stats.atk if physical else stats.spa
    defensive = max(stats.defense, stats.spd)
    if defensive > offense + 10:
        return ("Bold" if stats.defense >= stats.spd else "Calm"), "Leftovers"
    is_fast = stats.spe >= 90 or stats.spe >= defensive
    if is_fast:
        return ("Jolly" if physical else "Timid"), "Life Orb"
    return ("Adamant" if physical else "Modest"), "Leftovers"


def _team_scaffold(run: ChallengeRun) -> str | None:
    if len(run.picks) != run.definition.draft_rules.roster_size:
        return None
    blocks: list[str] = []
    for pick in run.picks:
        nature, item = _recommended_role(pick.candidate)
        heading = f"{pick.candidate.species} @ {pick.candidate.required_item or item}"
        lines = [heading]
        ev_line = _ev_line(run.ev_allocations.get(pick.candidate.entry_id, EvSpread()))
        if ev_line:
            lines.append(ev_line)
        lines.append(f"{nature} Nature")
        selected = run.ability_selections.get(pick.candidate.entry_id)
        ability = next((item for item in pick.candidate.abilities if item.id == selected), None)
        if ability is not None:
            lines.append(f"Ability: {ability.name}")
        lines.extend(f"- {move}" for move in (pick.candidate.recommended_moves or ("Tackle",)))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _apply_selected_abilities(team_export: str, run: ChallengeRun) -> str:
    """Apply persisted format-aware selections before authoritative validation."""
    candidates = {
        candidate.showdown_id: candidate for candidate in (p.candidate for p in run.picks)
    }
    normalized: list[str] = []
    for block in (item.strip() for item in team_export.strip().split("\n\n") if item.strip()):
        lines = block.splitlines()
        heading = lines[0].split("@", 1)[0].strip()
        species_match = re.search(r"\(([^()]+)\)\s*$", heading)
        species_id = showdown_id(species_match.group(1) if species_match else heading)
        candidate = candidates.get(species_id)
        lines = [line for line in lines if not line.startswith("Ability:")]
        if candidate is not None and run.draft_pool.abilities_supported:
            selected = run.ability_selections.get(candidate.entry_id)
            ability = next((item for item in candidate.abilities if item.id == selected), None)
            if ability is None:
                raise ValueError(f"select a legal ability for {candidate.species}")
            lines.insert(1, f"Ability: {ability.name}")
        normalized.append("\n".join(lines))
    return "\n\n".join(normalized)


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
        ev_index = next(
            (index for index, line in enumerate(lines) if line.startswith("EVs:")), None
        )
        if ev_index is None:
            lines.insert(2, "EVs: 1 HP")
        elif level < 100:
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


def _with_unique_duplicate_nicknames(team_export: str) -> str:
    """Give duplicate species distinct Showdown identities without changing the roster."""
    blocks = [block.strip() for block in team_export.strip().split("\n\n") if block.strip()]
    species = [block.splitlines()[0].split(" @", 1)[0] for block in blocks]
    totals = {name: species.count(name) for name in set(species)}
    seen: dict[str, int] = {}
    normalized: list[str] = []
    for block, name in zip(blocks, species, strict=True):
        first_line = block.splitlines()[0]
        if totals[name] == 1 or " (" in first_line:
            normalized.append(block)
            continue
        seen[name] = seen.get(name, 0) + 1
        lines = block.splitlines()
        lines[0] = f"{name} {seen[name]} ({name}){first_line[len(name):]}"
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
        species: ShowdownSpeciesCatalog,
        battles: BattleService,
    ) -> None:
        self.repository = repository
        self.species = species
        self.battles = battles
        self._auto_tasks: dict[UUID, asyncio.Task[None]] = {}

    @staticmethod
    def auto_run_available(run: ChallengeRun) -> bool:
        interactive = {AgentType.HUMAN, AgentType.MANUAL}
        return (
            run.battle_controller.agent_type not in interactive
            and run.opponent_controller.agent_type not in interactive
        )

    def _schedule_auto_run(self, run: ChallengeRun) -> None:
        if (
            not self.auto_run_available(run)
            or run.auto_run_paused
            or run.auto_advance_at is None
            or run.status not in {ChallengeStatus.READY, ChallengeStatus.STAGE_RESULT}
            or run.id in self._auto_tasks
        ):
            return
        task = asyncio.create_task(
            self._wait_and_auto_advance(run.id), name=f"challenge-auto-run-{run.id}"
        )
        self._auto_tasks[run.id] = task

        def forget(completed: asyncio.Task[None]) -> None:
            self._auto_tasks.pop(run.id, None)
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(forget)

    async def _wait_and_auto_advance(self, run_id: UUID) -> None:
        run = await self.require(run_id)
        if run.auto_advance_at is None:
            return
        delay = (run.auto_advance_at - datetime.now(UTC)).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            await self.auto_advance(run_id)
        except ValueError as error:
            async with self.repository.lock(run_id):
                current = await self.require(run_id)
                if current.active_match_id is None and not current.auto_run_paused:
                    await self.repository.save(
                        current.model_copy(
                            update={
                                "auto_run_paused": True,
                                "auto_advance_at": None,
                                "error": f"Automatic progression paused: {error}",
                            }
                        ),
                        expected_revision=current.revision,
                    )

    @staticmethod
    def _candidates(
        metadata: tuple[SpeciesMetadata, ...], *, abilities_supported: bool
    ) -> tuple[tuple[DraftCandidate, ...], list[dict[str, str]]]:
        candidates: list[DraftCandidate] = []
        excluded: list[dict[str, str]] = []
        for species in metadata:
            if (
                species.battle_only
                or species.cosmetic
                or species.unavailable
                or species.is_mega
                or species.is_gmax
            ):
                excluded.append(
                    {
                        "species": species.name,
                        "state": "unavailable",
                        "reason": "temporary or special-mechanic form excluded",
                    }
                )
                continue
            if abilities_supported and not species.abilities:
                excluded.append(
                    {
                        "species": species.name,
                        "state": "unavailable",
                        "reason": "format requires abilities but Showdown exposes none",
                    }
                )
                continue
            candidates.append(
                DraftCandidate(
                    entry_id=species.id,
                    species=species.name,
                    showdown_id=species.id,
                    base_species_id=species.base_species_id,
                    national_dex_number=species.national_dex_number,
                    introduction_generation=species.introduction_generation,
                    types=species.types,
                    base_stat_total=species.base_stat_total,
                    base_stats=species.base_stats,
                    abilities=species.abilities,
                    recommended_moves=species.recommended_moves,
                    required_item=species.required_item,
                )
            )
        return tuple(sorted(candidates, key=lambda item: item.entry_id)), excluded

    async def create(self, payload: CreateChallengeRun) -> ChallengeRunView:
        definition = _definition(payload.definition_id)
        if payload.draft_rules is not None:
            definition = definition.model_copy(update={"draft_rules": payload.draft_rules})
        if payload.training_rules is not None:
            definition = definition.model_copy(update={"training_rules": payload.training_rules})
        species_snapshot = await self.species.snapshot(definition.format)
        candidates, _ = self._candidates(
            species_snapshot.species,
            abilities_supported=species_snapshot.abilities_supported,
        )
        identities = {
            candidate.base_species_id
            if definition.draft_rules.species_clause
            else candidate.entry_id
            for candidate in candidates
        }
        if len(identities) < definition.draft_rules.roster_size:
            raise ValueError(
                f"draft pool has only {len(identities)} eligible Species-Clause identities for "
                f"a roster of {definition.draft_rules.roster_size}"
            )
        catalog_material = json.dumps(
            {
                "showdown_version": species_snapshot.showdown_version,
                "format": species_snapshot.format,
                "candidates": [item.model_dump(mode="json") for item in candidates],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        now = datetime.now(UTC)
        run = ChallengeRun(
            id=uuid4(),
            name=payload.name,
            definition=definition,
            status=ChallengeStatus.DRAFTING,
            seed=payload.seed,
            draft_rules_version=DRAFT_RULES_VERSION,
            draft_pool=DraftPoolSnapshot(
                showdown_version=species_snapshot.showdown_version,
                format=species_snapshot.format,
                format_generation=species_snapshot.format_generation,
                abilities_supported=species_snapshot.abilities_supported,
                catalog_hash=hashlib.sha256(catalog_material).hexdigest(),
                candidates=candidates,
            ),
            draft_controller=payload.draft_controller,
            battle_controller=payload.battle_controller,
            opponent_controller=payload.opponent_controller,
            battle_experience=payload.battle_experience,
            difficulty=payload.difficulty,
            rerolls_remaining=definition.draft_rules.rerolls,
            type_rerolls_remaining=definition.draft_rules.type_rerolls,
            generation_rerolls_remaining=definition.draft_rules.generation_rerolls,
            created_at=now,
            updated_at=now,
        )
        run = attach_offer(run)
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
                if run is None:
                    continue
                if run.status is ChallengeStatus.PREPARING:
                    prepared = await self._auto_prepare_team(run.id)
                    if prepared.revision != run.revision:
                        reconciled.append(run.id)
                    continue
                if (
                    run.active_match_id is None
                    and run.status in {ChallengeStatus.READY, ChallengeStatus.STAGE_RESULT}
                    and run.auto_advance_at is not None
                ):
                    self._schedule_auto_run(run)
                    continue
                if run.active_match_id is None:
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
        run = await self._refresh_active(run)
        summary = None
        if run.stage_results and self.battles is not None:
            archive = await self.battles.repository.get_match(run.stage_results[-1].match_id)
            if archive is not None and archive.status is MatchStatus.COMPLETED:
                summary = derive_battle_summary(archive)
        return self.view(run, latest_battle_summary=summary)

    def view(
        self,
        run: ChallengeRun,
        *,
        latest_battle_summary: ChallengeBattleSummary | None = None,
    ) -> ChallengeRunView:
        stages = tuple(_public_stage(stage, run.difficulty) for stage in run.definition.stages)
        current = stages[run.current_stage_index] if run.current_stage_index < len(stages) else None
        wins = sum(item.status == "won" for item in run.stage_results)
        losses = sum(item.status == "lost" for item in run.stage_results)
        draws = sum(item.status == "draw" for item in run.stage_results)
        technical_failures = sum(
            item.status in {"failed", "cancelled", "interrupted"} for item in run.stage_results
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
        visible_candidates = {pick.candidate.entry_id: pick.candidate for pick in run.picks}
        for history in run.draft_history:
            visible_candidates.update(
                (candidate.entry_id, candidate) for candidate in history.offer.options
            )
        if run.current_offer is not None:
            visible_candidates.update(
                (candidate.entry_id, candidate) for candidate in run.current_offer.options
            )
        return ChallengeRunView(
            run=run.model_copy(
                update={
                    "draft_pool": run.draft_pool.model_copy(
                        update={"candidates": tuple(visible_candidates.values())}
                    ),
                    "definition": run.definition.model_copy(
                        update={
                            "stages": tuple(
                                stage.model_copy(update={"opponent_team": "[private stage team]"})
                                for stage in run.definition.stages
                            )
                        }
                    ),
                }
            ),
            stages=stages,
            current_stage=current,
            latest_battle_summary=latest_battle_summary,
            team_export_scaffold=_team_scaffold(run),
            can_reroll=(
                run.status is ChallengeStatus.DRAFTING
                and run.current_offer is not None
                and run.rerolls_remaining > 0
                and can_generate_offer(
                    run,
                    nonce=run.offer_nonce + 1,
                    fixed_generation=run.current_offer.generation,
                    fixed_type=run.current_offer.type,
                )
            ),
            can_reroll_type=(
                run.status is ChallengeStatus.DRAFTING
                and run.current_offer is not None
                and run.type_rerolls_remaining > 0
                and can_generate_offer(
                    run,
                    nonce=run.offer_nonce + 1,
                    fixed_generation=run.current_offer.generation,
                    excluded_type=run.current_offer.type,
                )
            ),
            can_reroll_generation=(
                run.status is ChallengeStatus.DRAFTING
                and run.current_offer is not None
                and run.generation_rerolls_remaining > 0
                and can_generate_offer(
                    run,
                    nonce=run.offer_nonce + 1,
                    fixed_type=run.current_offer.type,
                    excluded_generation=run.current_offer.generation,
                )
            ),
            unseen_candidate_count=unseen_identity_count(run),
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
                rerolls_used=(
                    run.definition.draft_rules.rerolls
                    - run.rerolls_remaining
                    + run.definition.draft_rules.type_rerolls
                    - run.type_rerolls_remaining
                    + run.definition.draft_rules.generation_rerolls
                    - run.generation_rerolls_remaining
                ),
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
            ability_selections = dict(run.ability_selections)
            ev_allocations = dict(run.ev_allocations)
            if complete:
                for pick in picks:
                    ability_selections[pick.candidate.entry_id] = (
                        pick.candidate.abilities[0].id
                        if run.draft_pool.abilities_supported and pick.candidate.abilities
                        else None
                    )
                    ev_allocations[pick.candidate.entry_id] = _recommended_ev_spread(pick.candidate)
            updated = run.model_copy(
                update={
                    "picks": picks,
                    "draft_history": (
                        *run.draft_history,
                        DraftHistoryEntry(
                            offer=run.current_offer,
                            outcome="picked",
                            selected_entry_id=candidate.entry_id,
                            decided_by=controller,
                        ),
                    ),
                    "ability_selections": ability_selections,
                    "ev_allocations": ev_allocations,
                    "status": ChallengeStatus.PREPARING if complete else ChallengeStatus.DRAFTING,
                    "current_offer": None,
                    "offer_nonce": 0,
                }
            )
            if not complete:
                updated = attach_offer(updated)
            stored = await self.repository.save(updated, expected_revision=run.revision)
        if complete:
            return await self._auto_prepare_team(stored.id)
        return stored

    async def _auto_prepare_team(self, run_id: UUID) -> ChallengeRun:
        """Validate and persist recommended sets without a mandatory setup screen."""
        async with self.repository.lock(run_id):
            run = await self.require(run_id)
            if run.status is not ChallengeStatus.PREPARING:
                return run
            scaffold = _team_scaffold(run)
            if scaffold is None:
                raise ValueError("complete draft has no team scaffold")
            submitted = _with_zero_ev_confirmation(_apply_selected_abilities(scaffold, run))
            try:
                validation = await self.battles.team_validator.validate(
                    submitted, run.definition.format
                )
            except (RuntimeError, ValueError, OSError) as error:
                # The validator being unreachable must not strand the run in `preparing`
                # forever with no state, no error, and no way out. Park it in Team review
                # with the reason; the user can validate again from the editor.
                return await self.repository.save(
                    run.model_copy(
                        update={
                            "status": ChallengeStatus.TEAM_REVIEW,
                            "error": (
                                "Automatic team preparation could not reach the Showdown team "
                                f"validator: {error}"
                            ),
                        }
                    ),
                    expected_revision=run.revision,
                )
            if not validation.valid:
                return await self.repository.save(
                    run.model_copy(
                        update={
                            "status": ChallengeStatus.TEAM_REVIEW,
                            "error": "Automatic team preparation failed: "
                            + "; ".join(validation.errors),
                        }
                    ),
                    expected_revision=run.revision,
                )
            snapshot = await self.battles.teams.create_snapshot(
                name=f"{run.name} · recommended roster",
                source=TeamSource.PRESET,
                submitted_text=submitted,
                validation=validation,
            )
            auto_advance_at = (
                datetime.now(UTC) + timedelta(seconds=1)
                if self.auto_run_available(run) and not run.auto_run_paused
                else None
            )
            stored = await self.repository.save(
                run.model_copy(
                    update={
                        "team_snapshot_id": snapshot.id,
                        "status": ChallengeStatus.READY,
                        "auto_advance_at": auto_advance_at,
                        "error": None,
                    }
                ),
                expected_revision=run.revision,
            )
            self._schedule_auto_run(stored)
            return stored

    async def reroll(
        self,
        run_id: UUID,
        fingerprint: str,
        expected_revision: int,
        *,
        kind: Literal["pokemon", "type", "generation"] = "pokemon",
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
            counter = {
                "pokemon": run.rerolls_remaining,
                "type": run.type_rerolls_remaining,
                "generation": run.generation_rerolls_remaining,
            }[kind]
            if counter <= 0:
                raise ValueError(f"no {kind} rerolls remain")
            offer = run.current_offer
            nonce = run.offer_nonce + 1
            counter_update = {
                "pokemon": {"rerolls_remaining": run.rerolls_remaining - 1},
                "type": {"type_rerolls_remaining": run.type_rerolls_remaining - 1},
                "generation": {
                    "generation_rerolls_remaining": run.generation_rerolls_remaining - 1
                },
            }[kind]
            history_outcome: Literal[
                "pokemon_rerolled", "type_rerolled", "generation_rerolled"
            ]
            if kind == "pokemon":
                history_outcome = "pokemon_rerolled"
            elif kind == "type":
                history_outcome = "type_rerolled"
            else:
                history_outcome = "generation_rerolled"
            updated = run.model_copy(
                update={
                    **counter_update,
                    "offer_nonce": nonce,
                    "current_offer": None,
                    "draft_history": (
                        *run.draft_history,
                        DraftHistoryEntry(
                            offer=offer,
                            outcome=history_outcome,
                            decided_by=selected_by or run.draft_controller.kind,
                        ),
                    ),
                }
            )
            if kind == "type":
                updated = attach_offer(
                    updated,
                    nonce=nonce,
                    fixed_generation=offer.generation,
                    excluded_type=offer.type,
                )
            elif kind == "generation":
                updated = attach_offer(
                    updated,
                    nonce=nonce,
                    fixed_type=offer.type,
                    excluded_generation=offer.generation,
                )
            else:
                updated = attach_offer(
                    updated,
                    nonce=nonce,
                    fixed_generation=offer.generation,
                    fixed_type=offer.type,
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
        # An agent drafter gets the same three single-use powers a human drafter has.
        # Offering only the Pokemon reroll left two of them permanently unusable.
        if run.rerolls_remaining and can_generate_offer(
            run,
            nonce=run.offer_nonce + 1,
            fixed_generation=run.current_offer.generation,
            fixed_type=run.current_offer.type,
        ):
            legal.append("reroll")
        if run.type_rerolls_remaining and can_generate_offer(
            run,
            nonce=run.offer_nonce + 1,
            fixed_generation=run.current_offer.generation,
            excluded_type=run.current_offer.type,
        ):
            legal.append("reroll:type")
        if run.generation_rerolls_remaining and can_generate_offer(
            run,
            nonce=run.offer_nonce + 1,
            fixed_type=run.current_offer.type,
            excluded_generation=run.current_offer.generation,
        ):
            legal.append("reroll:generation")
        prompt = json.dumps(
            {
                "task": "Select exactly one legal draft action. Return JSON only; no reasoning.",
                "challenge_rules": {
                    "format": run.definition.format,
                    "draft": run.definition.draft_rules.model_dump(mode="json"),
                    "training": run.definition.training_rules.model_dump(mode="json"),
                    "offer_consumption": (
                        "Every currently displayed Pokemon disappears after this decision, "
                        "including rejected choices. Reroll also consumes and replaces the "
                        "complete offer. None can appear again in this run."
                    ),
                },
                "remaining_slots": run.definition.draft_rules.roster_size - len(run.picks),
                "rerolls_remaining": {
                    "reroll": run.rerolls_remaining,
                    "reroll:type": run.type_rerolls_remaining,
                    "reroll:generation": run.generation_rerolls_remaining,
                },
                "reroll_effects": {
                    "reroll": "Keep this Generation and Type; replace only the Pokemon.",
                    "reroll:type": "Keep this Generation; roll a different Type and new Pokemon.",
                    "reroll:generation": (
                        "Keep this Type; roll a different Generation and new Pokemon."
                    ),
                },
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
            if parsed.action.startswith("reroll"):
                kind: Literal["pokemon", "type", "generation"] = (
                    "type"
                    if parsed.action == "reroll:type"
                    else "generation"
                    if parsed.action == "reroll:generation"
                    else "pokemon"
                )
                return await self.reroll(
                    run.id,
                    run.current_offer.fingerprint,
                    run.revision,
                    kind=kind,
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
            updated = run.model_copy(
                update={
                    "ev_allocations": allocations,
                    "status": ChallengeStatus.TEAM_REVIEW,
                }
            )
            return await self.repository.save(updated, expected_revision=run.revision)

    async def open_team_editor(self, run_id: UUID, expected_revision: int) -> ChallengeRun:
        async with self.repository.lock(run_id):
            run = await self.require(run_id)
            if run.revision != expected_revision:
                raise ValueError(f"stale challenge revision: current {run.revision}")
            if (
                run.status is not ChallengeStatus.READY
                or run.current_stage_index != 0
                or run.stage_results
                or run.active_match_id is not None
            ):
                raise ValueError("advanced team setup is available only before the first stage")
            return await self.repository.save(
                run.model_copy(
                    update={
                        "status": ChallengeStatus.TEAM_REVIEW,
                        "auto_advance_at": None,
                    }
                ),
                expected_revision=run.revision,
            )

    async def save_abilities(
        self,
        run_id: UUID,
        abilities: dict[str, str | None],
        expected_revision: int,
    ) -> ChallengeRun:
        async with self.repository.lock(run_id):
            run = await self.require(run_id)
            if run.revision != expected_revision:
                raise ValueError(f"stale challenge revision: current {run.revision}")
            if run.status not in {ChallengeStatus.TRAINING, ChallengeStatus.TEAM_REVIEW}:
                raise ValueError("challenge is not accepting team configuration")
            expected = {pick.candidate.entry_id for pick in run.picks}
            if set(abilities) != expected:
                raise ValueError("ability selections must contain every drafted entry exactly once")
            normalized: dict[str, str | None] = {}
            for pick in run.picks:
                selected = abilities[pick.candidate.entry_id]
                if not run.draft_pool.abilities_supported:
                    if selected is not None:
                        raise ValueError(
                            f"{run.definition.format} does not support Pokemon abilities"
                        )
                    normalized[pick.candidate.entry_id] = None
                    continue
                legal = {ability.id for ability in pick.candidate.abilities}
                if selected not in legal:
                    raise ValueError(f"invalid ability for {pick.candidate.species}")
                normalized[pick.candidate.entry_id] = selected
            updated = run.model_copy(update={"ability_selections": normalized})
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
            configured_team = _apply_selected_abilities(team_text, run)
            submitted_team = _with_zero_ev_confirmation(configured_team)
            validation = await self.battles.team_validator.validate(
                submitted_team, run.definition.format
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
                if run.draft_pool.abilities_supported:
                    actual_ability = showdown_id(str(pokemon.get("ability") or ""))
                    if actual_ability != run.ability_selections.get(entry_id):
                        raise ValueError(f"final team ability for {species_id} is not selected")
            snapshot = await self.battles.teams.create_snapshot(
                name=f"{run.name} · source roster",
                source=TeamSource.IMPORTED,
                submitted_text=submitted_team,
                validation=validation,
            )
            update: dict[str, object] = {
                "team_snapshot_id": snapshot.id,
                "status": ChallengeStatus.READY,
            }
            if self.auto_run_available(run) and not run.auto_run_paused:
                update["auto_advance_at"] = datetime.now(UTC) + timedelta(seconds=1)
            updated = run.model_copy(update=update)
            saved = await self.repository.save(updated, expected_revision=run.revision)
            self._schedule_auto_run(saved)
            return saved

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
            # Each attempt at a stage gets its own deterministic seed, so retrying a lost
            # stage is a genuine retry rather than a byte-identical rerun of the same loss.
            stage_attempts = sum(
                1 for item in run.stage_results if item.stage_index == run.current_stage_index
            )
            # The drafted roster snapshot stays immutable; only this derived export moves.
            player_level = player_stage_level(stage.level, run.difficulty)
            # A hand-edited set can carry a move with an event minimum level that the
            # difficulty modifier would drop below. Give back the smallest amount of the
            # level disadvantage that makes the derived team legal instead of failing the
            # stage; the opponent's level never moves.
            player_validation = await self.battles.team_validator.validate(
                _with_level(source.normalized_export, player_level), run.definition.format
            )
            while not player_validation.valid and player_level < stage.level:
                player_level = min(stage.level, player_level + 5)
                player_validation = await self.battles.team_validator.validate(
                    _with_level(source.normalized_export, player_level), run.definition.format
                )
            opponent_validation = await self.battles.team_validator.validate(
                _with_unique_duplicate_nicknames(
                    _with_level(stage.opponent_team, stage.level)
                ),
                run.definition.format,
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
                name=f"{run.name} · {stage.name} · level {player_level}",
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
                random_seed=run.seed + run.current_stage_index + 1000 * stage_attempts,
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
                    "auto_advance_at": None,
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
            if any(result.match_id == match_id for result in run.stage_results):
                return
            if run.current_stage_index >= len(run.definition.stages):
                return
            stage_index = run.current_stage_index
            stage = run.definition.stages[stage_index]
            if archive.challenge_stage_id != stage.id:
                raise ValueError(
                    f"challenge match stage mismatch: expected {stage.id}, got "
                    f"{archive.challenge_stage_id}"
                )
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
                duration_seconds=max(0, (archive.updated_at - archive.created_at).total_seconds()),
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
            auto_advance_at = (
                datetime.now(UTC) + timedelta(seconds=AUTO_ADVANCE_DELAYS[run.battle_experience])
                if won
                and not completed
                and self.auto_run_available(run)
                and not run.auto_run_paused
                else None
            )
            updated = run.model_copy(
                update={
                    "status": ChallengeStatus.COMPLETED
                    if completed
                    else ChallengeStatus.STAGE_RESULT,
                    "current_stage_index": next_index,
                    "active_match_id": None,
                    "stage_results": (*run.stage_results, result),
                    "auto_advance_at": auto_advance_at,
                    "completed_at": datetime.now(UTC) if completed else None,
                    "error": archive.error if outcome in {"failed", "interrupted"} else None,
                }
            )
            stored = await self.repository.save(updated, expected_revision=run.revision)
        self._schedule_auto_run(stored)

    async def auto_advance(self, run_id: UUID) -> tuple[ChallengeRun, MatchArchive | None]:
        """Idempotently launch the next stage when the persisted deadline is due."""
        run = await self.require(run_id)
        if (
            not self.auto_run_available(run)
            or run.auto_run_paused
            or run.auto_advance_at is None
            or run.status not in {ChallengeStatus.READY, ChallengeStatus.STAGE_RESULT}
            or run.current_stage_index >= len(run.definition.stages)
        ):
            match = (
                await self.battles.repository.get_match(run.active_match_id)
                if run.active_match_id is not None
                else None
            )
            return run, match
        if run.auto_advance_at > datetime.now(UTC):
            self._schedule_auto_run(run)
            return run, None
        try:
            return await self.launch_stage(run.id, run.revision)
        except ValueError:
            current = await self.require(run.id)
            if current.active_match_id is not None:
                return current, await self.battles.repository.get_match(current.active_match_id)
            raise

    async def pause_auto_run(self, run_id: UUID, expected_revision: int) -> ChallengeRun:
        async with self.repository.lock(run_id):
            run = await self.require(run_id)
            if not self.auto_run_available(run):
                raise ValueError("this run requires player-controlled battles")
            # Pause is a monotonic safety command: a concurrent terminal update or launch must
            # never discard the user's request to stop after the active match. Keep the revision
            # in the API contract for diagnostics, but apply the current persisted revision.
            if run.auto_run_paused:
                return run
            return await self.repository.save(
                run.model_copy(update={"auto_run_paused": True, "auto_advance_at": None}),
                expected_revision=run.revision,
            )

    async def continue_auto_run(
        self, run_id: UUID, expected_revision: int
    ) -> tuple[ChallengeRun, MatchArchive | None]:
        async with self.repository.lock(run_id):
            run = await self.require(run_id)
            if run.revision != expected_revision:
                raise ValueError(f"stale challenge revision: current {run.revision}")
            if not self.auto_run_available(run):
                raise ValueError("this run requires player-controlled battles")
            launchable = run.status in {ChallengeStatus.READY, ChallengeStatus.STAGE_RESULT}
            stored = await self.repository.save(
                run.model_copy(
                    update={
                        "auto_run_paused": False,
                        "auto_advance_at": datetime.now(UTC) if launchable else None,
                    }
                ),
                expected_revision=run.revision,
            )
        if launchable:
            return await self.auto_advance(stored.id)
        return stored, None

    async def delete(self, run_id: UUID, expected_revision: int) -> None:
        """Remove a saved run. Recorded stage matches and replays are immutable and stay."""
        active_match_id: UUID | None
        async with self.repository.lock(run_id):
            run = await self.require(run_id)
            if run.revision != expected_revision:
                raise ValueError(f"stale challenge revision: current {run.revision}")
            active_match_id = run.active_match_id
            task = self._auto_tasks.pop(run.id, None)
            if task is not None:
                task.cancel()
            if not await self.repository.delete(run_id):
                raise KeyError(str(run_id))
        if active_match_id is not None:
            await self.battles.cancel_match(active_match_id)

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
                update={
                    "status": ChallengeStatus.CANCELLED,
                    "active_match_id": None,
                    "auto_advance_at": None,
                }
            )
            stored = await self.repository.save(updated, expected_revision=run.revision)
        if active_match_id is not None:
            await self.battles.cancel_match(active_match_id)
        return stored
