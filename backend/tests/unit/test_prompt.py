from __future__ import annotations

import json
from uuid import uuid4

from koalabattle.agents.context import render_prompt_messages
from koalabattle.agents.prompt_renderer import humanize_event, render
from koalabattle.agents.validation import parse_structured_decision, trim_commentary
from koalabattle.core.models import (
    MAX_COMMENTARY_CHARACTERS,
    ActionType,
    AgentContextSnapshot,
    AgentRequest,
    BattleAction,
    BattleSide,
    ContextProfileId,
    KnownPokemon,
    MemoryPolicyId,
    MoveState,
    PlayerKnowledgeState,
    PokemonState,
    PromptProfileId,
    Side,
)
from koalabattle.formats import describe_format


def _snapshot(format_id: str) -> AgentContextSnapshot:
    descriptor = describe_format(format_id)
    assert descriptor is not None
    match_id = uuid4()
    tauros = PokemonState(
        id="p1: Tauros",
        name="Tauros",
        species="Tauros",
        level=100,
        current_hp=353,
        max_hp=353,
        hp_fraction=1.0,
        types=("normal",),
        item="leftovers",
        ability="intimidate",
        tera_type="fire",
        active=True,
        moves=(
            MoveState(
                id="bodyslam",
                name="Body Slam",
                type="normal",
                category="physical",
                power=85,
                accuracy=100,
                current_pp=24,
                max_pp=24,
            ),
        ),
    )
    chansey = PokemonState(
        id="p1: Chansey",
        name="Chansey",
        species="Chansey",
        level=100,
        hp_fraction=0.8,
        types=("normal",),
        moves=(
            MoveState(
                id="softboiled",
                name="Soft-Boiled",
                type="normal",
                category="status",
                power=0,
                accuracy=100,
                current_pp=16,
                max_pp=16,
            ),
        ),
    )
    knowledge = PlayerKnowledgeState(
        match_id=match_id,
        side=Side.P1,
        turn=3,
        own_side=BattleSide(
            side=Side.P1,
            display_name="Gemini",
            active=tauros,
            team=(tauros, chansey),
        ),
        opponent_active=KnownPokemon(
            id="p2: Alakazam",
            species="Alakazam",
            display_name="Alakazam",
            hp_fraction=1.0,
            types=("psychic",),
        ),
    )
    return AgentContextSnapshot(
        match_id=match_id,
        format=descriptor.id,
        format_name=descriptor.name,
        game_type=descriptor.game_type,
        mechanics=descriptor.mechanics,
        generation=descriptor.generation,
        turn=3,
        side=Side.P1,
        knowledge=knowledge,
        recent_events=("|move|p2a: Alakazam|Psychic|p1a: Tauros",),
        legal_actions=(
            BattleAction(
                id="move:1",
                type=ActionType.MOVE,
                name="Body Slam",
                slot=1,
                move_type="normal",
                category="physical",
                power=85,
                accuracy=100,
                current_pp=24,
                max_pp=24,
            ),
            BattleAction(
                id="switch:1",
                type=ActionType.SWITCH,
                name="Chansey",
                slot=1,
                species="Chansey",
                hp_fraction=0.8,
            ),
        ),
        prompt_profile_id=PromptProfileId.BENCHMARK_FAIR,
        prompt_profile_version="2.0",
        context_profile_id=ContextProfileId.STANDARD,
        context_profile_version="2.0",
        history_policy_version="relevant-v1",
        memory_policy=MemoryPolicyId.STRATEGY_NOTE,
        memory_policy_version="1.0",
        output_schema_version="battle-decision-v2",
    )


def test_manual_prompt_is_self_contained_for_a_fresh_chat(agent_request: AgentRequest) -> None:
    prompt = agent_request.prompt
    for heading in (
        "FORMAT",
        "TURN",
        "OBJECTIVE",
        "YOUR ACTIVE POKEMON",
        "YOUR BENCH",
        "OPPONENT ACTIVE",
        "KNOWN OPPONENT TEAM",
        "FIELD",
        "RECENT EVENTS",
        "LEGAL ACTIONS",
        "RETURN EXACTLY",
    ):
        assert heading in prompt
    assert "Player 1" in prompt
    assert "poke_env" not in prompt
    assert "chain-of-thought" not in prompt
    # The rules must sit at the top, not below thousands of tokens of state.
    assert prompt.index("RULES") < prompt.index("YOUR ACTIVE POKEMON")


def test_api_prompt_splits_stable_rules_from_battle_state(agent_request: AgentRequest) -> None:
    assert agent_request.system_prompt is not None
    assert agent_request.user_prompt is not None
    assert "RETURN EXACTLY" in agent_request.system_prompt
    assert "\nLEGAL ACTIONS\n" in agent_request.user_prompt
    assert "\nLEGAL ACTIONS\n" not in agent_request.system_prompt
    assert "YOUR ACTIVE POKEMON" not in agent_request.system_prompt
    assert agent_request.prompt.endswith(agent_request.user_prompt)


def test_gen1_prompt_omits_mechanics_that_do_not_exist() -> None:
    prompt = render(_snapshot("gen1ou")).combined
    absent_fields = (
        "Ability:",
        "Item:",
        "Tera type:",
        "Terastallize",
        "Known ability",
        "Known item",
    )
    for absent in absent_fields:
        assert absent not in prompt, absent
    assert "Generation 1" in prompt
    assert "no abilities and no held items" in prompt
    assert "Damage class is decided by the move's type" in prompt
    # Gen 1 has no physical/special split, so no per-move damage class is claimed.
    assert "Normal · 85 BP · 100% · 24/24 PP" in prompt
    assert "Physical" not in prompt
    assert "Tauros" in prompt


def test_gen9_prompt_keeps_modern_mechanics() -> None:
    prompt = render(_snapshot("gen9ou")).combined
    # Display names come from the Showdown dex, not from title-casing the raw ID.
    assert "Ability: Intimidate" in prompt
    assert "Item: Leftovers" in prompt
    assert "Tera type: Fire (available)" in prompt
    assert "Available mechanics: Terastallization" in prompt


def test_prompt_carries_full_bench_move_information() -> None:
    prompt = render(_snapshot("gen9ou")).combined
    bench = prompt.split("YOUR BENCH", 1)[1].split("OPPONENT ACTIVE", 1)[0]
    assert "Chansey" in bench
    assert "Soft-Boiled" in bench
    assert "Normal · Status · 100% · 16/16 PP" in bench


def test_legal_actions_are_self_describing_with_display_names() -> None:
    prompt = render(_snapshot("gen9ou")).combined
    actions = prompt.split("LEGAL ACTIONS", 1)[1]
    assert "move:1\n  Body Slam · Normal · Physical · 85 BP · 100% · 24/24 PP" in actions
    assert "switch:1\n  Switch to Chansey · 80%" in actions


def test_unknown_opponent_data_is_rendered_as_unknown_not_as_a_fake_value() -> None:
    prompt = render(_snapshot("gen9ou")).combined
    opponent = prompt.split("OPPONENT ACTIVE", 1)[1].split("KNOWN OPPONENT TEAM", 1)[0]
    assert "Known ability: unknown" in opponent
    assert "Known item: unknown" in opponent
    assert "unknown_item" not in prompt
    assert "Known moves: none revealed" in opponent


def test_hidden_information_policy_allows_prediction_but_not_invention() -> None:
    prompt = render(_snapshot("gen9ou")).combined
    assert "probabilistic strategic predictions" in prompt
    assert "never" in prompt and "as known fact" in prompt
    assert "Do not infer hidden state" not in prompt
    assert "Use only information in this prompt" not in prompt


def test_recent_events_are_humanized_rather_than_raw_protocol() -> None:
    prompt = render(_snapshot("gen9ou")).combined
    assert "Opposing Alakazam used Psychic." in prompt
    assert "|move|" not in prompt


def test_humanize_event_covers_the_common_protocol_commands() -> None:
    assert humanize_event("|faint|p1a: Tauros") == "Your Tauros fainted."
    assert humanize_event("|-status|p2a: Alakazam|par") == "Opposing Alakazam is now paralyzed."
    assert humanize_event("|-weather|RainDance") == "Weather: Raindance."
    assert humanize_event("|unhandled|thing") is None


def test_prompt_requests_short_commentary_and_private_memory() -> None:
    prompt = render(_snapshot("gen9ou")).combined
    assert f"max {MAX_COMMENTARY_CHARACTERS} characters" in prompt
    assert "Strategy memory is private" in prompt


def test_commentary_is_trimmed_rather_than_rejected() -> None:
    long_text = "Attacking because " + ("it is a very good idea " * 40)
    trimmed = trim_commentary(long_text)
    assert len(trimmed) <= MAX_COMMENTARY_CHARACTERS
    assert trimmed.endswith("…")
    parsed = parse_structured_decision(
        json.dumps({"action": "move:1", "commentary": long_text}), {"move:1"}
    )
    assert len(parsed.commentary) <= MAX_COMMENTARY_CHARACTERS


def test_both_prompt_profiles_state_identical_rules_for_a_fair_benchmark() -> None:
    standard = _snapshot("gen9ou").model_copy(
        update={"prompt_profile_id": PromptProfileId.STANDARD_COMPETITIVE}
    )
    fair = _snapshot("gen9ou").model_copy(
        update={"prompt_profile_id": PromptProfileId.BENCHMARK_FAIR}
    )
    assert render(standard).system == render(fair).system


def test_rendered_prompt_reports_deterministic_metrics(agent_request: AgentRequest) -> None:
    assert agent_request.context is not None
    first, metrics = render_prompt_messages(agent_request.context)
    second, _ = render_prompt_messages(agent_request.context)
    assert first == second
    assert metrics.rendered_characters == len(first.combined)
    assert metrics.estimated_tokens > 0


def test_ability_and_item_ids_are_rendered_as_display_names() -> None:
    prompt = render(
        _snapshot("gen9ou").model_copy(
            update={
                "knowledge": _snapshot("gen9ou").knowledge.model_copy(
                    update={
                        "own_side": _snapshot("gen9ou").knowledge.own_side.model_copy(
                            update={
                                "active": _snapshot("gen9ou").knowledge.own_side.active.model_copy(  # type: ignore[union-attr]
                                    update={"ability": "ironfist", "item": "heavydutyboots"}
                                )
                            }
                        )
                    }
                )
            }
        )
    ).combined
    assert "Ability: Iron Fist" in prompt
    assert "Item: Heavy-Duty Boots" in prompt
    assert "Ironfist" not in prompt
    assert "Heavydutyboots" not in prompt


def test_variable_power_moves_are_not_reported_as_powerless() -> None:
    snapshot = _snapshot("gen9ou")
    active = snapshot.knowledge.own_side.active
    assert active is not None
    grass_knot = MoveState(
        id="grassknot",
        name="Grass Knot",
        type="grass",
        category="special",
        power=0,
        accuracy=100,
        current_pp=32,
        max_pp=32,
    )
    updated = snapshot.model_copy(
        update={
            "knowledge": snapshot.knowledge.model_copy(
                update={
                    "own_side": snapshot.knowledge.own_side.model_copy(
                        update={"active": active.model_copy(update={"moves": (grass_knot,)})}
                    )
                }
            )
        }
    )
    prompt = render(updated).combined
    assert "Grass · Special · variable BP · 100% · 32/32 PP" in prompt
    assert "no base power" not in prompt


def test_mechanics_without_an_action_are_not_advertised_as_available() -> None:
    """Gen 6-8 have Mega Evolution, Z-Moves and Dynamax; KoalaBattle issues none of them."""
    # Formats chosen because their rule table actually permits the mechanic; gen8ou bans
    # Dynamax outright, so it would prove nothing here.
    for format_id, label in (
        ("gen6ou", "Mega Evolution"),
        ("gen7anythinggoes", "Z-Moves"),
        ("gen8anythinggoes", "Dynamax"),
    ):
        snapshot = _snapshot(format_id)
        prompt = render(snapshot).combined
        available = [
            line for line in prompt.splitlines() if line.startswith("Available mechanics:")
        ]
        assert all(label not in line for line in available), f"{format_id} advertises {label}"
        # The opponent can still use it, so the prompt says so instead of staying silent.
        assert label in prompt
        assert "KoalaBattle cannot select it" in prompt


def test_terastallization_is_advertised_because_an_action_carries_it() -> None:
    prompt = render(_snapshot("gen9ou")).combined
    assert "Available mechanics: Terastallization" in prompt
    assert "KoalaBattle cannot select it" not in prompt
