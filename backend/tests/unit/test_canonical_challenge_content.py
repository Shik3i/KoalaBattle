from __future__ import annotations

import hashlib
import json
from pathlib import Path

from koalabattle.challenges.service import _definition

# Species are authored per trainer theme. Roster size and set quality escalate; these are
# regression-locked so a later stage can never quietly become smaller or weaker.
EXPECTED_SPECIES = {
    "brock": (
        "Onix",
        "Golem",
        "Rhyhorn",
        "Graveler",
        "Omastar",
        "Kabutops",
    ),
    "misty": (
        "Starmie",
        "Lapras",
        "Quagsire",
        "Golduck",
        "Staryu",
        "Psyduck",
    ),
    "lt-surge": (
        "Raichu",
        "Magneton",
        "Electrode",
        "Electivire",
        "Electabuzz",
        "Pikachu",
    ),
    "erika": (
        "Tangela",
        "Victreebel",
        "Bellossom",
        "Vileplume",
        "Gloom",
        "Jumpluff",
    ),
    "koga": (
        "Crobat",
        "Koffing",
        "Muk",
        "Venomoth",
        "Weezing",
        "Ariados",
    ),
    "sabrina": (
        "Alakazam",
        "Espeon",
        "Kadabra",
        "Venomoth",
        "Mr. Mime",
        "Abra",
    ),
    "blaine": (
        "Ninetales",
        "Growlithe",
        "Arcanine",
        "Magmortar",
        "Rapidash",
        "Magcargo",
    ),
    "giovanni": (
        "Nidoking",
        "Nidoqueen",
        "Rhydon",
        "Dugtrio",
        "Persian",
        "Kangaskhan",
    ),
    "lorelei": (
        "Cloyster",
        "Lapras",
        "Jynx",
        "Dewgong",
        "Slowbro",
        "Piloswine",
    ),
    "bruno": (
        "Machamp",
        "Hitmonlee",
        "Hitmonchan",
        "Hitmontop",
        "Steelix",
        "Onix",
    ),
    "agatha": (
        "Gengar",
        "Haunter",
        "Arbok",
        "Gastly",
        "Golbat",
        "Misdreavus",
    ),
    "lance": (
        "Dragonite",
        "Dragonair",
        "Dratini",
        "Gyarados",
        "Aerodactyl",
        "Charizard",
    ),
    "champion-blue": (
        "Pidgeot",
        "Alakazam",
        "Rhydon",
        "Gyarados",
        "Exeggutor",
        "Charizard",
    ),
}

NATURES = {
    "Adamant", "Bold", "Brave", "Calm", "Careful", "Gentle", "Hasty", "Impish", "Jolly",
    "Lax", "Lonely", "Mild", "Modest", "Naive", "Naughty", "Quiet", "Rash", "Relaxed",
    "Sassy", "Serious", "Timid",
}


def _sets(stage_team: str) -> list[dict[str, object]]:
    parsed: list[dict[str, object]] = []
    for block in stage_team.split("\n\n"):
        lines = block.splitlines()
        heading = lines[0]
        parsed.append(
            {
                "species": heading.split(" @ ")[0].strip(),
                "item": heading.split(" @ ")[1].strip() if " @ " in heading else None,
                "ability": next(
                    (
                        line.removeprefix("Ability: ")
                        for line in lines
                        if line.startswith("Ability: ")
                    ),
                    None,
                ),
                "nature": next(
                    (line.removesuffix(" Nature") for line in lines if line.endswith(" Nature")),
                    None,
                ),
                "evs": next(
                    (line.removeprefix("EVs: ") for line in lines if line.startswith("EVs: ")), None
                ),
                "ivs": next(
                    (line.removeprefix("IVs: ") for line in lines if line.startswith("IVs: ")), None
                ),
                "moves": [line.removeprefix("- ") for line in lines if line.startswith("- ")],
            }
        )
    return parsed


def _source_snapshot() -> list[dict[str, object]]:
    definition = _definition("kanto-gym-gauntlet")
    return [
        {"id": stage.id, "level": stage.level, "team": _sets(stage.opponent_team)}
        for stage in definition.stages
    ]


def test_kanto_content_uses_authored_theme_teams() -> None:
    definition = _definition("kanto-gym-gauntlet")

    assert definition.version == "12.0.0"
    assert definition.draft_rules.rerolls == 3
    assert definition.draft_rules.type_rerolls == 1
    assert definition.draft_rules.generation_rerolls == 1
    assert definition.source is not None
    assert definition.source.game == "Pokémon Red and Blue"
    assert "KoalaBattle-authored" in definition.source.variant
    assert {
        stage.id: tuple(str(entry["species"]) for entry in _sets(stage.opponent_team))
        for stage in definition.stages
    } == EXPECTED_SPECIES
    assert all(stage.trainer_asset_id and stage.specialty for stage in definition.stages)
    assert definition.stages[0].trainer_asset_id == "brock-gen1rb"


def test_every_opponent_set_is_a_complete_competitive_set() -> None:
    definition = _definition("kanto-gym-gauntlet")

    for stage in definition.stages:
        for entry in _sets(stage.opponent_team):
            label = f"{stage.id}/{entry['species']}"
            assert entry["ability"], label
            assert entry["item"], label
            assert entry["nature"] in NATURES, label
            assert entry["evs"], label
            total = sum(int(part.split(" ")[0]) for part in str(entry["evs"]).split(" / "))
            assert 500 <= total <= 510, f"{label} allocates {total} EVs"
            moves = entry["moves"]
            assert isinstance(moves, list) and len(moves) == 4, label


def test_the_elite_four_is_one_gauntlet_and_every_gym_heals_first() -> None:
    """Losing a Pokemon to Lorelei has to still matter when Bruno walks in."""
    definition = _definition("kanto-gym-gauntlet")
    heals = {stage.id: stage.full_heal_before for stage in definition.stages}

    assert heals["lorelei"] is True, "arriving at the Plateau heals"
    assert all(heals[stage] is False for stage in ("bruno", "agatha", "lance", "champion-blue"))
    gyms = [stage.id for stage in definition.stages[:8]]
    assert all(heals[stage] is True for stage in gyms), gyms


def test_every_trainer_fields_six_so_no_stage_is_a_numbers_advantage() -> None:
    """The player always brings six. An opponent with three made early stages trivial."""
    definition = _definition("kanto-gym-gauntlet")
    sizes = {stage.id: len(_sets(stage.opponent_team)) for stage in definition.stages}
    levels = [stage.level for stage in definition.stages]

    assert set(sizes.values()) == {6}, sizes
    assert levels == sorted(levels), levels


def test_kanto_opponent_sets_are_regression_locked() -> None:
    payload = json.dumps(_source_snapshot(), sort_keys=True, separators=(",", ":")).encode()

    assert hashlib.sha256(payload).hexdigest() == (
        "378bfbace9602724fc94c62e52291ee78fdae80ccd8ba8054bb07e4a45291b6a"
    )


def test_challenge_format_only_relaxes_misc_obtainability() -> None:
    format_config = (
        Path(__file__).resolve().parents[3] / "showdown/config/custom-formats.js"
    ).read_text()

    assert "'!Obtainable Misc'" in format_config
    assert "'!Obtainable Moves'" not in format_config
    assert "'!Obtainable Abilities'" not in format_config
    assert "'!Obtainable Formes'" not in format_config
