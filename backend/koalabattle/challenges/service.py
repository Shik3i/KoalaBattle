from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from itertools import combinations
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, ValidationError

from koalabattle.agents.providers import ProviderRequest
from koalabattle.agents.providers.base import safe_error_detail
from koalabattle.core.models import (
    AgentType,
    CampaignBadge,
    MatchArchive,
    MatchConfig,
    MatchStatus,
    PlayerConfig,
    Side,
    TeamPolicy,
    TeamSource,
)
from koalabattle.service import BattleService
from koalabattle.teams.models import TeamValidationResult
from koalabattle.teams.service import TeamValidator

from .domain import (
    attach_offer,
    can_generate_offer,
    deterministic_random_choice,
    unseen_identity_count,
)
from .models import (
    DRAFT_RULES_VERSION,
    NON_LEVEL_EVOLUTION_FALLBACK_LEVEL,
    BattleControllerSnapshot,
    ChallengeBattleOverview,
    ChallengeBattleSummary,
    ChallengeDefinition,
    ChallengeDefinitionSummary,
    ChallengeDifficulty,
    ChallengeMegaOption,
    ChallengeMegaSelection,
    ChallengePokemonStats,
    ChallengeRun,
    ChallengeRunStats,
    ChallengeRunView,
    ChallengeStage,
    ChallengeStageResult,
    ChallengeStatus,
    ContinueChallengeRun,
    CreateChallengeRun,
    CurrentPickView,
    DraftCandidate,
    DraftControllerKind,
    DraftHistoryEntry,
    DraftOffer,
    DraftPick,
    DraftPoolSnapshot,
    DraftRules,
    EvolutionEvent,
    EvolutionTrigger,
    EvSpread,
    MegaEvolutionOption,
    PokemonIvSpread,
    PublicChallengeStage,
    opponent_stage_level,
)
from .rarity import DraftPointsSnapshot, load_draft_points, rarity_for_candidate
from .repository import ChallengeRepository
from .species import ShowdownSpeciesCatalog, SpeciesMetadata, showdown_id

CONTENT_ROOT = Path(__file__).with_name("content")
#: Quick Sim has no watched presentation to acknowledge. Watched modes deliberately receive
#: no deadline: the browser advances only after its result card has actually finished.
AUTO_ADVANCE_DELAYS = {"quick-sim": 0.0, "fast-watch": 0.0, "normal": 0.0}
PRESENTATION_GATED_EXPERIENCES = {"fast-watch", "normal"}
# The first eight stages are the Gym/Trial route; Mega selection opens after its eighth
# badge, immediately before the first Elite Four stage (stage index 8 in regional routes).
MEGA_UNLOCK_STAGE_INDEX = 8
CAMPAIGN_DOUBLES_FORMAT = "gen9koalabattlecanonicalnatdexdraftdoubles"


def _scaled_stage_level(index: int, count: int) -> int:
    """Every newly created route progresses evenly from level 5 to level 100."""
    if count <= 1:
        return 100
    return round(5 + (95 * index / (count - 1)))


def _with_scaled_levels(definition: ChallengeDefinition) -> ChallengeDefinition:
    return definition.model_copy(
        update={
            "format": "gen9koalabattlecanonicalnatdexdraft",
            "stages": tuple(
                stage.model_copy(
                    update={"level": _scaled_stage_level(index, len(definition.stages))}
                )
                for index, stage in enumerate(definition.stages)
            )
        }
    )


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


def derive_battle_overview(
    run: ChallengeRun, archives: tuple[MatchArchive, ...]
) -> tuple[ChallengeBattleOverview, ...]:
    """Combine each saved stage result with its replay-derived participant summary."""
    summaries = {archive.id: derive_battle_summary(archive) for archive in archives}
    attempts: dict[str, int] = {}
    overview: list[ChallengeBattleOverview] = []
    for result in run.stage_results:
        attempt = attempts.get(result.stage_id, 0) + 1
        attempts[result.stage_id] = attempt
        summary = summaries.get(result.match_id)
        overview.append(
            ChallengeBattleOverview(
                stage_id=result.stage_id,
                stage_index=result.stage_index,
                attempt=attempt,
                match_id=result.match_id,
                status=result.status,
                winner=result.winner,
                turns=result.turns,
                duration_seconds=result.duration_seconds,
                player_participants=summary.player_participants if summary else (),
                opponent_participants=summary.opponent_participants if summary else (),
                player_fainted=summary.player_fainted if summary else (),
                opponent_fainted=summary.opponent_fainted if summary else (),
            )
        )
    return tuple(overview)


def _hp_value(value: object) -> tuple[int, int | None] | None:
    """Parse Showdown's public `current/max` or `0 fnt` HP token."""
    if not isinstance(value, str):
        return None
    token = value.split(" ", 1)[0].strip()
    if "/" not in token:
        return (int(token), None) if token.isdigit() else None
    current, maximum = token.split("/", 1)
    if not current.isdigit() or not maximum.isdigit() or int(maximum) <= 0:
        return None
    return int(current), int(maximum)


def _event_species(value: object, aliases: dict[tuple[str, str], str]) -> tuple[str, str] | None:
    parsed = _event_pokemon(value)
    if parsed is None:
        return None
    side, nickname = parsed
    return side, aliases.get(parsed, nickname)


def derive_pokemon_statistics(
    run: ChallengeRun, archives: tuple[MatchArchive, ...]
) -> tuple[ChallengePokemonStats, ...]:
    """Aggregate player contribution metrics from the immutable battle event stream.

    Damage is reported as HP-equivalent points (using the public max HP when Showdown
    provides it); older archives without that value fall back to a 100-point scale.
    """
    picks = run.picks
    entry_by_species: dict[str, str] = {}
    values: dict[str, dict[str, int]] = {}
    for pick in picks:
        entry_id = pick.candidate.entry_id
        species = pick.current_species or pick.candidate.species
        for name in (species, pick.candidate.species):
            entry_by_species[showdown_id(name)] = entry_id
        values[entry_id] = {
            key: 0
            for key in (
                "battles",
                "switch_ins",
                "turns_active",
                "moves_used",
                "damage_dealt",
                "damage_taken",
                "healing",
                "knockouts",
                "fainted",
                "critical_hits",
                "statuses_inflicted",
            )
        }

    for archive in archives:
        aliases: dict[tuple[str, str], str] = {}
        active: dict[str, tuple[str, str]] = {}
        hp: dict[tuple[str, str], tuple[int, int | None]] = {}
        move_sources: dict[tuple[str, str], tuple[str, str]] = {}
        damage_sources: dict[tuple[str, str], tuple[str, str]] = {}
        participants: set[str] = set()

        def player_entry(value: object, current_aliases: dict[tuple[str, str], str]) -> str | None:
            resolved = _event_species(value, current_aliases)
            if resolved is None or resolved[0] != "p1":
                return None
            return entry_by_species.get(showdown_id(resolved[1]))

        def actor_key(value: object) -> tuple[str, str] | None:
            parsed = _event_pokemon(value)
            return parsed

        def amount(previous: tuple[int, int | None] | None, current: tuple[int, int | None]) -> int:
            if previous is None:
                return 0
            delta = max(0, previous[0] - current[0])
            if current[1] or previous[1]:
                maximum = current[1] or previous[1] or 100
                return round(delta / maximum * maximum)
            return delta

        for event in archive.events:
            payload = event.payload
            if event.event_type == "pokemon_switched":
                actor = actor_key(payload.get("actor"))
                if actor is None:
                    continue
                details = payload.get("details")
                species = (
                    str(details).split(",", 1)[0].strip()
                    if isinstance(details, str) and details.strip()
                    else actor[1]
                )
                aliases[actor] = species
                active[actor[0]] = actor
                event_entry_id = player_entry(payload.get("actor"), aliases)
                if event_entry_id is not None:
                    values[event_entry_id]["switch_ins"] += 1
                    participants.add(event_entry_id)
                parsed_hp = _hp_value(payload.get("hp"))
                if parsed_hp is not None:
                    hp[actor] = parsed_hp
            elif event.event_type == "turn_started":
                for actor in active.values():
                    event_entry_id = player_entry(f"{actor[0]}a: {actor[1]}", aliases)
                    if event_entry_id is not None:
                        values[event_entry_id]["turns_active"] += 1
            elif event.event_type == "move_used":
                actor = actor_key(payload.get("actor"))
                target = actor_key(payload.get("target"))
                if actor is not None and target is not None:
                    move_sources[target] = actor
                event_entry_id = player_entry(payload.get("actor"), aliases)
                if event_entry_id is not None:
                    values[event_entry_id]["moves_used"] += 1
                    participants.add(event_entry_id)
            elif event.event_type in {"damage", "healing"}:
                target = actor_key(payload.get("target"))
                current = _hp_value(payload.get("hp"))
                if target is None or current is None:
                    continue
                previous = hp.get(target)
                if event.event_type == "damage":
                    points = amount(previous, current)
                    target_entry = player_entry(payload.get("target"), aliases)
                    if target_entry is not None:
                        values[target_entry]["damage_taken"] += points
                        participants.add(target_entry)
                    source = (
                        actor_key(payload.get("source_actor"))
                        or damage_sources.get(target)
                        or move_sources.get(target)
                    )
                    source_entry = (
                        player_entry(f"{source[0]}a: {source[1]}", aliases) if source else None
                    )
                    if source_entry is not None:
                        values[source_entry]["damage_dealt"] += points
                        participants.add(source_entry)
                    if source is not None:
                        damage_sources[target] = source
                else:
                    gained = amount(current, previous) if previous is not None else 0
                    target_entry = player_entry(payload.get("target"), aliases)
                    if target_entry is not None:
                        values[target_entry]["healing"] += gained
                        participants.add(target_entry)
                hp[target] = current
            elif event.event_type == "critical_hit":
                target = actor_key(payload.get("target"))
                source = damage_sources.get(target) if target else None
                source_entry = (
                    player_entry(f"{source[0]}a: {source[1]}", aliases) if source else None
                )
                if source_entry is not None:
                    values[source_entry]["critical_hits"] += 1
            elif event.event_type == "status_applied":
                target = actor_key(payload.get("target"))
                source = actor_key(payload.get("source_actor")) or (
                    damage_sources.get(target) if target else None
                )
                source_entry = (
                    player_entry(f"{source[0]}a: {source[1]}", aliases) if source else None
                )
                if source_entry is not None:
                    values[source_entry]["statuses_inflicted"] += 1
            elif event.event_type == "pokemon_fainted":
                target = actor_key(payload.get("target"))
                target_entry = player_entry(payload.get("target"), aliases)
                if target_entry is not None:
                    values[target_entry]["fainted"] += 1
                    participants.add(target_entry)
                source = damage_sources.get(target) if target else None
                source_entry = (
                    player_entry(f"{source[0]}a: {source[1]}", aliases) if source else None
                )
                if source_entry is not None:
                    values[source_entry]["knockouts"] += 1

        for entry_id in participants:
            values[entry_id]["battles"] += 1

    return tuple(
        ChallengePokemonStats(
            entry_id=pick.candidate.entry_id,
            species=pick.current_species or pick.candidate.species,
            drafted_species=pick.candidate.species,
            types=pick.current_types or pick.candidate.types,
            base_stats=pick.candidate.base_stats,
            **values[pick.candidate.entry_id],
        )
        for pick in picks
    )


def _resolve_draft_action(raw: str, legal: list[str], offer: DraftOffer) -> str | None:
    """Map a model's answer onto one exact legal action.

    Only `json_schema` providers get the enum enforced; DeepSeek documents `json_object`,
    so the answer routinely arrives as a bare entry id, a species name, or different case.
    Rejecting those made a correct decision look like a provider failure.
    """
    candidate = raw.strip()
    if candidate in legal:
        return candidate
    lowered = candidate.casefold()
    for action in legal:
        if action.casefold() == lowered:
            return action
    # A bare entry id or species name, with or without the prefix.
    bare = lowered.removeprefix("pick:").strip()
    for option in offer.options:
        names = {option.entry_id.casefold(), option.species.casefold(), option.showdown_id}
        if bare in names and f"pick:{option.entry_id}" in legal:
            return f"pick:{option.entry_id}"
    # A reroll named without its exact key, e.g. "reroll pokemon" or "type reroll".
    if "reroll" in lowered:
        for suffix, action in (("type", "reroll:type"), ("generation", "reroll:generation")):
            if suffix in lowered and action in legal:
                return action
        if "reroll" in legal:
            return "reroll"
    return None


class _AgentDraftAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str


def _definition(definition_id: str) -> ChallengeDefinition:
    path = CONTENT_ROOT / f"{definition_id}.json"
    if not path.is_file():
        raise KeyError(definition_id)
    definition = ChallengeDefinition.model_validate_json(path.read_text(encoding="utf-8"))
    return _with_scaled_levels(definition)


def _definition_summaries() -> tuple[ChallengeDefinitionSummary, ...]:
    summaries: list[ChallengeDefinitionSummary] = []
    for path in sorted(CONTENT_ROOT.glob("*.json")):
        try:
            definition = ChallengeDefinition.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValueError, TypeError):
            continue
        summaries.append(
            ChallengeDefinitionSummary(
                id=definition.id,
                name=definition.name,
                description=definition.description,
                region=definition.region,
                generation=definition.generation,
                campaign_kind=definition.campaign_kind,
                stage_count=len(definition.stages),
                stage_count_label=definition.stage_count_label,
                specialties=tuple(
                    dict.fromkeys(stage.specialty for stage in definition.stages if stage.specialty)
                ),
            )
        )
    return tuple(
        sorted(
            summaries,
            key=lambda item: (
                item.campaign_kind != "multi-generation",
                item.generation,
                item.name,
            ),
        )
    )


def _eligible_draft_candidates(
    candidates: tuple[DraftCandidate, ...], draft_rules: DraftRules
) -> tuple[DraftCandidate, ...]:
    if draft_rules.draft_pool_mode != "base-forms-only":
        return candidates
    return tuple(candidate for candidate in candidates if candidate.evolution_stage == 0)


def _opponent_stage_team(stage: ChallengeStage, mode: Literal["original", "filled"]) -> str:
    if mode == "filled" and stage.filled_opponent_team is not None:
        return stage.filled_opponent_team
    return stage.opponent_team


def _team_blocks(team_export: str) -> list[str]:
    return [block.strip() for block in team_export.strip().split("\n\n") if block.strip()]


_TYPE_ADVANTAGES: dict[str, frozenset[str]] = {
    "normal": frozenset(),
    "fire": frozenset({"grass", "ice", "bug", "steel"}),
    "water": frozenset({"fire", "ground", "rock"}),
    "electric": frozenset({"water", "flying"}),
    "grass": frozenset({"water", "ground", "rock"}),
    "ice": frozenset({"grass", "ground", "flying", "dragon"}),
    "fighting": frozenset({"normal", "ice", "rock", "dark", "steel"}),
    "poison": frozenset({"grass", "fairy"}),
    "ground": frozenset({"fire", "electric", "poison", "rock", "steel"}),
    "flying": frozenset({"grass", "fighting", "bug"}),
    "psychic": frozenset({"fighting", "poison"}),
    "bug": frozenset({"grass", "psychic", "dark"}),
    "rock": frozenset({"fire", "ice", "flying", "bug"}),
    "ghost": frozenset({"psychic", "ghost"}),
    "dragon": frozenset({"dragon"}),
    "dark": frozenset({"psychic", "ghost"}),
    "steel": frozenset({"ice", "rock", "fairy"}),
    "fairy": frozenset({"fighting", "dragon", "dark"}),
}


def _block_types(
    block: str, species_by_id: dict[str, SpeciesMetadata]
) -> tuple[str, ...]:
    metadata = species_by_id.get(showdown_id(_team_block_species(block)))
    return tuple(item.casefold() for item in metadata.types) if metadata else ()


def _matchup_score(own_types: tuple[str, ...], opponent_types: tuple[tuple[str, ...], ...]) -> int:
    attacking = sum(
        target in _TYPE_ADVANTAGES.get(own, frozenset())
        for target_types in opponent_types
        for own in own_types
        for target in target_types
    )
    threatened = sum(
        own in _TYPE_ADVANTAGES.get(attacker, frozenset())
        for target_types in opponent_types
        for attacker in target_types
        for own in own_types
    )
    return 4 * attacking - 3 * threatened


def _pair_synergy(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    left_weak = {
        attacker
        for attacker, targets in _TYPE_ADVANTAGES.items()
        if any(item in targets for item in left)
    }
    right_weak = {
        attacker
        for attacker, targets in _TYPE_ADVANTAGES.items()
        if any(item in targets for item in right)
    }
    left_coverage = set().union(*(_TYPE_ADVANTAGES.get(item, frozenset()) for item in left))
    right_coverage = set().union(*(_TYPE_ADVANTAGES.get(item, frozenset()) for item in right))
    mutual_cover = len(left_coverage & right_weak) + len(right_coverage & left_weak)
    shared_weaknesses = len(left_weak & right_weak)
    distinct_types = len(set(left) ^ set(right))
    return 3 * mutual_cover + distinct_types - 2 * shared_weaknesses


def _automatic_stage_team(
    team_export: str,
    opponent_export: str,
    size: int,
    species_by_id: dict[str, SpeciesMetadata],
    *,
    doubles: bool,
) -> str:
    """Choose the exact stage roster by matchup and, in Doubles, partner synergy."""
    blocks = _team_blocks(team_export)
    if not blocks:
        return team_export
    count = min(size, len(blocks))
    opponent_types = tuple(
        _block_types(block, species_by_id) for block in _team_blocks(opponent_export)
    )
    types = {block: _block_types(block, species_by_id) for block in blocks}
    individual = {block: _matchup_score(types[block], opponent_types) for block in blocks}

    def group_score(group: tuple[str, ...]) -> int:
        score = sum(individual[block] for block in group)
        if doubles:
            score += sum(
                _pair_synergy(types[left], types[right])
                for left, right in combinations(group, 2)
            )
        return score

    selected = max(combinations(blocks, count), key=group_score)
    remaining = list(selected)
    ordered: list[str] = []
    if doubles and len(remaining) >= 2:
        lead = max(
            combinations(remaining, 2),
            key=lambda pair: individual[pair[0]]
            + individual[pair[1]]
            + _pair_synergy(types[pair[0]], types[pair[1]]),
        )
        ordered.extend(lead)
        remaining = [block for block in remaining if block not in lead]
    ordered.extend(sorted(remaining, key=lambda block: -individual[block]))
    return "\n\n".join(ordered)


def _competitive_species_block(species: SpeciesMetadata) -> str | None:
    competitive = species.showdown_set
    if competitive is None:
        return None
    lines = [f"{species.name} @ {competitive.item}" if competitive.item else species.name]
    if competitive.ability:
        lines.append(f"Ability: {competitive.ability}")
    ev_line = _ev_line(competitive.evs)
    if ev_line:
        lines.append(ev_line)
    lines.append(f"{competitive.nature} Nature")
    iv_line = _iv_line(competitive.ivs)
    if iv_line:
        lines.append(iv_line)
    lines.extend(f"- {move}" for move in competitive.moves)
    return "\n".join(lines)


def _even_duo_opponent_team(
    team_export: str,
    stage: ChallengeStage,
    generation: int,
    species_by_id: dict[str, SpeciesMetadata],
) -> str:
    """Add one same-generation specialist when a Doubles stage roster is odd."""
    blocks = _team_blocks(team_export)
    if len(blocks) % 2 == 0:
        return team_export
    existing = {showdown_id(_team_block_species(block)) for block in blocks}
    specialty = (stage.specialty or "").casefold()
    if specialty in {"", "mixed", "champion", "starter type"}:
        first = species_by_id.get(showdown_id(_team_block_species(blocks[0])))
        specialty = first.types[0].casefold() if first and first.types else ""
    eligible = [
        species
        for species in species_by_id.values()
        if species.introduction_generation == generation
        and not species.unavailable
        and not species.battle_only
        and not species.cosmetic
        and not species.is_mega
        and not species.is_gmax
        and species.id not in existing
        and specialty in {item.casefold() for item in species.types}
        and species.showdown_set is not None
    ]
    eligible.sort(
        key=lambda species: (
            not species.is_legendary,
            -(species.base_stat_total or 0),
            species.national_dex_number,
            species.id,
        )
    )
    if not eligible:
        raise ValueError(
            f"no same-generation {stage.specialty or 'specialty'} Pokemon can complete "
            f"the Doubles roster for {stage.name}"
        )
    addition = _competitive_species_block(eligible[0])
    if addition is None:
        raise ValueError(f"{eligible[0].name} has no pinned competitive set")
    return "\n\n".join((*blocks, addition))


def _team_block_species(block: str) -> str:
    heading = block.splitlines()[0].split("@", 1)[0].strip()
    species_match = re.search(r"\(([^()]+)\)\s*$", heading)
    return species_match.group(1) if species_match else heading


def _legal_mega_options(
    species: SpeciesMetadata, species_by_id: dict[str, SpeciesMetadata]
) -> tuple[MegaEvolutionOption, ...]:
    """Keep only Mega forms exposed as legal by the same format catalog as validation."""
    legal: list[MegaEvolutionOption] = []
    for option in species.mega_evolutions:
        target = species_by_id.get(showdown_id(option.id))
        if target is None or target.unavailable or not target.is_mega:
            continue
        if target.required_item and showdown_id(target.required_item) != showdown_id(
            option.required_item
        ):
            continue
        legal.append(option)
    return tuple(legal)


def _opponent_mega_choices(
    team_export: str, species_by_id: dict[str, SpeciesMetadata]
) -> tuple[tuple[str, str, int], ...]:
    """List deterministic Mega candidates, including duplicate-species occurrences."""
    occurrences: dict[str, int] = {}
    choices: list[tuple[str, str, int]] = []
    for raw_block in (item.strip() for item in team_export.strip().split("\n\n") if item.strip()):
        species = _team_block_species(raw_block)
        species_id = showdown_id(species)
        occurrence = occurrences.get(species_id, 0)
        occurrences[species_id] = occurrence + 1
        metadata = species_by_id.get(species_id)
        if metadata is None:
            continue
        options = _legal_mega_options(metadata, species_by_id)
        choices.extend(
            (species, mega.required_item, occurrence)
            for mega in sorted(options, key=lambda option: option.id)
        )
    return tuple(choices)


def _prepare_opponent_stage_team(
    team_export: str, species_by_id: dict[str, SpeciesMetadata]
) -> str:
    """Complete a canonical roster with pinned, validator-legal battle details.

    Regional content deliberately stores the source-game roster (species and order) instead
    of copying modern competitive sets into every pack.  At launch, the pinned Dex supplies
    an ability, a neutral-confirmation EV line, a nature, and its authoritative recommended
    moves only when the source block does not already specify them.  Existing Kanto sets and
    any future hand-authored set therefore remain untouched.
    """
    fallback_moves: dict[str, tuple[str, ...]] = {
        "gogoat": ("Horn Leech", "Earthquake", "Bulk Up", "Milk Drink"),
        "aegislash": ("Shadow Sneak", "King's Shield", "Sacred Sword", "Iron Head"),
        "mudsdale": ("Earthquake", "Heavy Slam", "Rock Slide", "Body Press"),
        "centiskorch": ("Fire Lash", "Leech Life", "Coil", "Power Whip"),
        "coalossal": ("Stealth Rock", "Rock Blast", "Heat Crash", "Will-O-Wisp"),
        "espathra": ("Lumina Crash", "Dazzling Gleam", "Calm Mind", "Roost"),
        "copperajah": ("Heavy Slam", "Earthquake", "Power Whip", "Stealth Rock"),
        "tinkaton": ("Gigaton Hammer", "Play Rough", "Knock Off", "Swords Dance"),
        "grimmsnarl": ("Spirit Break", "Play Rough", "Sucker Punch", "Reflect"),
        "sandaconda": ("Earthquake", "Glare", "Coil", "Rock Slide"),
        "glimmora": ("Power Gem", "Sludge Wave", "Earth Power", "Stealth Rock"),
    }
    blocks: list[str] = []
    for raw_block in (item.strip() for item in team_export.strip().split("\n\n") if item.strip()):
        lines = raw_block.splitlines()
        if not lines:
            continue
        heading = lines[0].split("@", 1)[0].strip()
        species_match = re.search(r"\(([^()]+)\)\s*$", heading)
        species = species_match.group(1) if species_match else heading
        metadata = species_by_id.get(showdown_id(species))
        if metadata is None:
            blocks.append(raw_block)
            continue
        competitive = metadata.showdown_set
        details = list(lines[1:])
        if not any(line.startswith("Ability:") for line in details) and metadata.abilities:
            ability = competitive.ability if competitive else metadata.abilities[0].name
            ability_name = next(
                (
                    item.name
                    for item in metadata.abilities
                    if showdown_id(item.id) == showdown_id(ability)
                ),
                metadata.abilities[0].name,
            )
            details.insert(0, f"Ability: {ability_name}")
        if not any(line.startswith("EVs:") for line in details):
            details.append("EVs: 1 HP")
        if not any(line.endswith(" Nature") for line in details):
            details.append(f"{competitive.nature if competitive else 'Serious'} Nature")
        if not any(line.startswith("-") for line in details):
            moves = (
                metadata.recommended_moves
                or (competitive.moves if competitive else ())
                or fallback_moves.get(showdown_id(species), ())
            )
            details.extend(f"- {move}" for move in moves[:4])
        blocks.append("\n".join([lines[0], *details]))
    return "\n\n".join(blocks)


def _public_stage(stage: ChallengeStage, difficulty: ChallengeDifficulty) -> PublicChallengeStage:
    return PublicChallengeStage.model_validate(
        {
            "id": stage.id,
            "name": stage.name,
            "title": stage.title,
            "theme": stage.theme,
            "level": stage.level,
            "player_level": stage.level,
            "opponent_level": opponent_stage_level(stage.level, difficulty),
            "full_heal_before": stage.full_heal_before,
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


def _iv_line(spread: PokemonIvSpread) -> str | None:
    names = (
        ("HP", spread.hp),
        ("Atk", spread.atk),
        ("Def", spread.defense),
        ("SpA", spread.spa),
        ("SpD", spread.spd),
        ("Spe", spread.spe),
    )
    values = [f"{value} {name}" for name, value in names if value != 31]
    return f"IVs: {' / '.join(values)}" if values else None


def _recommended_ev_spread(candidate: DraftCandidate) -> EvSpread:
    """Return the same deterministic first-choice preset shown by Training Camp."""
    if candidate.showdown_set is not None:
        return candidate.showdown_set.evs
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
    if candidate.showdown_set is not None:
        return candidate.showdown_set.nature, candidate.showdown_set.item
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
        competitive_set = pick.candidate.showdown_set
        if competitive_set is None:
            raise ValueError(f"{pick.candidate.species} has no pinned Showdown competitive set")
        nature, item = competitive_set.nature, competitive_set.item
        selected_item = pick.candidate.required_item or item
        heading = (
            f"{pick.candidate.species} @ {selected_item}"
            if selected_item
            else pick.candidate.species
        )
        lines = [heading]
        ev_line = _ev_line(run.ev_allocations.get(pick.candidate.entry_id, EvSpread()))
        if ev_line:
            lines.append(ev_line)
        lines.append(f"{nature} Nature")
        selected = run.ability_selections.get(pick.candidate.entry_id)
        ability = next((item for item in pick.candidate.abilities if item.id == selected), None)
        if ability is not None:
            lines.append(f"Ability: {ability.name}")
        iv_line = _iv_line(competitive_set.ivs)
        if iv_line:
            lines.append(iv_line)
        if competitive_set.tera_type:
            lines.append(f"Tera Type: {competitive_set.tera_type}")
        lines.extend(f"- {move}" for move in competitive_set.moves)
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


def _terminal_evolution_paths(
    species_id: str,
    species_by_id: dict[str, SpeciesMetadata],
    seen: frozenset[str] = frozenset(),
) -> tuple[tuple[str, ...], ...]:
    """Enumerate every acyclic path to a final evolution in Showdown's pinned Dex."""
    if species_id in seen:
        return ()
    current = species_by_id.get(species_id)
    if current is None or not current.evolves_to:
        return ((species_id,),)
    paths: list[tuple[str, ...]] = []
    for option in current.evolves_to:
        child_paths = _terminal_evolution_paths(
            option.id, species_by_id, seen | {species_id}
        )
        paths.extend((species_id, *path) for path in child_paths)
    return tuple(paths) or ((species_id,),)


def _evolution_branches(
    species_id: str, species_by_id: dict[str, SpeciesMetadata]
) -> tuple[EvolutionTrigger, ...]:
    """Return every distinct final evolution when the reachable line branches."""
    paths = _terminal_evolution_paths(species_id, species_by_id)
    terminal_ids = tuple(dict.fromkeys(path[-1] for path in paths))
    if len(terminal_ids) <= 1:
        return ()
    choices: list[EvolutionTrigger] = []
    for terminal_id in terminal_ids:
        terminal = species_by_id.get(terminal_id)
        choices.append(
            EvolutionTrigger(
                id=terminal_id,
                name=terminal.name if terminal else terminal_id,
                trigger_kind="branch",
            )
        )
    return tuple(choices)


def _resolve_evolution_path(
    species_id: str, choice: str | None, species_by_id: dict[str, SpeciesMetadata]
) -> tuple[str, ...]:
    """Resolve the complete path to the chosen final evolution."""
    paths = _terminal_evolution_paths(species_id, species_by_id)
    if len(paths) == 1:
        return paths[0]
    if choice is not None:
        selected = next((path for path in paths if path[-1] == choice), None)
        if selected is not None:
            return selected
    return (species_id,)


def _current_species_id(pick: DraftPick) -> str:
    if not pick.evolution_path:
        return pick.candidate.showdown_id
    index = min(pick.evolution_stage_index, len(pick.evolution_path) - 1)
    return pick.evolution_path[index]


def _advance_evolutions(
    run: ChallengeRun,
    next_stage_index: int,
    next_stage_level: int,
    species_by_id: dict[str, SpeciesMetadata],
) -> tuple[tuple[DraftPick, ...], tuple[EvolutionEvent, ...]]:
    """Apply at most one evolution step per pick for the transition into one stage.

    Called only when a stage is actually won and there is a next stage — evolution never
    happens mid-battle or before the first stage. A pick that is already at the last step
    of its resolved path, or whose evolution was never resolved (older saved runs), never
    changes.
    """
    updated_picks: list[DraftPick] = []
    events: list[EvolutionEvent] = []
    for pick in run.picks:
        if not pick.evolution_path or pick.evolution_stage_index >= len(pick.evolution_path) - 1:
            updated_picks.append(pick)
            continue
        current_id = pick.evolution_path[pick.evolution_stage_index]
        next_id = pick.evolution_path[pick.evolution_stage_index + 1]
        current_species = species_by_id.get(current_id)
        options = current_species.evolves_to if current_species else ()
        trigger = next((option for option in options if option.id == next_id), None)
        if trigger is None:
            updated_picks.append(pick)
            continue
        reached = (
            next_stage_level >= trigger.trigger_level
            if trigger.trigger_kind == "level" and trigger.trigger_level is not None
            else next_stage_level >= NON_LEVEL_EVOLUTION_FALLBACK_LEVEL
        )
        if not reached:
            updated_picks.append(pick)
            continue
        next_species = species_by_id.get(next_id)
        updated_picks.append(
            pick.model_copy(
                update={
                    "evolution_stage_index": pick.evolution_stage_index + 1,
                    "current_species": next_species.name if next_species else trigger.name,
                    "current_types": next_species.types if next_species else (),
                }
            )
        )
        events.append(
            EvolutionEvent(
                entry_id=pick.candidate.entry_id,
                from_species=current_species.name if current_species else current_id,
                to_species=trigger.name,
            )
        )
    return tuple(updated_picks), tuple(events)


def _with_evolutions(
    team_export: str, run: ChallengeRun, species_by_id: dict[str, SpeciesMetadata]
) -> str:
    """Rewrite each evolved pick's block to its current species.

    Every field coupled to move legality comes from the new form's own recommended set
    (guaranteed legal at the campaign's lowest level). Only EVs are read from the frozen
    block so a Training allocation survives evolution. In particular, IVs must move with
    Hidden Power: retaining a prior form's IVs can change the move's derived type and make
    the otherwise authoritative target set illegal. A pick that has not evolved from its
    drafted form is left untouched.
    """
    evolved: dict[str, SpeciesMetadata] = {}
    for pick in run.picks:
        current_id = _current_species_id(pick)
        if current_id != pick.candidate.showdown_id:
            metadata = species_by_id.get(current_id)
            if metadata is not None and metadata.showdown_set is not None:
                evolved[showdown_id(pick.candidate.species)] = metadata
    if not evolved:
        return team_export
    blocks = [block.strip() for block in team_export.strip().split("\n\n") if block.strip()]
    rewritten: list[str] = []
    for block in blocks:
        lines = block.splitlines()
        heading = lines[0].split("@", 1)[0].strip()
        match = re.search(r"\(([^()]+)\)\s*$", heading)
        drafted_id = showdown_id(match.group(1) if match else heading)
        metadata = evolved.get(drafted_id)
        if metadata is None:
            rewritten.append(block)
            continue
        current_set = metadata.showdown_set
        assert current_set is not None
        ev_line = next((line for line in lines if line.startswith("EVs:")), None)
        new_lines = [
            f"{metadata.name} @ {current_set.item}" if current_set.item else metadata.name,
            f"Ability: {current_set.ability}",
        ]
        if ev_line is not None:
            new_lines.append(ev_line)
        if current_set.nature:
            new_lines.append(f"{current_set.nature} Nature")
        iv_line = _iv_line(current_set.ivs)
        if iv_line is not None:
            new_lines.append(iv_line)
        if current_set.tera_type:
            new_lines.append(f"Tera Type: {current_set.tera_type}")
        new_lines.extend(f"- {move}" for move in current_set.moves)
        rewritten.append("\n".join(new_lines))
    return "\n\n".join(rewritten)


def _mega_options(
    run: ChallengeRun, species_by_id: dict[str, SpeciesMetadata]
) -> tuple[ChallengeMegaOption, ...]:
    options: list[ChallengeMegaOption] = []
    for pick in run.picks:
        current_id = _current_species_id(pick)
        current = species_by_id.get(current_id)
        if current is None:
            continue
        options.extend(
            ChallengeMegaOption(
                entry_id=pick.candidate.entry_id,
                from_species=current.name,
                mega_species_id=mega.id,
                mega_species=mega.species,
                required_item=mega.required_item,
            )
            for mega in _legal_mega_options(current, species_by_id)
        )
    return tuple(sorted(options, key=lambda option: (option.entry_id, option.mega_species_id)))


def _automatic_mega_selections(
    run: ChallengeRun,
    team_export: str,
    opponent_export: str,
    species_by_id: dict[str, SpeciesMetadata],
) -> tuple[ChallengeMegaSelection, ...]:
    """Rank this stage's Megas by matchup, team synergy, BST, then Draft order."""
    if run.current_stage_index < MEGA_UNLOCK_STAGE_INDEX:
        return ()
    available = _team_species_ids(team_export)
    options = [
        option
        for option in _mega_options(run, species_by_id)
        if showdown_id(option.from_species) in available
    ]
    if not options:
        return ()
    opponent_types = tuple(
        _block_types(block, species_by_id) for block in _team_blocks(opponent_export)
    )
    teammate_types = {
        showdown_id(_team_block_species(block)): _block_types(block, species_by_id)
        for block in _team_blocks(team_export)
    }
    draft_order = {pick.candidate.entry_id: index for index, pick in enumerate(run.picks)}

    def score(option: ChallengeMegaOption) -> tuple[int, int, int]:
        mega = species_by_id.get(showdown_id(option.mega_species_id))
        mega_types = mega.types if mega else ()
        matchup_and_synergy = _matchup_score(mega_types, opponent_types) + sum(
            _pair_synergy(mega_types, types)
            for species_id, types in teammate_types.items()
            if species_id != showdown_id(option.from_species)
        )
        return (
            matchup_and_synergy,
            mega.base_stat_total if mega and mega.base_stat_total else 0,
            -draft_order.get(option.entry_id, len(run.picks)),
        )

    return tuple(
        ChallengeMegaSelection(**option.model_dump())
        for option in sorted(options, key=score, reverse=True)
    )


def _automatic_mega_selection(
    run: ChallengeRun,
    team_export: str,
    opponent_export: str,
    species_by_id: dict[str, SpeciesMetadata],
) -> ChallengeMegaSelection | None:
    selections = _automatic_mega_selections(run, team_export, opponent_export, species_by_id)
    return selections[0] if selections else None


def _with_selected_item(
    team_export: str, species: str, item: str, *, occurrence: int = 0
) -> str:
    """Give one exact species its persisted Mega Stone without changing its set."""
    target = showdown_id(species)
    rewritten: list[str] = []
    matched = False
    seen = 0
    for block in (part.strip() for part in team_export.strip().split("\n\n") if part.strip()):
        lines = block.splitlines()
        heading = lines[0].split("@", 1)[0].strip()
        match = re.search(r"\(([^()]+)\)\s*$", heading)
        species_id = showdown_id(match.group(1) if match else heading)
        if species_id == target:
            if seen == occurrence:
                display = heading
                lines[0] = f"{display} @ {item}"
                matched = True
            seen += 1
        rewritten.append("\n".join(lines))
    if not matched:
        raise ValueError(f"Mega selection species is missing from the derived team: {species}")
    return "\n\n".join(rewritten)


async def _validated_player_stage_team(
    team_export: str,
    opponent_export: str,
    run: ChallengeRun,
    species_by_id: dict[str, SpeciesMetadata],
    minimum_levels: Mapping[str, int],
    level: int,
    format_id: str,
    validator: TeamValidator,
) -> tuple[str, TeamValidationResult, ChallengeMegaSelection | None]:
    """Use the strongest legal Mega, or preserve a legal team without one."""
    for selection in _automatic_mega_selections(run, team_export, opponent_export, species_by_id):
        candidate = _with_selected_item(
            team_export, selection.from_species, selection.required_item
        )
        validation = await validator.validate(
            _with_level(candidate, level, minimum_levels), format_id
        )
        if validation.valid:
            return candidate, validation, selection

    validation = await validator.validate(
        _with_level(team_export, level, minimum_levels), format_id
    )
    return team_export, validation, None


def _team_species_ids(team_export: str) -> set[str]:
    """Return the species identities currently present in an exported team."""
    species_ids: set[str] = set()
    for block in (part.strip() for part in team_export.strip().split("\n\n") if part.strip()):
        heading = block.splitlines()[0].split("@", 1)[0].strip()
        match = re.search(r"\(([^()]+)\)\s*$", heading)
        species_ids.add(showdown_id(match.group(1) if match else heading))
    return species_ids


async def _validated_opponent_stage_team(
    team_export: str,
    species_by_id: dict[str, SpeciesMetadata],
    minimum_levels: Mapping[str, int],
    opponent_level: int,
    format_id: str,
    validator: TeamValidator,
    *,
    try_mega: bool,
) -> tuple[str, TeamValidationResult]:
    """Use the first validator-legal Mega candidate, or the unchanged legal team."""

    async def validate(candidate: str) -> TeamValidationResult:
        return await validator.validate(
            _with_unique_duplicate_nicknames(
                _with_level(candidate, opponent_level, minimum_levels)
            ),
            format_id,
        )

    if try_mega:
        for species, item, occurrence in _opponent_mega_choices(team_export, species_by_id):
            candidate = _with_selected_item(
                team_export, species, item, occurrence=occurrence
            )
            result = await validate(candidate)
            if result.valid:
                return candidate, result
    return team_export, await validate(team_export)


def _with_level(
    team_export: str,
    level: int,
    minimum_levels: Mapping[str, int] | None = None,
) -> str:
    blocks = [block.strip() for block in team_export.strip().split("\n\n") if block.strip()]
    normalized: list[str] = []
    for block in blocks:
        lines = block.splitlines()
        # The campaign formats explicitly relax source/event move minimums so the shared
        # route curve remains exact, including the new level-5 opening stage.
        effective_level = level
        level_indexes = [index for index, line in enumerate(lines) if line.startswith("Level:")]
        if level_indexes:
            lines[level_indexes[0]] = f"Level: {effective_level}"
            for index in reversed(level_indexes[1:]):
                lines.pop(index)
        else:
            lines.insert(1, f"Level: {effective_level}")
        ev_index = next(
            (index for index, line in enumerate(lines) if line.startswith("EVs:")), None
        )
        if ev_index is None:
            lines.insert(2, "EVs: 1 HP")
        elif effective_level < 100:
            # Showdown requires an intentional-level marker below the format maximum.
            # One otherwise unused EV is its canonical marker and cannot change a stat.
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
        lines[0] = f"{name} {seen[name]} ({name}){first_line[len(name) :]}"
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
        self._agent_tasks: dict[tuple[UUID, int], asyncio.Task[ChallengeRun]] = {}

    @staticmethod
    def definition_summaries() -> tuple[ChallengeDefinitionSummary, ...]:
        return _definition_summaries()

    async def _species_by_id(self, format_id: str) -> dict[str, SpeciesMetadata]:
        """Evolution is a layer on top of a working draft/battle flow, not a precondition
        for one: an unreachable species catalog degrades to "nothing evolves this attempt"
        rather than blocking a pick or a match result from being recorded."""
        try:
            entries = await self.species.entries(format_id)
        except RuntimeError:
            return {}
        return {item.id: item for item in entries}

    @staticmethod
    def auto_run_available(run: ChallengeRun) -> bool:
        interactive = {AgentType.HUMAN, AgentType.MANUAL}
        return (
            run.battle_controller.agent_type not in interactive
            and run.opponent_controller.agent_type not in interactive
        )

    @staticmethod
    def auto_advance_was_earned(run: ChallengeRun) -> bool:
        """A retry is always a deliberate user action; only victories continue a run."""
        if run.status is ChallengeStatus.READY:
            return True
        return bool(
            run.status is ChallengeStatus.STAGE_RESULT
            and run.stage_results
            and run.stage_results[-1].status == "won"
        )

    def _schedule_auto_run(self, run: ChallengeRun) -> None:
        if (
            not self.auto_run_available(run)
            or not self.auto_advance_was_earned(run)
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
                    message = f"Automatic progression paused: {error}"
                    await self.repository.save(
                        current.model_copy(
                            update={
                                "auto_run_paused": True,
                                "auto_advance_at": None,
                                "error": message[:1000],
                            }
                        ),
                        expected_revision=current.revision,
                    )

    @staticmethod
    def _candidates(
        metadata: tuple[SpeciesMetadata, ...],
        *,
        abilities_supported: bool,
        draft_points: DraftPointsSnapshot | None = None,
    ) -> tuple[tuple[DraftCandidate, ...], list[dict[str, str]]]:
        candidates: list[DraftCandidate] = []
        excluded: list[dict[str, str]] = []
        points_snapshot = draft_points or load_draft_points()
        species_by_id = {species.id: species for species in metadata}
        banned = set(points_snapshot.banned)

        def reachable_points(species_id: str, seen: frozenset[str] = frozenset()) -> int | None:
            if species_id in seen or species_id in banned:
                return None
            species = species_by_id.get(species_id)
            if species is None:
                return points_snapshot.points.get(species_id)
            next_seen = seen | {species_id}
            values = [
                value
                for option in species.evolves_to
                if (value := reachable_points(option.id, next_seen)) is not None
            ]
            own = points_snapshot.points.get(species_id)
            if own is not None:
                values.append(own)
            return max(values) if values else None

        def evolution_stage(species: SpeciesMetadata) -> int:
            stage = 0
            current = species
            seen: set[str] = set()
            while current.prevo_id and current.prevo_id not in seen:
                seen.add(current.id)
                previous = species_by_id.get(current.prevo_id)
                if previous is None:
                    break
                stage += 1
                current = previous
            return stage

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
            if species.showdown_set is None:
                excluded.append(
                    {
                        "species": species.name,
                        "state": "unavailable",
                        "reason": "pinned Showdown exposes no validator-legal set",
                    }
                )
                continue
            points = reachable_points(species.id)
            if points is None:
                excluded.append(
                    {
                        "species": species.name,
                        "state": "unpriced",
                        "reason": "no legal Smogon Gen 9 NatDex Draft Points path",
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
                    max_hp=species.max_hp,
                    abilities=species.abilities,
                    recommended_moves=species.recommended_moves,
                    required_item=species.required_item,
                    showdown_set=species.showdown_set,
                    evolves_to=species.evolves_to,
                    evolution_choices=_evolution_branches(species.id, species_by_id),
                    mega_evolutions=species.mega_evolutions,
                    evolution_stage=evolution_stage(species),
                    draft_points=points,
                    draft_rarity=rarity_for_candidate(points, species.base_stat_total),
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
        points_snapshot = load_draft_points()
        candidates, _ = self._candidates(
            species_snapshot.species,
            abilities_supported=species_snapshot.abilities_supported,
            draft_points=points_snapshot,
        )
        candidates = _eligible_draft_candidates(candidates, definition.draft_rules)
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
                draft_points_catalog_hash=points_snapshot.catalog_hash,
                draft_points_source=points_snapshot.source_name,
                draft_points_updated_on=points_snapshot.updated_on,
                candidates=candidates,
            ),
            draft_controller=payload.draft_controller,
            battle_controller=payload.battle_controller,
            opponent_controller=payload.opponent_controller,
            battle_experience=payload.battle_experience,
            difficulty=payload.difficulty,
            opponent_team_mode=payload.opponent_team_mode,
            battle_mode=payload.battle_mode,
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
                if run.status is ChallengeStatus.MEGA_SELECTION:
                    migrated = run.model_copy(
                        update={
                            "status": ChallengeStatus.STAGE_RESULT,
                            "mega_options": (),
                            "mega_selection": None,
                            "auto_advance_at": (
                                datetime.now(UTC)
                                if self.auto_run_available(run) and not run.auto_run_paused
                                else None
                            ),
                        }
                    )
                    run = await self.repository.save(
                        migrated, expected_revision=run.revision
                    )
                    reconciled.append(run.id)
                    self._schedule_auto_run(run)
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
                    and self.auto_advance_was_earned(run)
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
        archives: list[MatchArchive] = []
        if run.stage_results and self.battles is not None:
            for result in run.stage_results:
                archive = await self.battles.repository.get_match(result.match_id)
                if archive is not None:
                    archives.append(archive)
            if archives and archives[-1].status is MatchStatus.COMPLETED:
                summary = derive_battle_summary(archives[-1])
        return self.view(
            run,
            latest_battle_summary=summary,
            battle_overview=derive_battle_overview(run, tuple(archives)),
            pokemon_statistics=derive_pokemon_statistics(run, tuple(archives)),
        )

    async def continue_with_same_team(
        self, run_id: UUID, payload: ContinueChallengeRun
    ) -> ChallengeRunView:
        """Start another campaign route with the finalized roster snapshot unchanged."""
        source = await self.require(run_id)
        if source.status is not ChallengeStatus.COMPLETED:
            raise ValueError("a same-team continuation is available after a completed run")
        if source.team_snapshot_id is None:
            raise ValueError("the completed run has no finalized team snapshot")
        if not source.picks:
            raise ValueError("the completed run has no drafted roster to carry forward")
        definition = _definition(payload.definition_id)
        if definition.id == source.definition.id:
            raise ValueError("choose a different campaign route for the same-team continuation")
        if len(source.picks) != definition.draft_rules.roster_size:
            raise ValueError("the selected campaign does not support this roster size")
        now = datetime.now(UTC)
        seed_material = f"{source.id}:{source.seed}:{definition.id}".encode()
        seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "big")
        auto_advance_at = (
            now + timedelta(seconds=1)
            if self.auto_run_available(source) and not source.auto_run_paused
            else None
        )
        continuation = ChallengeRun(
            id=uuid4(),
            name=payload.name or f"{definition.region} Draft Gauntlet · Same Team",
            definition=definition,
            status=ChallengeStatus.READY,
            seed=seed,
            draft_rules_version=DRAFT_RULES_VERSION,
            draft_pool=source.draft_pool,
            draft_controller=source.draft_controller,
            draft_controller_history=source.draft_controller_history,
            battle_controller=source.battle_controller,
            opponent_controller=source.opponent_controller,
            battle_experience=source.battle_experience,
            difficulty=source.difficulty,
            opponent_team_mode=source.opponent_team_mode,
            battle_mode=source.battle_mode,
            rerolls_remaining=source.rerolls_remaining,
            type_rerolls_remaining=source.type_rerolls_remaining,
            generation_rerolls_remaining=source.generation_rerolls_remaining,
            consumed_species_ids=source.consumed_species_ids,
            draft_history=source.draft_history,
            picks=source.picks,
            ev_allocations=source.ev_allocations,
            ability_selections=source.ability_selections,
            team_snapshot_id=source.team_snapshot_id,
            auto_run_paused=source.auto_run_paused,
            auto_advance_at=auto_advance_at,
            created_at=now,
            updated_at=now,
            continued_from_run_id=source.id,
        )
        await self.repository.create(continuation)
        self._schedule_auto_run(continuation)
        return self.view(continuation)

    def view(
        self,
        run: ChallengeRun,
        *,
        latest_battle_summary: ChallengeBattleSummary | None = None,
        battle_overview: tuple[ChallengeBattleOverview, ...] = (),
        pokemon_statistics: tuple[ChallengePokemonStats, ...] = (),
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
        current_roster = tuple(
            CurrentPickView(
                entry_id=pick.candidate.entry_id,
                species=pick.current_species or pick.candidate.species,
                showdown_id=_current_species_id(pick),
                types=pick.current_types or pick.candidate.types,
                evolved=pick.current_species is not None,
                drafted_species=pick.candidate.species,
            )
            for pick in run.picks
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
            battle_overview=battle_overview,
            pokemon_statistics=pokemon_statistics,
            continuation_options=tuple(
                item for item in _definition_summaries() if item.id != run.definition.id
            ),
            team_export_scaffold=(
                _team_scaffold(run)
                if run.status
                in {
                    ChallengeStatus.PREPARING,
                    ChallengeStatus.TRAINING,
                    ChallengeStatus.TEAM_REVIEW,
                }
                else None
            ),
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
            current_roster=current_roster,
        )

    async def pick(
        self,
        run_id: UUID,
        entry_id: str,
        fingerprint: str,
        expected_revision: int,
        *,
        selected_by: DraftControllerKind | None = None,
        evolution_choice: str | None = None,
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
            species_by_id = (
                await self._species_by_id(run.definition.format)
                if candidate.evolves_to
                else {}
            )
            branches = candidate.evolution_choices or _evolution_branches(
                candidate.showdown_id, species_by_id
            )
            if branches:
                valid_ids = {option.id for option in branches}
                if evolution_choice in valid_ids:
                    resolved_choice = evolution_choice
                elif controller is DraftControllerKind.HUMAN:
                    names = ", ".join(f"{option.name} ({option.id})" for option in branches)
                    raise ValueError(
                        f"{candidate.species} can evolve multiple ways; include "
                        f"evolution_choice with one of: {names}"
                    )
                else:
                    # Automated drafting (Fast Auto's legacy Auto/AI path, deterministic
                    # Random) picks the first option in a stable, sorted order so the run
                    # never stalls waiting for a choice nobody will make.
                    resolved_choice = min(valid_ids)
            else:
                resolved_choice = None
            evolution_path = (
                _resolve_evolution_path(
                    candidate.showdown_id, resolved_choice, species_by_id
                )
                if candidate.evolves_to
                else (candidate.showdown_id,)
            )
            picks = (
                *run.picks,
                DraftPick(
                    round=len(run.picks) + 1,
                    offer_fingerprint=fingerprint,
                    candidate=candidate,
                    selected_by=controller,
                    evolution_path=evolution_path,
                ),
            )
            complete = len(picks) == run.definition.draft_rules.roster_size
            ability_selections = dict(run.ability_selections)
            ev_allocations = dict(run.ev_allocations)
            if complete:
                for pick in picks:
                    set_ability = (
                        showdown_id(pick.candidate.showdown_set.ability)
                        if pick.candidate.showdown_set
                        else None
                    )
                    legal_set_ability = next(
                        (
                            ability.id
                            for ability in pick.candidate.abilities
                            if ability.id == set_ability
                        ),
                        None,
                    )
                    ability_selections[pick.candidate.entry_id] = legal_set_ability or (
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
            format_id = (
                CAMPAIGN_DOUBLES_FORMAT
                if run.battle_mode == "doubles"
                else run.definition.format
            )
            try:
                validation = await self.battles.team_validator.validate(
                    submitted, format_id
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
                if self.auto_run_available(run)
                and not run.auto_run_paused
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
            history_outcome: Literal["pokemon_rerolled", "type_rerolled", "generation_rerolled"]
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
        key = (run_id, expected_revision)
        task = self._agent_tasks.get(key)
        if task is None:
            task = asyncio.create_task(
                self._agent_action_once(run_id, expected_revision),
                name=f"challenge-agent-draft-{run_id}-{expected_revision}",
            )
            self._agent_tasks[key] = task

            def forget(completed: asyncio.Task[ChallengeRun]) -> None:
                if not completed.cancelled():
                    completed.exception()
                if self._agent_tasks.get(key) is completed:
                    self._agent_tasks.pop(key, None)

            task.add_done_callback(forget)
        # A disconnected duplicate HTTP caller must not cancel the one shared provider charge.
        return await asyncio.shield(task)

    async def _agent_action_once(self, run_id: UUID, expected_revision: int) -> ChallengeRun:
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
            # No 256-token cap here. Reasoning models (DeepSeek V4 has thinking enabled by
            # default) spend their budget on hidden reasoning first, so a small cap returns
            # an empty completion and every AI draft decision failed as "invalid response".
            max_output_tokens=max(512, run.draft_controller.configuration.max_output_tokens),
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
                if not response.text.strip():
                    last_error = (
                        "agent draft provider returned no text; raise max output tokens for "
                        "reasoning models"
                    )
                else:
                    last_error = f"agent draft response is invalid: {error}"
                continue
            action = _resolve_draft_action(parsed.action, legal, run.current_offer)
            if action is None:
                last_error = (
                    f"agent selected {parsed.action!r}, which is not one of the legal actions"
                )
                continue
            parsed = parsed.model_copy(update={"action": action})
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
            format_id = (
                CAMPAIGN_DOUBLES_FORMAT
                if run.battle_mode == "doubles"
                else run.definition.format
            )
            validation = await self.battles.team_validator.validate(
                submitted_team, format_id
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
                "auto_advance_at": None,
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
            # Saved V1/V2 runs could carry a Random or provider opponent. Draft campaign
            # opponents are an invariant: every newly launched stage uses the same local,
            # switch-capable Tactical Fast Auto logic as the player preset.
            if run.opponent_controller.agent_type is not AgentType.TACTICAL_AUTO:
                run = await self.repository.save(
                    run.model_copy(
                        update={
                            "opponent_controller": BattleControllerSnapshot(
                                agent_type=AgentType.TACTICAL_AUTO,
                                configuration=run.opponent_controller.configuration,
                            )
                        }
                    ),
                    expected_revision=run.revision,
                )
            if run.team_snapshot_id is None or run.current_stage_index >= len(
                run.definition.stages
            ):
                raise ValueError("challenge has no launchable stage")
            source = await self.battles.teams.get(run.team_snapshot_id)
            if source is None:
                raise ValueError("finalized source team snapshot is missing")
            stage = run.definition.stages[run.current_stage_index]
            # V2 Quick Draft battles always start from the complete drafted roster. Older
            # saves can still carry the retired gauntlet casualty field, so clear it before
            # selecting exactly as many Pokemon as the opponent brings.
            if run.downed_entry_ids:
                run = await self.repository.save(
                    run.model_copy(update={"downed_entry_ids": ()}),
                    expected_revision=run.revision,
                )
            # Each attempt at a stage gets its own deterministic seed, so retrying a lost
            # stage is a genuine retry rather than a byte-identical rerun of the same loss.
            stage_attempts = sum(
                1 for item in run.stage_results if item.stage_index == run.current_stage_index
            )
            # The drafted roster snapshot stays immutable; only this derived export moves.
            # The player always follows the campaign's own level curve; difficulty never
            # lowers them below it, so evolution and levelling stay honest. Recommended sets
            # are validated at the campaign's lowest stage level during catalog generation
            # (Showdown's move-level legality is monotonic upward), so this should already be
            # legal; a hand-edited team_review export that is not surfaces as a real
            # validation error instead of silently changing the player's level.
            player_level = stage.level
            opponent_level = opponent_stage_level(stage.level, run.difficulty)
            species_by_id = await self._species_by_id(run.definition.format)
            available = _with_evolutions(source.normalized_export, run, species_by_id)
            opponent_team = _opponent_stage_team(stage, run.opponent_team_mode)
            opponent_team = _prepare_opponent_stage_team(opponent_team, species_by_id)
            if run.battle_mode == "doubles":
                opponent_team = _even_duo_opponent_team(
                    opponent_team, stage, run.definition.generation, species_by_id
                )
            team_size = len(_team_blocks(opponent_team))
            available = _automatic_stage_team(
                available,
                opponent_team,
                team_size,
                species_by_id,
                doubles=run.battle_mode == "doubles",
            )
            battle_format = (
                CAMPAIGN_DOUBLES_FORMAT
                if run.battle_mode == "doubles"
                else run.definition.format
            )
            minimum_levels = {
                showdown_id(species.id): species.minimum_level for species in species_by_id.values()
            }
            _, player_validation, _ = await _validated_player_stage_team(
                available,
                opponent_team,
                run,
                species_by_id,
                minimum_levels,
                player_level,
                battle_format,
                self.battles.team_validator,
            )
            opponent_team, opponent_validation = await _validated_opponent_stage_team(
                opponent_team,
                species_by_id,
                minimum_levels,
                opponent_level,
                battle_format,
                self.battles.team_validator,
                try_mega=run.current_stage_index >= MEGA_UNLOCK_STAGE_INDEX,
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
                name=f"{run.definition.name} · {stage.name} · level {opponent_level}",
                source=TeamSource.PRESET,
                submitted_text=opponent_validation.normalized_export or "",
                validation=opponent_validation,
            )
            config = MatchConfig(
                name=f"{run.name} · {stage.title} {stage.name}",
                campaign=CampaignBadge(
                    definition_name=run.definition.name,
                    stage_id=stage.id,
                    stage_name=stage.name,
                    stage_title=stage.title,
                    specialty=stage.specialty,
                    trainer_asset_id=stage.trainer_asset_id,
                    visual_accent=stage.visual_accent,
                    stage_index=run.current_stage_index,
                    stage_count=len(run.definition.stages),
                    difficulty=run.difficulty.value,
                    player_level=player_level,
                    opponent_level=opponent_level,
                ),
                format=battle_format,
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
            next_stage = (
                run.definition.stages[next_index]
                if next_index < len(run.definition.stages)
                else None
            )
            # Evolution is a state transition between stages, never mid-battle: it is
            # resolved here, exactly where the next stage is already being entered, and at
            # most once per pick per win.
            if won and next_stage is not None:
                species_by_id = await self._species_by_id(run.definition.format)
                picks, recent_evolutions = _advance_evolutions(
                    run, next_index, next_stage.level, species_by_id
                )
            else:
                picks, recent_evolutions = run.picks, ()
            # Mega Stones are selected afresh for every late-campaign matchup. Persisted
            # manual options remain readable on old saves but never pause a current run.
            mega_options: tuple[ChallengeMegaOption, ...] = ()
            mega_selection = None
            auto_advance_at = (
                datetime.now(UTC) + timedelta(seconds=AUTO_ADVANCE_DELAYS[run.battle_experience])
                if won
                and not completed
                and self.auto_run_available(run)
                and not run.auto_run_paused
                and run.battle_experience not in PRESENTATION_GATED_EXPERIENCES
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
                    "downed_entry_ids": (),
                    "picks": picks,
                    "recent_evolutions": recent_evolutions,
                    "mega_options": mega_options,
                    "mega_selection": mega_selection,
                    "completed_at": datetime.now(UTC) if completed else None,
                    "error": archive.error if outcome in {"failed", "interrupted"} else None,
                }
            )
            stored = await self.repository.save(updated, expected_revision=run.revision)
        self._schedule_auto_run(stored)

    async def select_mega(
        self,
        run_id: UUID,
        entry_id: str,
        mega_species_id: str,
        expected_revision: int,
    ) -> ChallengeRun:
        async with self.repository.lock(run_id):
            run = await self.require(run_id)
            if run.revision != expected_revision:
                raise ValueError(f"stale challenge revision: current {run.revision}")
            if run.status is not ChallengeStatus.MEGA_SELECTION:
                raise ValueError("challenge is not waiting for a Mega selection")
            option = next(
                (
                    item
                    for item in run.mega_options
                    if item.entry_id == entry_id and item.mega_species_id == mega_species_id
                ),
                None,
            )
            if option is None:
                raise ValueError("Mega selection is not one of the persisted legal options")
            selection = ChallengeMegaSelection(**option.model_dump())
            update: dict[str, object] = {
                "mega_selection": selection,
                "status": ChallengeStatus.STAGE_RESULT,
                "error": None,
            }
            if self.auto_run_available(run) and not run.auto_run_paused:
                update["auto_advance_at"] = datetime.now(UTC)
            stored = await self.repository.save(
                run.model_copy(update=update), expected_revision=run.revision
            )
        self._schedule_auto_run(stored)
        return stored

    async def auto_advance(self, run_id: UUID) -> tuple[ChallengeRun, MatchArchive | None]:
        """Launch after a Quick Sim deadline or a watched presentation acknowledgement."""
        run = await self.require(run_id)
        earned = self.auto_advance_was_earned(run)
        presentation_acknowledged = (
            run.battle_experience in PRESENTATION_GATED_EXPERIENCES
            and run.status is ChallengeStatus.STAGE_RESULT
            and earned
        )
        if (
            not self.auto_run_available(run)
            or not earned
            or run.auto_run_paused
            or (run.auto_advance_at is None and not presentation_acknowledged)
            or run.status not in {ChallengeStatus.READY, ChallengeStatus.STAGE_RESULT}
            or run.current_stage_index >= len(run.definition.stages)
        ):
            match = (
                await self.battles.repository.get_match(run.active_match_id)
                if run.active_match_id is not None
                else None
            )
            return run, match
        if run.auto_advance_at is not None and run.auto_advance_at > datetime.now(UTC):
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
            launchable = self.auto_advance_was_earned(run)
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
