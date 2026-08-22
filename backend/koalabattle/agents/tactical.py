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
    "lovelykiss",
    "hypnosis",
    "glare",
    "taunt",
    "encore",
}
#: Entry hazards are only worth a turn when the opponent still has switches left.
_HAZARDS = {"stealthrock", "spikes", "toxicspikes", "stickyweb"}
#: Removing our own hazards is worth a turn once they are actually down.
_HAZARD_REMOVAL = {"rapidspin", "defog", "courtchange", "tidyup", "mortalspin"}
#: Statuses a second status move cannot stack onto.
_MAJOR_STATUS = {"brn", "par", "psn", "tox", "slp", "frz"}
#: Rough per-switch HP cost of the hazards on our own half of the field.
_HAZARD_SWITCH_COST = {
    "stealthrock": 0.13,
    "spikes": 0.12,
    "toxicspikes": 0.06,
    "stickyweb": 0.05,
}
#: The move ids each status move actually applies, so it is never used redundantly.
_STATUS_MOVE_EFFECT = {
    "toxic": "tox",
    "willowisp": "brn",
    "thunderwave": "par",
    "glare": "par",
    "spore": "slp",
    "sleeppowder": "slp",
    "lovelykiss": "slp",
    "hypnosis": "slp",
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


def _side_condition_ids(conditions: tuple[str, ...]) -> set[str]:
    return {_id(item) for item in conditions}


def _hazard_switch_cost(conditions: set[str]) -> float:
    """Fraction of maximum HP a switch-in loses to the hazards already on our side."""
    return sum(cost for name, cost in _HAZARD_SWITCH_COST.items() if name in conditions)


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
    # A finishing bonus was measured against the campaign and made the agent *worse*: the
    # power-based KO estimate is far too optimistic, so it fired on nearly every move and
    # quietly re-ranked hits by accuracy instead of by damage. Only the narrow, safe part
    # survives: when the target is genuinely nearly dead, prefer the reliable hit.
    if opponent_hp > 0 and opponent_hp <= 0.2:
        score += 25 * _accuracy(accuracy)
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
        own_conditions = _side_condition_ids(request.state.player.side_conditions)
        opponent_conditions = _side_condition_ids(request.state.opponent.side_conditions)
        switch_cost = _hazard_switch_cost(own_conditions)
        opponent_bench = sum(
            1
            for pokemon in request.state.opponent.team
            if not pokemon.fainted and not pokemon.active
        )
        # How hard the opponent can hit back right now, from what it has revealed.
        revealed = tuple(move.type for move in (opponent.moves if opponent else ()) if move.type)
        incoming = max(
            (_effectiveness(move_type, own_types) for move_type in (revealed or opponent_types)),
            default=1.0,
        )
        offensive_boost = max(
            (active.boosts.get(stat, 0) for stat in ("atk", "spa", "spe")), default=0
        ) if active else 0
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
                else:
                    # Switching into our own hazards is not free, and a switch-in that
                    # would arrive nearly dead is worse than staying in.
                    arriving = (candidate.hp_fraction if candidate else (action.hp_fraction or 1))
                    switch_score -= 90 * switch_cost
                    if arriving - switch_cost <= 0.12:
                        switch_score -= 60
                    if hp < 0.22:
                        switch_score += 28
                    # A bad matchup is the reason to switch; a good one is a reason to stay.
                    if incoming >= 2:
                        switch_score += 22
                    elif incoming <= 0.5:
                        switch_score -= 26
                    # Never throw away an active setup by switching out of it.
                    switch_score -= 26 * max(0, offensive_boost)
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
                    # Healing is only tempo if we survive to use it. Against a matchup that
                    # is already hitting us super effectively, healing just delays the loss.
                    utility = 76 if hp < 0.42 and incoming < 2 else 6 if hp < 0.42 else 3
                elif move_id in _SETUP:
                    # Set up when it is actually safe and there is something left to sweep,
                    # not only in the opening turns, and never past a useful boost.
                    safe = hp > 0.6 and incoming <= 1 and opponent_hp > 0.35
                    utility = 46 if safe and offensive_boost < 2 else 8
                elif move_id in _HAZARDS:
                    already = move_id in opponent_conditions
                    # Toxic Spikes stacks once, the rest do not; either way, hazards are
                    # only worth a turn while the opponent still has Pokemon to bring in.
                    utility = 44 if not already and opponent_bench >= 2 else 4
                elif move_id in _HAZARD_REMOVAL:
                    utility = 40 if own_conditions & set(_HAZARD_SWITCH_COST) else 5
                elif move_id in _DISRUPTION:
                    applied = _STATUS_MOVE_EFFECT.get(move_id)
                    blocked = bool(
                        opponent
                        and opponent.status
                        and (applied is None or opponent.status in _MAJOR_STATUS)
                    )
                    utility = 8 if blocked else 38 if opponent_hp > 0.45 else 14
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
            if action.mega_evolve:
                damage += 18
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
