"""Render a compact, model-friendly battle prompt from the structured agent context.

`AgentContextSnapshot` stays the versioned internal model. This module is the presentation
layer on top of it: it turns that snapshot into readable text that a fresh web chat can act
on with no prior conversation, and it omits every mechanic the selected generation does not
have (no items in Gen 1, no abilities before Gen 3, no Terastallization before Gen 9).
"""

from __future__ import annotations

from dataclasses import dataclass

from koalabattle.core.models import (
    MAX_COMMENTARY_CHARACTERS,
    MAX_STRATEGY_MEMORY_CHARACTERS,
    AgentContextSnapshot,
    BattleAction,
    KnownPokemon,
    MemoryPolicyId,
    MoveState,
    PokemonState,
)
from koalabattle.formats import FormatMechanics, ability_name, item_name

PROMPT_RENDERER_VERSION = "battle-text-v1"

_STATUS_LABELS = {
    "brn": "burned",
    "par": "paralyzed",
    "psn": "poisoned",
    "tox": "badly poisoned",
    "slp": "asleep",
    "frz": "frozen",
    "fnt": "fainted",
}

_BOOST_ORDER = ("atk", "def", "spa", "spd", "spe", "accuracy", "evasion")
_BOOST_LABELS = {
    "atk": "Atk",
    "def": "Def",
    "spa": "SpA",
    "spd": "SpD",
    "spe": "Spe",
    "accuracy": "Acc",
    "evasion": "Eva",
}


@dataclass(frozen=True)
class RenderedPrompt:
    """One prompt in the two shapes KoalaBattle needs: chat messages and a copyable block."""

    system: str
    user: str

    @property
    def combined(self) -> str:
        return f"{self.system}\n\n{self.user}"


def title_case(value: str) -> str:
    """Turn `light-screen` or `stealth_rock` into `Light Screen`."""
    cleaned = value.replace("_", " ").replace("-", " ").strip()
    return " ".join(word.capitalize() for word in cleaned.split()) or value


def status_label(status: str | None) -> str:
    if not status:
        return "none"
    return _STATUS_LABELS.get(status.casefold(), title_case(status))


def percent(fraction: float | None) -> str:
    if fraction is None:
        return "unknown"
    return f"{round(fraction * 100)}%"


def type_line(types: tuple[str, ...]) -> str:
    return "/".join(title_case(item) for item in types) if types else "unknown"


def accuracy_label(accuracy: float | int | None) -> str:
    if accuracy is None:
        return "—"
    if accuracy is True or accuracy == 0:
        return "always hits"
    value = float(accuracy)
    if value <= 1:
        value *= 100
    return f"{round(value)}%"


def damage_class(category: str | None, power: int | None, mechanics: FormatMechanics) -> list[str]:
    """Name the damage class and base power the way the selected generation works.

    Before Gen 4 the physical/special split is decided by the move's type, so repeating
    Showdown's modern category would state a rule that format does not have.
    """
    if category == "status" or (category is None and power == 0):
        return ["Status"]
    parts: list[str] = []
    if category and mechanics.physical_special_split:
        parts.append(category.capitalize())
    # Moves like Grass Knot and Low Kick carry base power 0 because it depends on the target.
    parts.append(f"{power} BP" if power else "variable BP")
    return parts


def move_line(move: MoveState, mechanics: FormatMechanics) -> str:
    """One-line public move metadata, generation-correct."""
    parts = [title_case(move.type or "unknown")]
    parts.extend(damage_class(move.category, move.power, mechanics))
    parts.append(accuracy_label(move.accuracy))
    if move.current_pp is not None and move.max_pp is not None:
        parts.append(f"{move.current_pp}/{move.max_pp} PP")
    if move.disabled:
        parts.append("DISABLED")
    return " · ".join(parts)


def boost_line(boosts: dict[str, int]) -> str | None:
    active = {key: value for key, value in boosts.items() if value}
    if not active:
        return None

    def rank(key: str) -> int:
        return _BOOST_ORDER.index(key) if key in _BOOST_ORDER else len(_BOOST_ORDER)

    ordered = sorted(active, key=rank)
    return " · ".join(f"{_BOOST_LABELS.get(key, key)} {active[key]:+d}" for key in ordered)


def _own_pokemon_block(
    pokemon: PokemonState, mechanics: FormatMechanics, *, active: bool
) -> list[str]:
    header = pokemon.name
    if pokemon.level is not None:
        header = f"{header} · Lv. {pokemon.level}"
    lines = [header]
    lines.append(f"Type: {type_line(pokemon.types)}")
    if pokemon.fainted:
        lines.append("HP: 0% (fainted)")
    elif pokemon.current_hp is not None and pokemon.max_hp:
        lines.append(f"HP: {pokemon.current_hp}/{pokemon.max_hp} ({percent(pokemon.hp_fraction)})")
    else:
        lines.append(f"HP: {percent(pokemon.hp_fraction)}")
    lines.append(f"Status: {status_label(pokemon.status)}")
    if mechanics.abilities:
        lines.append(f"Ability: {ability_name(pokemon.ability) or 'unknown'}")
    if mechanics.items:
        lines.append(f"Item: {item_name(pokemon.item) or 'none'}")
    if mechanics.terastallization and pokemon.tera_type:
        state = "already Terastallized" if pokemon.terastallized else "available"
        lines.append(f"Tera type: {title_case(pokemon.tera_type)} ({state})")
    if active:
        stages = boost_line(pokemon.boosts)
        lines.append(f"Stat stages: {stages}" if stages else "Stat stages: none")
        if pokemon.effects:
            lines.append(f"Effects: {', '.join(title_case(item) for item in pokemon.effects)}")
    if pokemon.moves:
        lines.append("Moves:")
        for index, move in enumerate(pokemon.moves, start=1):
            lines.append(f"  M{index} {move.name}")
            lines.append(f"     {move_line(move, mechanics)}")
    else:
        lines.append("Moves: not yet known")
    return lines


def _known_pokemon_block(pokemon: KnownPokemon, mechanics: FormatMechanics) -> list[str]:
    lines = [pokemon.display_name]
    lines.append(f"Type: {type_line(pokemon.types)}")
    lines.append(f"HP: {percent(pokemon.hp_fraction)}{' (fainted)' if pokemon.fainted else ''}")
    lines.append(f"Status: {status_label(pokemon.status)}")
    if mechanics.abilities:
        lines.append(f"Known ability: {ability_name(pokemon.revealed_ability) or 'unknown'}")
    if mechanics.items:
        lines.append(f"Known item: {item_name(pokemon.revealed_item) or 'unknown'}")
    if mechanics.terastallization and pokemon.revealed_tera_type:
        lines.append(f"Terastallized into: {title_case(pokemon.revealed_tera_type)}")
    if pokemon.revealed_moves:
        lines.append("Known moves:")
        for move in pokemon.revealed_moves:
            lines.append(f"  {move.name} · {move_line(move, mechanics)}")
    else:
        lines.append("Known moves: none revealed")
    return lines


def action_line(action: BattleAction, mechanics: FormatMechanics) -> list[str]:
    """Render one legal action so the model never has to cross-reference another section."""
    if action.type.value == "switch":
        detail = f"{action.species or action.name} · {percent(action.hp_fraction)}"
        if action.status and action.status != "none":
            detail = f"{detail} · {status_label(action.status)}"
        return [action.id, f"  Switch to {detail}"]
    parts = [title_case(action.move_type or "unknown")]
    parts.extend(damage_class(action.category, action.power, mechanics))
    parts.append(accuracy_label(action.accuracy))
    if action.current_pp is not None and action.max_pp is not None:
        parts.append(f"{action.current_pp}/{action.max_pp} PP")
    if action.priority:
        parts.append(f"priority {action.priority:+d}")
    suffix = " + Terastallize" if action.terastallize else ""
    name = action.name.removesuffix(" + Terastallize")
    return [action.id, f"  {name}{suffix} · {' · '.join(parts)}"]


def humanize_event(entry: str, own_side: str = "p1") -> str | None:
    """Turn one raw Showdown protocol line into a readable sentence for one player.

    Ownership is resolved against the reading player's own side, so the P2 agent never
    reads the opponent's Pokemon as its own.
    """
    parts = entry.split("|")
    if len(parts) < 2:
        return None
    command = parts[1]
    fields = list(parts[2:])

    def actor(index: int = 0) -> str:
        if index >= len(fields):
            return "A Pokemon"
        raw = fields[index]
        name = raw.split(":", 1)[1].strip() if ":" in raw else raw
        owner = "Your" if raw.startswith(own_side) else "Opposing"
        return f"{owner} {name}" if name else owner

    if command == "move" and len(fields) >= 2:
        return f"{actor()} used {fields[1]}."
    if command in {"switch", "drag"} and len(fields) >= 2:
        return f"{actor()} switched in ({fields[1].split(',')[0]})."
    if command == "faint":
        return f"{actor()} fainted."
    if command == "-status" and len(fields) >= 2:
        return f"{actor()} is now {status_label(fields[1])}."
    if command == "-curestatus" and len(fields) >= 2:
        return f"{actor()} recovered from {status_label(fields[1])}."
    if command == "-ability" and len(fields) >= 2:
        return f"{actor()} revealed the ability {ability_name(fields[1])}."
    if command == "-item" and len(fields) >= 2:
        return f"{actor()} revealed the item {item_name(fields[1])}."
    if command == "-enditem" and len(fields) >= 2:
        return f"{actor()} lost its {item_name(fields[1])}."
    if command == "-terastallize" and len(fields) >= 2:
        return f"{actor()} Terastallized into {title_case(fields[1])}."
    if command == "-weather" and fields:
        return f"Weather: {title_case(fields[0])}."
    if command == "-sidestart" and len(fields) >= 2:
        return f"{title_case(fields[1].split(':')[-1])} was set on one side."
    if command == "-sideend" and len(fields) >= 2:
        return f"{title_case(fields[1].split(':')[-1])} faded."
    return None


def _system_prompt(snapshot: AgentContextSnapshot) -> str:
    display_name = snapshot.knowledge.own_side.display_name
    player_number = "1" if snapshot.side.value == "p1" else "2"
    memory_enabled = snapshot.memory_policy is MemoryPolicyId.STRATEGY_NOTE
    lines = [
        f"You are {display_name}, Player {player_number} in a Pokemon Showdown battle.",
        "",
        "OBJECTIVE",
        "Win the battle.",
        "",
        "RULES",
        "- Choose exactly one action ID from LEGAL ACTIONS, copied verbatim.",
        "- The supplied snapshot is the only source of current match facts.",
        "- You may use general Pokemon battle knowledge and the supplied format rules.",
        "- You may make probabilistic strategic predictions from public information, but never",
        "  present unrevealed opponent information as known fact.",
        "- Do not invent game state and never write a raw Showdown command.",
        "- Return one JSON object and no markdown.",
        "",
        "RETURN EXACTLY",
        "{",
        '  "action": "<one exact legal action id>",',
        f'  "commentary": "<one viewer-facing sentence, max '
        f'{MAX_COMMENTARY_CHARACTERS} characters>",',
    ]
    if memory_enabled:
        lines.append(
            f'  "strategy_memory": "<private note for your next turn, max '
            f'{MAX_STRATEGY_MEMORY_CHARACTERS} characters, or null>"'
        )
    else:
        lines.append('  "strategy_memory": null')
    lines.append("}")
    if memory_enabled:
        lines.extend(
            [
                "",
                "Commentary is shown to spectators and spoken aloud. Strategy memory is private",
                "and is never broadcast.",
            ]
        )
    return "\n".join(lines)


def _format_section(snapshot: AgentContextSnapshot) -> list[str]:
    mechanics = snapshot.mechanics
    lines = [
        "FORMAT",
        snapshot.format_name or snapshot.format,
        f"Generation {snapshot.generation} · {snapshot.game_type} · one active Pokemon per side",
    ]
    enabled = mechanics.enabled()
    absent = [
        label
        for label, present in (
            ("abilities", mechanics.abilities),
            ("held items", mechanics.items),
        )
        if not present
    ]
    if enabled:
        lines.append(f"Available mechanics: {', '.join(enabled)}")
    if absent:
        lines.append(f"This generation has no {' and no '.join(absent)}.")
    if not mechanics.physical_special_split:
        lines.append("Damage class is decided by the move's type, not by the move itself.")
    return lines


def _user_prompt(snapshot: AgentContextSnapshot, history: tuple[str, ...]) -> str:
    knowledge = snapshot.knowledge
    mechanics = snapshot.mechanics
    blocks: list[list[str]] = [
        _format_section(snapshot),
        ["TURN", str(snapshot.turn)],
    ]

    active = knowledge.own_side.active
    blocks.append(
        ["YOUR ACTIVE POKEMON", *_own_pokemon_block(active, mechanics, active=True)]
        if active
        else ["YOUR ACTIVE POKEMON", "None — you must send out a replacement."]
    )

    bench = [
        item
        for item in knowledge.own_side.team
        if not item.active and (active is None or item.id != active.id)
    ]
    if bench:
        team_lines = ["YOUR BENCH"]
        for member in bench:
            team_lines.extend(_own_pokemon_block(member, mechanics, active=False))
            team_lines.append("")
        blocks.append([line for line in team_lines[:-1]])
    else:
        blocks.append(["YOUR BENCH", "No other Pokemon available."])

    if knowledge.opponent_active is not None:
        blocks.append(
            ["OPPONENT ACTIVE", *_known_pokemon_block(knowledge.opponent_active, mechanics)]
        )
    else:
        blocks.append(["OPPONENT ACTIVE", "Not yet revealed."])

    others = [
        item
        for item in knowledge.known_opponent
        if knowledge.opponent_active is None or item.id != knowledge.opponent_active.id
    ]
    if others:
        known_lines = ["KNOWN OPPONENT TEAM"]
        for known in others:
            known_lines.append(
                f"{known.display_name} · {percent(known.hp_fraction)}"
                f"{' · fainted' if known.fainted else ''}"
                f"{'' if known.status is None else f' · {status_label(known.status)}'}"
            )
            if known.revealed_moves:
                known_lines.append(
                    f"  Known moves: {', '.join(move.name for move in known.revealed_moves)}"
                )
        blocks.append(known_lines)
    else:
        blocks.append(["KNOWN OPPONENT TEAM", "No other Pokemon revealed."])

    field_lines = [
        "FIELD",
        f"Weather: {', '.join(title_case(item) for item in knowledge.weather) or 'none'}",
        f"Terrain: {', '.join(title_case(item) for item in knowledge.fields) or 'none'}",
        "Your side: "
        + (
            ", ".join(title_case(item) for item in knowledge.own_side.side_conditions)
            or "no hazards or screens"
        ),
        "Opponent side: "
        + (
            ", ".join(title_case(item) for item in knowledge.opponent_side_conditions)
            or "no hazards or screens"
        ),
    ]
    blocks.append(field_lines)

    readable = [
        line for line in (humanize_event(entry, snapshot.side.value) for entry in history) if line
    ]
    blocks.append(["RECENT EVENTS", *(readable or ["No relevant previous events."])])

    if snapshot.memory_policy is MemoryPolicyId.STRATEGY_NOTE:
        blocks.append(["YOUR STRATEGY NOTE", snapshot.strategy_memory or "None recorded yet."])

    action_lines = ["LEGAL ACTIONS"]
    for action in snapshot.legal_actions:
        action_lines.extend(action_line(action, mechanics))
    blocks.append(action_lines)

    return "\n\n".join("\n".join(block) for block in blocks)


def render(
    snapshot: AgentContextSnapshot, history: tuple[str, ...] | None = None
) -> RenderedPrompt:
    """Render the system/user pair for one decision."""
    events = snapshot.recent_events if history is None else history
    return RenderedPrompt(
        system=_system_prompt(snapshot),
        user=_user_prompt(snapshot, events),
    )
