from __future__ import annotations

import hashlib
import json
from pathlib import Path

from koalabattle.challenges.service import _definition, _definition_summaries

# Species are authored per trainer theme. Roster size and set quality escalate; these are
# regression-locked so a later stage can never quietly become smaller or weaker.
EXPECTED_FILLED_SPECIES = {
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

EXPECTED_ORIGINAL_SPECIES = {
    "brock": ("Geodude", "Onix"),
    "misty": ("Staryu", "Starmie"),
    "lt-surge": ("Voltorb", "Pikachu", "Raichu"),
    "erika": ("Victreebel", "Tangela", "Vileplume"),
    "koga": ("Koffing", "Muk", "Koffing", "Weezing"),
    "sabrina": ("Kadabra", "Mr. Mime", "Venomoth", "Alakazam"),
    "blaine": ("Growlithe", "Ponyta", "Rapidash", "Arcanine"),
    "giovanni": ("Rhyhorn", "Dugtrio", "Nidoqueen", "Nidoking", "Rhydon"),
    "lorelei": ("Dewgong", "Cloyster", "Slowbro", "Jynx", "Lapras"),
    "bruno": ("Onix", "Hitmonchan", "Hitmonlee", "Onix", "Machamp"),
    "agatha": ("Gengar", "Golbat", "Haunter", "Arbok", "Gengar"),
    "lance": ("Gyarados", "Dragonair", "Dragonair", "Aerodactyl", "Dragonite"),
    "champion-blue": ("Pidgeot", "Alakazam", "Rhydon", "Gyarados", "Exeggutor", "Charizard"),
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
        {
            "id": stage.id,
            "level": stage.level,
            "original_team": _sets(stage.opponent_team),
            "filled_team": _sets(stage.filled_opponent_team or stage.opponent_team),
        }
        for stage in definition.stages
    ]


def test_kanto_content_offers_original_and_filled_teams() -> None:
    definition = _definition("kanto-gym-gauntlet")

    assert definition.version == "15.0.0"
    assert definition.draft_rules.rerolls == 3
    assert definition.draft_rules.type_rerolls == 1
    assert definition.draft_rules.generation_rerolls == 1
    assert definition.source is not None
    assert definition.source.game == "Pokémon Red and Blue"
    assert "English Red/Blue teams" in definition.source.variant
    assert {
        stage.id: tuple(str(entry["species"]) for entry in _sets(stage.opponent_team))
        for stage in definition.stages
    } == EXPECTED_ORIGINAL_SPECIES
    assert {
        stage.id: tuple(
            str(entry["species"])
            for entry in _sets(stage.filled_opponent_team or stage.opponent_team)
        )
        for stage in definition.stages
    } == EXPECTED_FILLED_SPECIES
    assert all(stage.trainer_asset_id and stage.specialty for stage in definition.stages)
    assert definition.stages[0].trainer_asset_id == "brock-gen1rb"


def test_original_sets_preserve_moves_and_filled_sets_are_competitive() -> None:
    definition = _definition("kanto-gym-gauntlet")

    for stage in definition.stages:
        for entry in _sets(stage.opponent_team):
            label = f"{stage.id}/{entry['species']}"
            assert entry["ability"], label
            moves = entry["moves"]
            assert isinstance(moves, list) and 2 <= len(moves) <= 4, label
        assert stage.filled_opponent_team is not None
        for entry in _sets(stage.filled_opponent_team):
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


def test_original_team_sizes_scale_with_progress_and_filled_teams_have_six() -> None:
    definition = _definition("kanto-gym-gauntlet")
    original_sizes = [len(_sets(stage.opponent_team)) for stage in definition.stages]
    filled_sizes = {
        stage.id: len(_sets(stage.filled_opponent_team or stage.opponent_team))
        for stage in definition.stages
    }
    levels = [stage.level for stage in definition.stages]

    assert original_sizes == [2, 2, 3, 3, 4, 4, 4, 5, 5, 5, 5, 5, 6]
    assert set(filled_sizes.values()) == {6}, filled_sizes
    assert levels == sorted(levels), levels


def test_kanto_opponent_sets_are_regression_locked() -> None:
    payload = json.dumps(_source_snapshot(), sort_keys=True, separators=(",", ":")).encode()

    assert hashlib.sha256(payload).hexdigest() == (
        "599699e9a1bed961e6f57352f9224ae902142a81beef70603c799710c6cc8bd5"
    )


def test_challenge_format_only_relaxes_misc_obtainability() -> None:
    format_config = (
        Path(__file__).resolve().parents[3] / "showdown/config/custom-formats.js"
    ).read_text()

    assert "'!Obtainable Misc'" in format_config
    assert "'!Obtainable Moves'" not in format_config
    assert "'!Obtainable Abilities'" not in format_config
    assert "'!Obtainable Formes'" not in format_config


def test_all_regional_campaign_packs_are_registered_and_canonical() -> None:
    summaries = _definition_summaries()
    by_id = {item.id: item for item in summaries}
    expected = {
        "kanto-gym-gauntlet": ("Kanto", 1, 13),
        "johto-gym-gauntlet": ("Johto", 2, 13),
        "hoenn-gym-gauntlet": ("Hoenn", 3, 13),
        "sinnoh-gym-gauntlet": ("Sinnoh", 4, 13),
        "unova-gym-gauntlet": ("Unova", 5, 13),
        "kalos-gym-gauntlet": ("Kalos", 6, 13),
        "alola-trial-gauntlet": ("Alola", 7, 9),
        "galar-gym-gauntlet": ("Galar", 8, 10),
        "paldea-gym-gauntlet": ("Paldea", 9, 13),
    }
    for definition_id, (region, generation, stage_count) in expected.items():
        assert definition_id in by_id
        summary = by_id[definition_id]
        assert (summary.region, summary.generation, summary.stage_count) == (
            region,
            generation,
            stage_count,
        )
        definition = _definition(definition_id)
        assert all(
            stage.opponent_team and stage.filled_opponent_team for stage in definition.stages
        )
        assert all(
            len(_sets(stage.filled_opponent_team or "")) == 6 for stage in definition.stages
        )

    multi = by_id["all-generations-gauntlet"]
    assert multi.campaign_kind == "multi-generation"
    assert multi.stage_count == sum(item[2] for item in expected.values())
