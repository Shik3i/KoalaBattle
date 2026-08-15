from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast, overload

from koalabattle.core.models import (
    AgentContextSnapshot,
    ContextMetrics,
    ContextProfileId,
    PromptProfileId,
)

PROMPT_SCHEMA_VERSION = "5.0"
OUTPUT_SCHEMA_VERSION = "battle-decision-v2"


@dataclass(frozen=True)
class PromptProfile:
    id: PromptProfileId
    name: str
    version: str
    system_policy: str


@dataclass(frozen=True)
class ContextProfile:
    id: ContextProfileId
    version: str
    estimated_token_budget: int
    maximum_history_events: int


PROMPT_PROFILES = {
    PromptProfileId.STANDARD_COMPETITIVE: PromptProfile(
        id=PromptProfileId.STANDARD_COMPETITIVE,
        name="Standard Competitive",
        version="1.0",
        system_policy=(
            "Act as the assigned player and try to win. Use only supplied information; "
            "unknown opponent information must remain unknown. Choose exactly one supplied "
            "legal action ID. Return concise public commentary, not hidden reasoning."
        ),
    ),
    PromptProfileId.BENCHMARK_FAIR: PromptProfile(
        id=PromptProfileId.BENCHMARK_FAIR,
        name="Benchmark Fair",
        version="1.0",
        system_policy=(
            "Act as the assigned player and try to win. Use only the player-specific snapshot. "
            "Do not infer hidden state. Choose exactly one supplied legal action ID. Return "
            "concise public commentary, not hidden reasoning."
        ),
    ),
}

CONTEXT_PROFILES = {
    ContextProfileId.STANDARD: ContextProfile(
        id=ContextProfileId.STANDARD,
        version="1.0",
        estimated_token_budget=4_000,
        maximum_history_events=10,
    ),
    ContextProfileId.COMPACT: ContextProfile(
        id=ContextProfileId.COMPACT,
        version="1.0",
        estimated_token_budget=2_400,
        maximum_history_events=5,
    ),
}


def render_agent_prompt(snapshot: AgentContextSnapshot) -> tuple[str, ContextMetrics]:
    """Render one provider-independent, stateless prompt and deterministic size metrics."""
    profile = PROMPT_PROFILES[snapshot.prompt_profile_id]
    context_profile = CONTEXT_PROFILES[snapshot.context_profile_id]
    history = list(snapshot.recent_events[-context_profile.maximum_history_events :])
    context_data = snapshot.model_dump(mode="json", exclude={"recent_events", "legal_actions"})

    def payload() -> dict[str, object]:
        return {
            "prompt_schema_version": PROMPT_SCHEMA_VERSION,
            "prompt_profile": {
                "id": profile.id.value,
                "name": profile.name,
                "version": profile.version,
            },
            "system_policy": profile.system_policy,
            "game_instructions": (
                "Pokemon Showdown supplies the legal actions. Never construct a raw Showdown "
                "command and never invent unrevealed opponent data."
            ),
            "context": {
                **context_data,
                "recent_events": history,
            },
            "legal_actions": [item.model_dump(mode="json") for item in snapshot.legal_actions],
            "response_schema": {
                "action": "one exact id from legal_actions",
                "commentary": "public explanation, maximum 1000 characters",
                "strategy_memory": (
                    "replacement strategy note, maximum 400 characters, or null"
                    if snapshot.memory_policy.value == "strategy-note"
                    else "null"
                ),
            },
            "rules": [
                "Return one JSON object and no markdown.",
                "Use only information in this prompt.",
                "Unknown means unknown.",
            ],
        }

    rendered = json.dumps(payload(), indent=2, sort_keys=True)
    while history and estimate_tokens(rendered) > context_profile.estimated_token_budget:
        history.pop(0)
        rendered = json.dumps(payload(), indent=2, sort_keys=True)

    if estimate_tokens(rendered) > context_profile.estimated_token_budget:
        context_data = _budgeted_context(context_data, minimal=False)
        rendered = json.dumps(payload(), indent=2, sort_keys=True)

    if estimate_tokens(rendered) > context_profile.estimated_token_budget:
        context_data = _budgeted_context(context_data, minimal=True)
        rendered = json.dumps(payload(), indent=2, sort_keys=True)

    metrics = ContextMetrics(
        rendered_characters=len(rendered),
        estimated_tokens=estimate_tokens(rendered),
        history_event_count=len(history),
        knowledge_entries=len(snapshot.knowledge.known_opponent),
        context_profile_version=snapshot.context_profile_version,
        history_policy_version=snapshot.history_policy_version,
    )
    return rendered, metrics


def estimate_tokens(value: str) -> int:
    return (len(value) + 3) // 4


def _budgeted_context(context: dict[str, Any], *, minimal: bool) -> dict[str, Any]:
    """Compact duplicated bench detail while retaining active state and legal choices."""
    result = deepcopy(context)
    knowledge = result.get("knowledge")
    if not isinstance(knowledge, dict):
        return result

    own_side = knowledge.get("own_side")
    if isinstance(own_side, dict):
        active = own_side.get("active")
        active_id = active.get("id") if isinstance(active, dict) else None
        if isinstance(active, dict):
            own_side["active"] = _pokemon_prompt_view(active, include_moves=True, minimal=minimal)
        team = own_side.get("team")
        if isinstance(team, list):
            own_side["team"] = [
                _pokemon_prompt_view(item, include_moves=False, minimal=minimal)
                for item in team
                if isinstance(item, dict) and item.get("id") != active_id
            ]

    opponent_active = knowledge.get("opponent_active")
    opponent_active_id = opponent_active.get("id") if isinstance(opponent_active, dict) else None
    if isinstance(opponent_active, dict):
        knowledge["opponent_active"] = _known_pokemon_prompt_view(
            opponent_active, include_moves=True, minimal=minimal
        )
    known_opponent = knowledge.get("known_opponent")
    if isinstance(known_opponent, list):
        knowledge["known_opponent"] = [
            _known_pokemon_prompt_view(item, include_moves=not minimal, minimal=minimal)
            for item in known_opponent
            if isinstance(item, dict) and item.get("id") != opponent_active_id
        ]

    return cast(dict[str, Any], _without_prompt_noise(result))


def _pokemon_prompt_view(
    pokemon: dict[str, Any], *, include_moves: bool, minimal: bool
) -> dict[str, Any]:
    keys = [
        "id",
        "species",
        "current_hp",
        "max_hp",
        "hp_fraction",
        "status",
        "types",
        "item",
        "ability",
        "tera_type",
        "terastallized",
        "boosts",
        "effects",
        "active",
        "fainted",
    ]
    if not minimal:
        keys[1:1] = ["name", "level"]
    result = {key: pokemon.get(key) for key in keys}
    if include_moves:
        moves = pokemon.get("moves")
        if isinstance(moves, list):
            result["moves"] = [_move_prompt_view(move) for move in moves if isinstance(move, dict)]
    return cast(dict[str, Any], _without_prompt_noise(result))


def _known_pokemon_prompt_view(
    pokemon: dict[str, Any], *, include_moves: bool, minimal: bool
) -> dict[str, Any]:
    keys = [
        "id",
        "species",
        "hp_fraction",
        "status",
        "active",
        "fainted",
        "revealed_item",
        "revealed_ability",
        "revealed_tera_type",
        "types",
    ]
    if not minimal:
        keys.insert(2, "display_name")
    result = {key: pokemon.get(key) for key in keys}
    moves = pokemon.get("revealed_moves")
    if isinstance(moves, list):
        if include_moves:
            result["revealed_moves"] = [
                _move_prompt_view(move, include_name=not minimal)
                for move in moves
                if isinstance(move, dict)
            ]
        elif minimal:
            result["revealed_move_ids"] = [
                move.get("id") for move in moves if isinstance(move, dict) and move.get("id")
            ]
    return cast(dict[str, Any], _without_prompt_noise(result))


def _move_prompt_view(move: dict[str, Any], *, include_name: bool = True) -> dict[str, Any]:
    keys = ["id", "type", "power", "accuracy", "current_pp", "max_pp", "disabled"]
    if include_name:
        keys.insert(1, "name")
    return cast(dict[str, Any], _without_prompt_noise({key: move.get(key) for key in keys}))


@overload
def _without_prompt_noise(value: dict[str, Any]) -> dict[str, Any]: ...


@overload
def _without_prompt_noise(value: list[Any]) -> list[Any]: ...


@overload
def _without_prompt_noise(value: Any) -> Any: ...


def _without_prompt_noise(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_prompt_noise(item)
            for key, item in value.items()
            if key != "schema_version" and item is not None and item not in ([], {}, ())
        }
    if isinstance(value, list):
        return [_without_prompt_noise(item) for item in value]
    return value
