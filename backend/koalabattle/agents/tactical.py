from __future__ import annotations

from koalabattle.core.models import (
    ActionType,
    AgentDecision,
    AgentRequest,
    BattleAction,
    MoveState,
    PokemonState,
)

_TYPE_EFFECTIVENESS: dict[str, tuple[set[str], set[str], set[str]]] = {
    "normal": (set(), {"rock", "steel"}, {"ghost"}),
    "fire": ({"grass", "ice", "bug", "steel"}, {"fire", "water", "rock", "dragon"}, set()),
    "water": ({"fire", "ground", "rock"}, {"water", "grass", "dragon"}, set()),
    "electric": ({"water", "flying"}, {"electric", "grass", "dragon"}, {"ground"}),
    "grass": (
        {"water", "ground", "rock"},
        {"fire", "grass", "poison", "flying", "bug", "dragon", "steel"},
        set(),
    ),
    "ice": ({"grass", "ground", "flying", "dragon"}, {"fire", "water", "ice", "steel"}, set()),
    "fighting": (
        {"normal", "ice", "rock", "dark", "steel"},
        {"poison", "flying", "psychic", "bug", "fairy"},
        {"ghost"},
    ),
    "poison": ({"grass", "fairy"}, {"poison", "ground", "rock", "ghost"}, {"steel"}),
    "ground": ({"fire", "electric", "poison", "rock", "steel"}, {"grass", "bug"}, {"flying"}),
    "flying": ({"grass", "fighting", "bug"}, {"electric", "rock", "steel"}, set()),
    "psychic": ({"fighting", "poison"}, {"psychic", "steel"}, {"dark"}),
    "bug": (
        {"grass", "psychic", "dark"},
        {"fire", "fighting", "poison", "flying", "ghost", "steel", "fairy"},
        set(),
    ),
    "rock": ({"fire", "ice", "flying", "bug"}, {"fighting", "ground", "steel"}, set()),
    "ghost": ({"psychic", "ghost"}, {"dark"}, {"normal"}),
    "dragon": ({"dragon"}, {"steel"}, {"fairy"}),
    "dark": ({"psychic", "ghost"}, {"fighting", "dark", "fairy"}, set()),
    "steel": ({"ice", "rock", "fairy"}, {"fire", "water", "electric", "steel"}, set()),
    "fairy": ({"fighting", "dragon", "dark"}, {"fire", "poison", "steel"}, set()),
}

_RECOVERY = {
    "recover",
    "roost",
    "softboiled",
    "slackoff",
    "synthesis",
    "rest",
    "milkdrink",
    "shoreup",
}
_SETUP = {
    "swordsdance",
    "nastyplot",
    "calmmind",
    "dragondance",
    "quiverdance",
    "bulkup",
    "shellsmash",
}
_DISRUPTION = {
    "toxic",
    "willowisp",
    "thunderwave",
    "spore",
    "sleeppowder",
    "stealthrock",
    "spikes",
    "taunt",
}


def _id(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _effectiveness(move_type: str | None, opponent_types: tuple[str, ...]) -> float:
    if not move_type or not opponent_types:
        return 1.0
    strong, resisted, immune = _TYPE_EFFECTIVENESS.get(move_type.lower(), (set(), set(), set()))
    multiplier = 1.0
    for opponent_type in (item.lower() for item in opponent_types):
        if opponent_type in immune:
            return 0.0
        if opponent_type in strong:
            multiplier *= 2
        elif opponent_type in resisted:
            multiplier *= 0.5
    return multiplier


def _accuracy(value: float | int | None) -> float:
    accuracy = float(value or 100)
    if accuracy <= 1:
        accuracy *= 100
    return max(1, min(100, accuracy)) / 100


def _damage_score(
    *,
    move_type: str | None,
    category: str | None,
    power: int | None,
    accuracy: float | int | None,
    priority: int | None,
    own_types: tuple[str, ...],
    opponent_types: tuple[str, ...],
    own_hp: float,
    opponent_hp: float,
) -> float:
    if category == "status" or not power:
        return 0
    effectiveness = _effectiveness(move_type, opponent_types)
    if effectiveness == 0:
        return -100
    stab = 1.5 if move_type and move_type.lower() in {item.lower() for item in own_types} else 1
    score = float(power) * _accuracy(accuracy) * stab * effectiveness
    if priority and priority > 0 and (own_hp < 0.3 or opponent_hp < 0.3):
        score += 30 * priority
    return score


def _candidate_matchup_score(candidate: PokemonState, opponent: PokemonState | None) -> float:
    opponent_types = opponent.types if opponent else ()
    best_damage = max(
        (
            _damage_score(
                move_type=move.type,
                category=move.category,
                power=move.power,
                accuracy=move.accuracy,
                priority=move.priority,
                own_types=candidate.types,
                opponent_types=opponent_types,
                own_hp=candidate.hp_fraction,
                opponent_hp=opponent.hp_fraction if opponent else 1,
            )
            for move in candidate.moves
            if not move.disabled and (move.current_pp is None or move.current_pp > 0)
        ),
        default=0,
    )
    revealed_moves: tuple[MoveState, ...] = opponent.moves if opponent else ()
    threat_types = tuple(move.type for move in revealed_moves if move.type) or opponent_types
    incoming = max(
        (_effectiveness(move_type, candidate.types) for move_type in threat_types),
        default=1,
    )
    defense = {0: 45, 0.25: 30, 0.5: 18, 1: 0, 2: -25, 4: -55}.get(incoming, -70)
    return 15 * candidate.hp_fraction + min(90, max(0, best_damage) / 6) + defense


class TacticalAgent:
    """Fast deterministic local baseline using only information visible in AgentRequest."""

    def __init__(self) -> None:
        self._last_active_id: str | None = None
        self._recent_switch_origin_id: str | None = None
        self._active_changed_at_turn: int | None = None

    async def decide(self, request: AgentRequest) -> AgentDecision:
        active = request.state.player.active
        opponent = request.state.opponent.active
        own_types = active.types if active else ()
        opponent_types = opponent.types if opponent else ()
        hp = active.hp_fraction if active else 0.0
        opponent_hp = opponent.hp_fraction if opponent else 1.0
        forced_switch = (
            active is None
            or active.fainted
            or not any(item.type is ActionType.MOVE for item in request.legal_actions)
        )
        if active is not None and active.id != self._last_active_id:
            if self._last_active_id is not None:
                self._recent_switch_origin_id = self._last_active_id
                self._active_changed_at_turn = request.turn
            self._last_active_id = active.id

        def score(action: BattleAction) -> tuple[float, str]:
            if action.type is ActionType.SWITCH:
                action_name = _id(action.name)
                action_species = _id(action.species or "")
                candidate = next(
                    (
                        pokemon
                        for pokemon in request.state.player.team
                        if action_name
                        in {
                            _id(pokemon.name),
                            _id(pokemon.id.rsplit(":", 1)[-1]),
                        }
                    ),
                    None,
                )
                if candidate is None:
                    candidate = next(
                        (
                            pokemon
                            for pokemon in request.state.player.team
                            if _id(pokemon.species) == action_species
                        ),
                        None,
                    )
                switch_score = 8 + (
                    _candidate_matchup_score(candidate, opponent)
                    if candidate
                    else 15 * (action.hp_fraction or 0)
                )
                if forced_switch:
                    switch_score += 1000
                elif hp < 0.22:
                    switch_score += 28
                if (
                    not forced_switch
                    and candidate is not None
                    and candidate.id == self._recent_switch_origin_id
                    and self._active_changed_at_turn is not None
                    and request.turn <= self._active_changed_at_turn + 1
                ):
                    switch_score -= 140
                return switch_score, action.id

            move_id = _id(action.name)
            if action.category == "status" or not action.power:
                utility = 10.0
                if move_id in _RECOVERY:
                    utility = 72 if hp < 0.35 else 4
                elif move_id in _SETUP:
                    utility = 40 if request.turn <= 4 and hp > 0.55 else 12
                elif move_id in _DISRUPTION:
                    utility = 35 if opponent and not opponent.status else 8
                return utility * _accuracy(action.accuracy), action.id
            damage = _damage_score(
                move_type=action.move_type,
                category=action.category,
                power=action.power,
                accuracy=action.accuracy,
                priority=action.priority,
                own_types=own_types,
                opponent_types=opponent_types,
                own_hp=hp,
                opponent_hp=opponent_hp,
            )
            return damage, action.id

        selected = max(request.legal_actions, key=score)
        return AgentDecision(
            request_id=request.request_id,
            match_id=request.match_id,
            side=request.side,
            turn=request.turn,
            decision_sequence=request.decision_sequence,
            action=selected.id,
            commentary=f"Fast Auto chose {selected.name}.",
            provider_metadata={"agent": "tactical-auto", "local": True, "cost": 0},
        )
