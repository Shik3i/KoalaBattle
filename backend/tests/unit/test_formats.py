from __future__ import annotations

import json
from uuid import uuid4

import pytest

from koalabattle.core.models import (
    AgentType,
    MatchConfig,
    PlayerConfig,
    Side,
    TeamPolicy,
    TeamSource,
)
from koalabattle.formats import (
    FormatCatalogService,
    build_catalog,
    capability,
    default_catalog,
    describe_format,
    expand_query,
    group_by_generation,
    load_snapshot,
    search_formats,
)
from koalabattle.formats.catalog import SNAPSHOT_PATH


def test_snapshot_is_generated_from_showdown_and_covers_every_generation() -> None:
    catalog = load_snapshot()
    generations = {item.generation for item in catalog.formats}
    assert generations == set(range(1, 10))
    # The registry is far larger than a hand-maintained allowlist would ever be.
    assert catalog.format_count > 250
    assert catalog.source == "showdown-snapshot"


@pytest.mark.parametrize(
    "format_id",
    [
        "gen1randombattle",
        "gen1ou",
        "gen2randombattle",
        "gen3ou",
        "gen4ou",
        "gen5ou",
        "gen6ou",
        "gen7ou",
        "gen8ou",
        "gen9randombattle",
        "gen9ou",
    ],
)
def test_acceptance_formats_are_present_and_runnable(format_id: str) -> None:
    descriptor = describe_format(format_id)
    assert descriptor is not None, format_id
    assert descriptor.supported, descriptor.unsupported_reason
    assert descriptor.game_type == "singles"


def test_generation_mechanics_match_the_generation() -> None:
    gen1 = describe_format("gen1ou")
    gen9 = describe_format("gen9ou")
    assert gen1 is not None and gen9 is not None
    assert not gen1.mechanics.items
    assert not gen1.mechanics.abilities
    assert not gen1.mechanics.physical_special_split
    assert not gen1.mechanics.terastallization
    assert gen9.mechanics.items
    assert gen9.mechanics.abilities
    assert gen9.mechanics.physical_special_split
    assert gen9.mechanics.terastallization
    gen3 = describe_format("gen3ou")
    assert gen3 is not None
    assert gen3.mechanics.items and gen3.mechanics.abilities
    assert not gen3.mechanics.physical_special_split


def test_non_singles_formats_are_listed_but_marked_unsupported() -> None:
    doubles = describe_format("gen9doublesou")
    assert doubles is not None
    assert not doubles.supported
    assert doubles.unsupported_reason is not None
    assert "renderer" in doubles.unsupported_reason
    catalog = default_catalog()
    game_types = {item.game_type for item in catalog.formats}
    # Every Showdown game type stays visible; only the isolated campaign Doubles format
    # joins the generally supported Singles catalog.
    assert {"doubles", "triples", "multi", "freeforall"} <= game_types
    supported_doubles = [
        item.id for item in catalog.formats if item.supported and item.game_type == "doubles"
    ]
    assert supported_doubles == ["gen9koalabattlecanonicalnatdexdraftdoubles"]


def test_capability_explains_each_refusal() -> None:
    assert capability({"game_type": "singles", "player_count": 2}) == (True, None)
    supported, reason = capability({"game_type": "doubles", "player_count": 2})
    assert not supported and reason and "doubles" in reason
    assert capability(
        {
            "id": "gen9koalabattlecanonicalnatdexdraftdoubles",
            "game_type": "doubles",
            "player_count": 2,
        }
    ) == (True, None)
    supported, reason = capability({"game_type": "singles", "player_count": 4})
    assert not supported and reason and "two players" in reason
    supported, reason = capability(
        {"game_type": "singles", "player_count": 2, "challenge_visible": False}
    )
    assert not supported and reason and "challenges" in reason


def test_grouping_orders_generations_and_puts_common_tiers_first() -> None:
    groups = group_by_generation(default_catalog().formats)
    assert [group.generation for group in groups] == list(range(9, 0, -1))
    gen9 = next(group for group in groups if group.generation == 9)
    assert gen9.formats[0].id == "gen9randombattle"
    assert gen9.formats[1].id == "gen9ou"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("gen 1", "gen1randombattle"),
        ("rby", "gen1randombattle"),
        ("gen1 ou", "gen1ou"),
        ("dpp ou", "gen4ou"),
        ("ou", "gen9ou"),
        ("random", "gen9randombattle"),
        ("uu", "gen9uu"),
    ],
)
def test_search_returns_the_obvious_format_first(query: str, expected: str) -> None:
    hits = search_formats(default_catalog().formats, query)
    assert hits and hits[0].id == expected


def test_search_prefix_matching_never_confuses_ou_with_doubles() -> None:
    hits = search_formats(default_catalog().formats, "ou")
    assert all(item.id.endswith("ou") or "ou" in item.display_name.casefold() for item in hits[:5])
    assert "gen9doublesuu" not in {item.id for item in hits[:5]}


def test_expand_query_understands_generation_shorthand() -> None:
    assert expand_query("gen 1") == ("gen1",)
    assert expand_query("RBY random") == ("gen1", "random")
    assert expand_query("  ") == ()


def test_unknown_or_unsupported_formats_are_refused_by_match_config() -> None:
    players = (
        PlayerConfig(side=Side.P1, display_name="Alpha", agent_type=AgentType.RANDOM),
        PlayerConfig(side=Side.P2, display_name="Beta", agent_type=AgentType.RANDOM),
    )
    gen1 = MatchConfig(format="gen1randombattle", players=players)
    assert gen1.generation == 1
    assert gen1.team_policy is TeamPolicy.SHOWDOWN_RANDOM
    with pytest.raises(ValueError, match="pinned Pokemon Showdown registry"):
        MatchConfig(format="not-a-format", players=players)
    with pytest.raises(ValueError, match="not runnable"):
        MatchConfig(format="gen9doublesou", players=players, team_policy=TeamPolicy.FIXED)


def test_custom_team_formats_require_a_validated_snapshot() -> None:
    players = (
        PlayerConfig(side=Side.P1, display_name="Alpha", agent_type=AgentType.RANDOM),
        PlayerConfig(side=Side.P2, display_name="Beta", agent_type=AgentType.RANDOM),
    )
    with pytest.raises(ValueError, match="requires validated custom teams"):
        MatchConfig(format="gen1ou", players=players)
    with pytest.raises(ValueError, match="supplies its own teams"):
        MatchConfig(format="gen1randombattle", players=players, team_policy=TeamPolicy.FIXED)
    imported = PlayerConfig(
        side=Side.P1,
        display_name="Alpha",
        agent_type=AgentType.RANDOM,
        team_source=TeamSource.PRESET,
        team_snapshot_id=uuid4(),
    )
    with pytest.raises(ValueError, match="cannot supply custom teams"):
        MatchConfig(format="gen1randombattle", players=(imported, players[1]))


def test_generation_is_derived_and_cannot_be_spoofed() -> None:
    players = (
        PlayerConfig(side=Side.P1, display_name="Alpha", agent_type=AgentType.RANDOM),
        PlayerConfig(side=Side.P2, display_name="Beta", agent_type=AgentType.RANDOM),
    )
    config = MatchConfig(format="gen4randombattle", generation=9, players=players)
    assert config.generation == 4


def test_service_falls_back_to_the_snapshot_when_showdown_is_unreachable() -> None:
    service = FormatCatalogService("http://127.0.0.1:9", timeout_seconds=0.2)
    import asyncio

    catalog = asyncio.run(service.refresh())
    assert catalog.source == "showdown-snapshot"
    assert catalog.format_count > 250
    assert service.require_supported("gen1ou").id == "gen1ou"
    with pytest.raises(ValueError, match="not runnable"):
        service.require_supported("gen9doublesou")


def test_malformed_payloads_are_rejected() -> None:
    with pytest.raises(ValueError, match="no formats"):
        build_catalog({"formats": []}, source="live")
    with pytest.raises(ValueError, match="no usable formats"):
        build_catalog({"formats": [{"name": "broken"}]}, source="live")


def test_snapshot_file_stays_machine_generated() -> None:
    payload = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.2"
    # Every entry carries the fields the Showdown tools server emits, not hand-written ones.
    for entry in payload["formats"][:20]:
        assert {"id", "name", "generation", "game_type", "mechanics"} <= set(entry)


def test_dex_names_resolve_ids_to_showdown_display_names() -> None:
    from koalabattle.formats import ability_name, item_name

    assert ability_name("ironfist") == "Iron Fist"
    assert ability_name("moldbreaker") == "Mold Breaker"
    assert item_name("heavydutyboots") == "Heavy-Duty Boots"
    assert item_name("lifeorb") == "Life Orb"
    # Unknown values fall back to the input rather than inventing a name.
    assert ability_name("notarealability") == "notarealability"
    assert ability_name(None) is None
    assert item_name("") is None
