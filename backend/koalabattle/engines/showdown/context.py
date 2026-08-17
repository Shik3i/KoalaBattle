from __future__ import annotations

from typing import Protocol

from koalabattle.agents.context import (
    CONTEXT_PROFILES,
    OUTPUT_SCHEMA_VERSION,
    PROMPT_PROFILES,
    render_prompt_messages,
)
from koalabattle.agents.prompt_renderer import RenderedPrompt
from koalabattle.core.models import (
    AgentContextSnapshot,
    BattleAction,
    BattleState,
    ContextMetrics,
    ContextProfileId,
    KnownPokemon,
    MemoryPolicyId,
    PlayerKnowledgeState,
    PokemonState,
    PromptProfileId,
)
from koalabattle.formats import FormatMechanics, describe_format

KNOWLEDGE_SCHEMA_VERSION = "1.0"
CONTEXT_SCHEMA_VERSION = "1.0"
HISTORY_POLICY_VERSION = "relevant-v1"
MEMORY_POLICY_VERSION = "1.0"


class AgentContextProvider(Protocol):
    def build(
        self,
        state: BattleState,
        legal_actions: tuple[BattleAction, ...],
        *,
        prompt_profile: PromptProfileId,
        context_profile: ContextProfileId,
        memory_policy: MemoryPolicyId,
        strategy_memory: str | None,
        maximum_turns: int | None = None,
    ) -> tuple[PlayerKnowledgeState, AgentContextSnapshot, RenderedPrompt, ContextMetrics]: ...


class PlayerKnowledgeReducer:
    """Deterministically merge only player-visible state into persistent knowledge."""

    def reduce(
        self,
        previous: PlayerKnowledgeState | None,
        state: BattleState,
    ) -> PlayerKnowledgeState:
        known = {item.id: item for item in previous.known_opponent} if previous else {}
        for pokemon in state.opponent.team:
            visible = _known_pokemon(pokemon)
            prior = known.get(visible.id)
            known[visible.id] = _merge_known(prior, visible)
        active = None
        if state.opponent.active is not None:
            active = known.get(state.opponent.active.id) or _known_pokemon(state.opponent.active)
            active = active.model_copy(update={"active": True})
            known[active.id] = active
        normalized = tuple(
            item.model_copy(update={"active": active is not None and item.id == active.id})
            for item in sorted(known.values(), key=lambda value: value.id)
        )
        return PlayerKnowledgeState(
            match_id=state.match_id,
            side=state.perspective,
            turn=state.turn,
            own_side=state.player,
            opponent_active=active,
            known_opponent=normalized,
            opponent_side_conditions=state.opponent.side_conditions,
            weather=state.weather,
            fields=state.fields,
        )


class PokemonShowdownContextProvider:
    def __init__(self) -> None:
        self.reducer = PlayerKnowledgeReducer()
        self._knowledge: PlayerKnowledgeState | None = None

    def build(
        self,
        state: BattleState,
        legal_actions: tuple[BattleAction, ...],
        *,
        prompt_profile: PromptProfileId,
        context_profile: ContextProfileId,
        memory_policy: MemoryPolicyId,
        strategy_memory: str | None,
        maximum_turns: int | None = None,
    ) -> tuple[PlayerKnowledgeState, AgentContextSnapshot, RenderedPrompt, ContextMetrics]:
        knowledge = self.reducer.reduce(self._knowledge, state)
        self._knowledge = knowledge
        profile = PROMPT_PROFILES[prompt_profile]
        context = CONTEXT_PROFILES[context_profile]
        recent_events = _relevant_history(state.public_history, context.maximum_history_events)
        descriptor = describe_format(state.format)
        snapshot = AgentContextSnapshot(
            match_id=state.match_id,
            format=state.format,
            format_name=descriptor.name if descriptor else state.format,
            game_type=descriptor.game_type if descriptor else "singles",
            mechanics=descriptor.mechanics if descriptor else FormatMechanics(),
            generation=state.generation,
            turn=state.turn,
            maximum_turns=maximum_turns,
            side=state.perspective,
            knowledge=knowledge,
            recent_events=recent_events,
            strategy_memory=(
                strategy_memory if memory_policy is MemoryPolicyId.STRATEGY_NOTE else None
            ),
            legal_actions=legal_actions,
            prompt_profile_id=prompt_profile,
            prompt_profile_version=profile.version,
            context_profile_id=context_profile,
            context_profile_version=context.version,
            history_policy_version=HISTORY_POLICY_VERSION,
            memory_policy=memory_policy,
            memory_policy_version=MEMORY_POLICY_VERSION,
            output_schema_version=OUTPUT_SCHEMA_VERSION,
        )
        prompt, metrics = render_prompt_messages(snapshot)
        return knowledge, snapshot, prompt, metrics


def _known_pokemon(pokemon: PokemonState) -> KnownPokemon:
    return KnownPokemon(
        id=pokemon.id,
        species=pokemon.species,
        display_name=pokemon.name,
        hp_fraction=pokemon.hp_fraction,
        status=pokemon.status,
        active=pokemon.active,
        fainted=pokemon.fainted,
        revealed_moves=pokemon.moves,
        revealed_item=pokemon.item,
        revealed_ability=pokemon.ability,
        revealed_tera_type=pokemon.tera_type if pokemon.terastallized else None,
        types=pokemon.types,
    )


def _merge_known(previous: KnownPokemon | None, current: KnownPokemon) -> KnownPokemon:
    if previous is None:
        return current
    moves = {move.id: move for move in previous.revealed_moves}
    moves.update({move.id: move for move in current.revealed_moves})
    return current.model_copy(
        update={
            "revealed_moves": tuple(moves[key] for key in sorted(moves)),
            "revealed_item": current.revealed_item or previous.revealed_item,
            "revealed_ability": current.revealed_ability or previous.revealed_ability,
            "revealed_tera_type": current.revealed_tera_type or previous.revealed_tera_type,
            "types": current.types or previous.types,
        }
    )


def _relevant_history(history: tuple[str, ...], maximum: int) -> tuple[str, ...]:
    commands = {
        "switch",
        "drag",
        "move",
        "-item",
        "-enditem",
        "-ability",
        "-status",
        "-curestatus",
        "-weather",
        "-sidestart",
        "-sideend",
        "-terastallize",
        "faint",
    }
    selected: list[str] = []
    for entry in history:
        parts = entry.split("|")
        if len(parts) > 1 and parts[1] in commands:
            selected.append(entry)
    return tuple(selected[-maximum:])
