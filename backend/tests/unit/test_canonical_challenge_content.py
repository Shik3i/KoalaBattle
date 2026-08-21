from __future__ import annotations

import hashlib
import json

from koalabattle.challenges.service import _definition

EXPECTED_SPECIES = {
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
    "champion-blue": (
        "Pidgeot",
        "Alakazam",
        "Rhydon",
        "Gyarados",
        "Exeggutor",
        "Charizard",
    ),
}


def _source_snapshot() -> list[dict[str, object]]:
    definition = _definition("kanto-gym-gauntlet")
    snapshot: list[dict[str, object]] = []
    for stage in definition.stages:
        team: list[dict[str, object]] = []
        for block in stage.opponent_team.split("\n\n"):
            lines = block.splitlines()
            team.append(
                {
                    "species": lines[0],
                    "level": next(
                        line.removeprefix("Level: ") for line in lines if line.startswith("Level: ")
                    ),
                    "moves": [line.removeprefix("- ") for line in lines if line.startswith("- ")],
                }
            )
        snapshot.append({"id": stage.id, "team": team})
    return snapshot


def test_kanto_content_uses_sourced_red_blue_rosters() -> None:
    definition = _definition("kanto-gym-gauntlet")

    assert definition.version == "3.0.0"
    assert definition.source.game == "Pokémon Red and Blue"
    assert definition.source.generation == 1
    assert "Champion Blue when the player chose Bulbasaur" in definition.source.variant
    assert {
        stage.id: tuple(block.splitlines()[0] for block in stage.opponent_team.split("\n\n"))
        for stage in definition.stages
    } == EXPECTED_SPECIES
    assert all(stage.trainer_asset_id and stage.specialty for stage in definition.stages)
    assert definition.stages[0].trainer_asset_id == "brock-gen1rb"


def test_kanto_source_levels_and_moves_are_regression_locked() -> None:
    payload = json.dumps(_source_snapshot(), sort_keys=True, separators=(",", ":")).encode()

    assert hashlib.sha256(payload).hexdigest() == (
        "b99985260c37ae8d6066c725d0ef5f0fbc33fdba4736531e0cbd745a641c75d2"
    )
