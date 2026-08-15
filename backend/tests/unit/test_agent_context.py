from __future__ import annotations

import json

from koalabattle.agents.context import render_agent_prompt
from koalabattle.core.models import (
    BattleAction,
    BattleSide,
    BattleState,
    ContextProfileId,
    MemoryPolicyId,
    MoveState,
    PokemonState,
    PromptProfileId,
    Side,
)
from koalabattle.engines.showdown.context import PokemonShowdownContextProvider


def test_revealed_knowledge_persists_without_inventing_hidden_fields(
    state: BattleState, actions: tuple[BattleAction, ...]
) -> None:
    provider = PokemonShowdownContextProvider()
    revealed = state.opponent.team[0].model_copy(
        update={
            "moves": (MoveState(id="bodyslam", name="Body Slam"),),
            "item": "leftovers",
            "ability": None,
        }
    )
    first = state.model_copy(
        update={
            "opponent": BattleSide(
                side=Side.P2,
                display_name="Beta",
                active=revealed,
                team=(revealed,),
            )
        }
    )
    knowledge, _, _, _ = provider.build(
        first,
        actions,
        prompt_profile=PromptProfileId.STANDARD_COMPETITIVE,
        context_profile=ContextProfileId.STANDARD,
        memory_policy=MemoryPolicyId.STRATEGY_NOTE,
        strategy_memory=None,
    )
    replacement = PokemonState(
        id="p2:2",
        name="Corviknight",
        species="Corviknight",
        hp_fraction=1,
        active=True,
    )
    second = first.model_copy(
        update={
            "turn": 20,
            "opponent": BattleSide(
                side=Side.P2,
                display_name="Beta",
                active=replacement,
                team=(replacement,),
            ),
        }
    )
    knowledge, snapshot, prompt, _ = provider.build(
        second,
        actions,
        prompt_profile=PromptProfileId.STANDARD_COMPETITIVE,
        context_profile=ContextProfileId.STANDARD,
        memory_policy=MemoryPolicyId.STRATEGY_NOTE,
        strategy_memory="Keep the endgame cleaner healthy.",
    )
    snorlax = next(item for item in knowledge.known_opponent if item.species == "Snorlax")
    assert [move.id for move in snorlax.revealed_moves] == ["bodyslam"]
    assert snorlax.revealed_item == "leftovers"
    assert snorlax.revealed_ability is None
    assert {item.species for item in knowledge.known_opponent} == {"Snorlax", "Corviknight"}
    assert "Mewtwo" not in prompt
    assert snapshot.strategy_memory == "Keep the endgame cleaner healthy."


def test_context_budget_never_removes_current_state_or_legal_actions(
    state: BattleState, actions: tuple[BattleAction, ...]
) -> None:
    moves = tuple(
        MoveState(
            id=f"move-{index}",
            name=f"Competitive Move {index}",
            type="electric",
            power=90,
            accuracy=1,
            current_pp=16,
            max_pp=16,
        )
        for index in range(4)
    )
    own_team = tuple(
        state.player.team[0].model_copy(
            update={
                "id": f"p1:{index}",
                "name": f"Pikachu {index}",
                "active": index == 0,
                "moves": moves,
            }
        )
        for index in range(6)
    )
    opponent_team = tuple(
        state.opponent.team[0].model_copy(
            update={
                "id": f"p2:{index}",
                "name": f"Snorlax {index}",
                "active": index == 0,
                "moves": moves,
                "item": "leftovers",
                "ability": "thickfat",
            }
        )
        for index in range(6)
    )
    noisy = state.model_copy(
        update={
            "player": state.player.model_copy(update={"active": own_team[0], "team": own_team}),
            "opponent": state.opponent.model_copy(
                update={"active": opponent_team[0], "team": opponent_team}
            ),
            "public_history": tuple(
                f"|move|p2a: Opponent|Move {index}|p1a: Player" for index in range(500)
            ),
        }
    )
    _, snapshot, _, _ = PokemonShowdownContextProvider().build(
        noisy,
        actions,
        prompt_profile=PromptProfileId.BENCHMARK_FAIR,
        context_profile=ContextProfileId.COMPACT,
        memory_policy=MemoryPolicyId.DISABLED,
        strategy_memory="must be ignored",
    )
    prompt, metrics = render_agent_prompt(snapshot)
    payload = json.loads(prompt)
    assert payload["context"]["knowledge"]["own_side"]["active"]["species"] == "Pikachu"
    assert [item["id"] for item in payload["legal_actions"]] == [item.id for item in actions]
    assert metrics.estimated_tokens <= 2_400
    assert metrics.history_event_count <= 5
    assert snapshot.strategy_memory is None


def test_context_is_deterministic_and_tracks_public_battle_changes(
    state: BattleState, actions: tuple[BattleAction, ...]
) -> None:
    provider = PokemonShowdownContextProvider()
    changed = state.model_copy(
        update={
            "turn": 12,
            "weather": ("rain",),
            "fields": ("electricterrain",),
            "player": state.player.model_copy(
                update={
                    "side_conditions": ("stealthrock",),
                    "active": state.player.active.model_copy(  # type: ignore[union-attr]
                        update={"hp_fraction": 0.4, "status": "brn", "boosts": {"atk": 2}}
                    ),
                }
            ),
            "opponent": state.opponent.model_copy(
                update={
                    "active": state.opponent.active.model_copy(  # type: ignore[union-attr]
                        update={"fainted": True, "hp_fraction": 0.0}
                    ),
                    "team": (
                        state.opponent.team[0].model_copy(
                            update={"fainted": True, "hp_fraction": 0.0}
                        ),
                    ),
                }
            ),
        }
    )
    first = provider.build(
        changed,
        actions,
        prompt_profile=PromptProfileId.BENCHMARK_FAIR,
        context_profile=ContextProfileId.STANDARD,
        memory_policy=MemoryPolicyId.STRATEGY_NOTE,
        strategy_memory="Use the replacement line.",
    )
    second = PokemonShowdownContextProvider().build(
        changed,
        actions,
        prompt_profile=PromptProfileId.BENCHMARK_FAIR,
        context_profile=ContextProfileId.STANDARD,
        memory_policy=MemoryPolicyId.STRATEGY_NOTE,
        strategy_memory="Use the replacement line.",
    )
    assert first[2] == second[2]
    knowledge, snapshot, _, metrics = first
    assert knowledge.weather == ("rain",)
    assert knowledge.fields == ("electricterrain",)
    assert knowledge.own_side.side_conditions == ("stealthrock",)
    assert knowledge.own_side.active is not None
    assert knowledge.own_side.active.status == "brn"
    assert knowledge.known_opponent[0].fainted
    assert snapshot.strategy_memory == "Use the replacement line."
    assert metrics.context_profile_version == snapshot.context_profile_version
