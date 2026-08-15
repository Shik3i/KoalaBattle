from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from uuid import UUID

from koalabattle.core.models import (
    ActionType,
    BattleAction,
    BattleResult,
    BattleSide,
    BattleState,
    MoveState,
    PokemonState,
    Side,
)

if TYPE_CHECKING:
    from poke_env.battle import AbstractBattle, Move, Pokemon
    from poke_env.player import SingleBattleOrder


_PUBLIC_COMMANDS = {
    "turn",
    "switch",
    "drag",
    "move",
    "-miss",
    "-damage",
    "-heal",
    "-crit",
    "-status",
    "-curestatus",
    "-weather",
    "-fieldstart",
    "-fieldend",
    "-sidestart",
    "-sideend",
    "-item",
    "-enditem",
    "-ability",
    "-terastallize",
    "faint",
    "win",
    "tie",
}


def _enum_name(value: object | None) -> str | None:
    if value is None:
        return None
    name = getattr(value, "name", None)
    return str(name).lower() if name else str(value).lower()


def _move_category(value: object | None) -> Literal["physical", "special", "status"] | None:
    category = _enum_name(value)
    if category == "physical":
        return "physical"
    if category == "special":
        return "special"
    if category == "status":
        return "status"
    return None


def _move_state(move: Move) -> MoveState:
    accuracy = getattr(move, "accuracy", None)
    if isinstance(accuracy, bool):
        accuracy = None
    return MoveState(
        id=move.id,
        name=move.entry.get("name", move.id),
        type=_enum_name(getattr(move, "type", None)),
        category=_move_category(getattr(move, "category", None)),
        power=getattr(move, "base_power", None),
        accuracy=accuracy,
        current_pp=getattr(move, "current_pp", None),
        max_pp=getattr(move, "max_pp", None),
    )


def _pokemon_state(identifier: str, pokemon: Pokemon, *, revealed: bool = True) -> PokemonState:
    types = tuple(
        value for value in (_enum_name(item) for item in getattr(pokemon, "types", [])) if value
    )
    moves = tuple(_move_state(move) for _, move in sorted(getattr(pokemon, "moves", {}).items()))
    boosts = {str(key): int(value) for key, value in sorted(getattr(pokemon, "boosts", {}).items())}
    effects = tuple(sorted(_enum_name(item) or "unknown" for item in pokemon.effects))
    return PokemonState(
        id=identifier,
        name=pokemon.name,
        species=pokemon.species,
        level=getattr(pokemon, "level", None),
        current_hp=getattr(pokemon, "current_hp", None),
        max_hp=getattr(pokemon, "max_hp", None),
        hp_fraction=max(0.0, min(1.0, float(pokemon.current_hp_fraction))),
        status=_enum_name(pokemon.status),
        types=types,
        item=getattr(pokemon, "item", None) or None,
        ability=getattr(pokemon, "ability", None) or None,
        tera_type=_enum_name(getattr(pokemon, "tera_type", None)),
        terastallized=bool(getattr(pokemon, "is_terastallized", False)),
        boosts=boosts,
        effects=effects,
        active=bool(pokemon.active),
        fainted=bool(pokemon.fainted),
        revealed=revealed,
        moves=moves,
    )


def legal_actions(battle: AbstractBattle) -> tuple[BattleAction, ...]:
    actions: list[BattleAction] = []
    for slot, move in enumerate(battle.available_moves, start=1):
        name = move.entry.get("name", move.id)
        actions.append(BattleAction(id=f"move:{slot}", type=ActionType.MOVE, name=name, slot=slot))
        if bool(battle.can_tera):
            actions.append(
                BattleAction(
                    id=f"move:{slot}:tera",
                    type=ActionType.MOVE,
                    name=f"{name} + Terastallize",
                    slot=slot,
                    terastallize=True,
                )
            )
    for slot, pokemon in enumerate(battle.available_switches, start=1):
        actions.append(
            BattleAction(
                id=f"switch:{slot}",
                type=ActionType.SWITCH,
                name=pokemon.species,
                slot=slot,
            )
        )
    return tuple(actions)


def action_to_order(action: BattleAction, battle: AbstractBattle) -> SingleBattleOrder:
    from poke_env.player import SingleBattleOrder

    if action.type is ActionType.MOVE:
        try:
            move = battle.available_moves[action.slot - 1]
        except IndexError as error:
            raise ValueError(f"move slot {action.slot} is no longer legal") from error
        return SingleBattleOrder(move, terastallize=action.terastallize)
    try:
        pokemon = battle.available_switches[action.slot - 1]
    except IndexError as error:
        raise ValueError(f"switch slot {action.slot} is no longer legal") from error
    return SingleBattleOrder(pokemon)


def _public_history(battle: AbstractBattle) -> tuple[str, ...]:
    history: list[str] = []
    # poke-env's replay buffer is an adapter-private compatibility surface pinned to 0.15.0.
    for parts in battle._replay_data:  # noqa: SLF001
        if len(parts) > 1 and parts[1] in _PUBLIC_COMMANDS:
            history.append("|".join(parts))
    return tuple(history[-12:])


def battle_state(
    battle: AbstractBattle,
    *,
    match_id: UUID,
    side: Side,
    display_names: dict[Side, str],
    result: BattleResult | None = None,
) -> BattleState:
    opponent_side = Side.P2 if side is Side.P1 else Side.P1
    own_team = tuple(
        _pokemon_state(identifier, pokemon) for identifier, pokemon in sorted(battle.team.items())
    )
    opponent_team = tuple(
        _pokemon_state(identifier, pokemon)
        for identifier, pokemon in sorted(battle.opponent_team.items())
    )
    own_active = next((pokemon for pokemon in own_team if pokemon.active), None)
    opponent_active = next((pokemon for pokemon in opponent_team if pokemon.active), None)
    history = _public_history(battle)
    last_action = next((item for item in reversed(history) if "|move|" in item), None)
    return BattleState(
        match_id=match_id,
        format=battle.format or "gen9randombattle",
        generation=battle.gen,
        turn=battle.turn,
        perspective=side,
        player=BattleSide(
            side=side,
            display_name=display_names[side],
            active=own_active,
            team=own_team,
            side_conditions=tuple(
                sorted(_enum_name(item) or "unknown" for item in battle.side_conditions)
            ),
            can_terastallize=bool(battle.can_tera),
            terastallization_used=not bool(battle.can_tera),
        ),
        opponent=BattleSide(
            side=opponent_side,
            display_name=display_names[opponent_side],
            active=opponent_active,
            team=opponent_team,
            side_conditions=tuple(
                sorted(_enum_name(item) or "unknown" for item in battle.opponent_side_conditions)
            ),
        ),
        weather=tuple(sorted(_enum_name(item) or "unknown" for item in battle.weather)),
        fields=tuple(sorted(_enum_name(item) or "unknown" for item in battle.fields)),
        last_action=last_action,
        public_history=history,
        result=result,
    )


def find_action(action_id: str, actions: tuple[BattleAction, ...]) -> BattleAction:
    for action in actions:
        if action.id == action_id:
            return action
    raise ValueError(f"agent selected illegal action {action_id!r}")
