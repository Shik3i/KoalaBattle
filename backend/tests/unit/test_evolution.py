from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest

from koalabattle.challenges.domain import attach_offer
from koalabattle.challenges.models import (
    BattleControllerSnapshot,
    ChallengeRun,
    ChallengeStatus,
    DraftCandidate,
    DraftControllerKind,
    DraftControllerSnapshot,
    DraftPick,
    DraftPoolSnapshot,
    EvolutionTrigger,
    EvSpread,
    MegaEvolutionOption,
    PokemonAbility,
    PokemonIvSpread,
    ShowdownCompetitiveSet,
)
from koalabattle.challenges.repository import ChallengeRepository
from koalabattle.challenges.service import (
    ChallengeService,
    _advance_evolutions,
    _current_species_id,
    _definition,
    _evolution_branches,
    _mega_options,
    _opponent_mega_choices,
    _resolve_evolution_path,
    _validated_opponent_stage_team,
    _with_evolutions,
    _with_selected_item,
)
from koalabattle.challenges.species import ShowdownSpeciesCatalog, SpeciesMetadata
from koalabattle.core.models import AgentType
from koalabattle.storage import Database
from koalabattle.teams.models import TeamValidationResult

# A tiny synthetic chain: Basic --level 30--> Middle --level 60--> Final, plus a
# Branch mon that splits into BranchA/BranchB with no level of its own (an item trigger).


def _species(
    species_id: str,
    name: str,
    *,
    evolves_to: tuple[EvolutionTrigger, ...] = (),
    showdown_set: ShowdownCompetitiveSet | None = None,
) -> SpeciesMetadata:
    return SpeciesMetadata(
        id=species_id,
        name=name,
        base_species_id=species_id,
        national_dex_number=1,
        introduction_generation=1,
        types=("normal",),
        evolves_to=evolves_to,
        showdown_set=showdown_set,
    )


def _set(species: str, moves: tuple[str, ...] = ("Tackle",)) -> ShowdownCompetitiveSet:
    return ShowdownCompetitiveSet(
        source="showdown-dex-validated",
        source_generation=9,
        source_tier="Format legal",
        species=species,
        item="Leftovers",
        ability="Overgrow",
        nature="Adamant",
        moves=moves,
        evs=EvSpread(),
        ivs=PokemonIvSpread(),
    )


SPECIES_BY_ID = {
    "basic": _species(
        "basic",
        "Basic",
        evolves_to=(
            EvolutionTrigger(id="middle", name="Middle", trigger_level=30, trigger_kind="level"),
        ),
    ),
    "middle": _species(
        "middle",
        "Middle",
        showdown_set=_set("Middle"),
        evolves_to=(
            EvolutionTrigger(id="final", name="Final", trigger_level=60, trigger_kind="level"),
        ),
    ),
    "final": _species("final", "Final", showdown_set=_set("Final", ("Frenzy Plant",))),
    "brancher": _species(
        "brancher",
        "Brancher",
        evolves_to=(
            EvolutionTrigger(id="brancha", name="BranchA", trigger_kind="useItem"),
            EvolutionTrigger(id="branchb", name="BranchB", trigger_kind="useItem"),
        ),
    ),
    "brancha": _species("brancha", "BranchA", showdown_set=_set("BranchA")),
    "branchb": _species("branchb", "BranchB", showdown_set=_set("BranchB")),
    "static": _species("static", "Static"),
}


def test_non_branching_chain_resolves_fully_without_a_choice() -> None:
    path = _resolve_evolution_path("basic", None, SPECIES_BY_ID)
    assert path == ("basic", "middle", "final")


def test_a_species_with_no_evolutions_resolves_to_itself() -> None:
    assert _resolve_evolution_path("static", None, SPECIES_BY_ID) == ("static",)


def test_evolution_branches_reports_only_the_branch_species_options() -> None:
    assert _evolution_branches("basic", SPECIES_BY_ID) == ()
    assert _evolution_branches("static", SPECIES_BY_ID) == ()
    branches = _evolution_branches("brancher", SPECIES_BY_ID)
    assert {option.id for option in branches} == {"brancha", "branchb"}


def test_a_branch_without_a_choice_stops_the_path_at_the_branch_point() -> None:
    assert _resolve_evolution_path("brancher", None, SPECIES_BY_ID) == ("brancher",)


def test_a_branch_with_a_choice_resolves_past_it() -> None:
    assert _resolve_evolution_path("brancher", "branchb", SPECIES_BY_ID) == (
        "brancher",
        "branchb",
    )


def test_an_invalid_choice_is_ignored_and_the_path_still_stops_at_the_branch() -> None:
    assert _resolve_evolution_path("brancher", "final", SPECIES_BY_ID) == ("brancher",)


def test_mega_options_are_derived_from_the_persisted_current_species() -> None:
    pick = _pick("charizard", "Charmander", "charmander", ("charmander", "charizard"))
    pick = pick.model_copy(update={"current_species": "Charizard", "evolution_stage_index": 1})
    metadata = _species("charizard", "Charizard").model_copy(
        update={
            "mega_evolutions": (
                MegaEvolutionOption(
                    id="charizardmegax",
                    species="Charizard-Mega-X",
                    required_item="Charizardite X",
                ),
                MegaEvolutionOption(
                    id="charizardmegay",
                    species="Charizard-Mega-Y",
                    required_item="Charizardite Y",
                ),
            )
        }
    )

    mega_x = _species("charizardmegax", "Charizard-Mega-X").model_copy(
        update={"is_mega": True, "required_item": "Charizardite X"}
    )
    mega_y = _species("charizardmegay", "Charizard-Mega-Y").model_copy(
        update={"is_mega": True, "required_item": "Charizardite Y"}
    )
    options = _mega_options(
        cast(ChallengeRun, _FakeRun((pick,))),
        {"charizard": metadata, "charizardmegax": mega_x, "charizardmegay": mega_y},
    )

    assert [option.mega_species_id for option in options] == [
        "charizardmegax",
        "charizardmegay",
    ]
    assert options[0].required_item == "Charizardite X"


def test_mega_options_exclude_forms_marked_unavailable_by_the_format() -> None:
    pick = _pick("chandelure", "Chandelure", "chandelure", ("chandelure",))
    metadata = _species("chandelure", "Chandelure").model_copy(
        update={
            "mega_evolutions": (
                MegaEvolutionOption(
                    id="chandeluremega",
                    species="Chandelure-Mega",
                    required_item="Chandelurite",
                ),
            )
        }
    )
    unavailable = _species("chandeluremega", "Chandelure-Mega").model_copy(
        update={"is_mega": True, "unavailable": True, "required_item": "Chandelurite"}
    )

    options = _mega_options(
        cast(ChallengeRun, _FakeRun((pick,))),
        {"chandelure": metadata, "chandeluremega": unavailable},
    )

    assert options == ()


def test_selected_mega_stone_replaces_only_the_exact_species_item() -> None:
    export = (
        "Ace (Charizard) @ Heavy-Duty Boots\nAbility: Blaze\n- Flamethrower\n\n"
        "Blastoise @ Leftovers\nAbility: Torrent\n- Surf"
    )

    rewritten = _with_selected_item(export, "Charizard", "Charizardite X")

    assert rewritten.splitlines()[0] == "Ace (Charizard) @ Charizardite X"
    assert "Blastoise @ Leftovers" in rewritten


@pytest.mark.asyncio
async def test_opponent_mega_skips_an_illegal_duplicate_and_uses_the_next_set() -> None:
    gengar = _species("gengar", "Gengar").model_copy(
        update={
            "mega_evolutions": (
                MegaEvolutionOption(
                    id="gengarmega", species="Gengar-Mega", required_item="Gengarite"
                ),
            )
        }
    )
    mega = _species("gengarmega", "Gengar-Mega").model_copy(
        update={"is_mega": True, "required_item": "Gengarite"}
    )
    team = "Gengar\n- Hypnosis\n- Shadow Ball\n\nGengar\n- Toxic\n- Shadow Ball"

    class SleepClauseValidator:
        async def validate(self, team_text: str, format_id: str) -> TeamValidationResult:
            first = team_text.split("\n\n", 1)[0]
            valid = not ("@ Gengarite" in first and "- Hypnosis" in first)
            return TeamValidationResult(
                format=format_id,
                valid=valid,
                errors=()
                if valid
                else (
                    "Gengar 1 (Gengar) has the combination of Hypnosis + Gengarite, "
                    "which is banned by Sleep Clause Mod.",
                ),
                normalized_export=team_text if valid else None,
                packed_team="packed" if valid else None,
            )

    choices = _opponent_mega_choices(team, {"gengar": gengar, "gengarmega": mega})
    selected, validation = await _validated_opponent_stage_team(
        team,
        {"gengar": gengar, "gengarmega": mega},
        {"gengar": 1},
        60,
        "gen9natdexdraft",
        SleepClauseValidator(),
        try_mega=True,
    )

    assert choices == (("Gengar", "Gengarite", 0), ("Gengar", "Gengarite", 1))
    assert validation.valid
    assert selected.split("\n\n")[0].splitlines()[0] == "Gengar"
    assert selected.split("\n\n")[1].splitlines()[0] == "Gengar @ Gengarite"


def _candidate(entry_id: str, species: str, showdown_id: str) -> DraftCandidate:
    return DraftCandidate(
        entry_id=entry_id,
        species=species,
        showdown_id=showdown_id,
        base_species_id=showdown_id,
        national_dex_number=1,
        introduction_generation=1,
        types=("normal",),
    )


def _pick(entry_id: str, species: str, showdown_id: str, path: tuple[str, ...]) -> DraftPick:
    return DraftPick(
        round=1,
        offer_fingerprint="a" * 64,
        candidate=_candidate(entry_id, species, showdown_id),
        selected_by=DraftControllerKind.HUMAN,
        evolution_path=path,
    )


def test_advance_evolutions_applies_at_most_one_level_gated_step() -> None:
    pick = _pick("mon1", "Basic", "basic", ("basic", "middle", "final"))
    picks, events = _advance_evolutions(
        _FakeRun((pick,)), next_stage_index=1, next_stage_level=30, species_by_id=SPECIES_BY_ID
    )
    assert picks[0].evolution_stage_index == 1
    assert picks[0].current_species == "Middle"
    assert events[0].to_species == "Middle"

    # A level far beyond the *next* step still advances only one stage per transition —
    # Middle -> Final requires level 60, reached here, but this is evaluated at the next
    # transition, never two steps in the same call.
    picks2, events2 = _advance_evolutions(
        _FakeRun(picks), next_stage_index=2, next_stage_level=59, species_by_id=SPECIES_BY_ID
    )
    assert picks2[0].evolution_stage_index == 1  # not yet: 59 < 60
    assert events2 == ()

    picks3, events3 = _advance_evolutions(
        _FakeRun(picks2), next_stage_index=3, next_stage_level=60, species_by_id=SPECIES_BY_ID
    )
    assert picks3[0].evolution_stage_index == 2
    assert picks3[0].current_species == "Final"


def test_non_level_evolution_uses_the_level_50_fallback() -> None:
    pick = _pick("mon1", "BranchA", "brancha", ("brancher", "brancha"))
    # brancher -> brancha is a useItem trigger (no level); level 49 is still too early.
    picks, events = _advance_evolutions(
        _FakeRun((pick,)), next_stage_index=1, next_stage_level=49, species_by_id=SPECIES_BY_ID
    )
    assert picks[0].evolution_stage_index == 0
    assert events == ()

    picks2, events2 = _advance_evolutions(
        _FakeRun((pick,)), next_stage_index=2, next_stage_level=50, species_by_id=SPECIES_BY_ID
    )
    assert picks2[0].evolution_stage_index == 1
    assert events2[0].to_species == "BranchA"


def test_a_legacy_pick_with_no_resolved_path_never_evolves() -> None:
    pick = _pick("mon1", "Basic", "basic", ())
    picks, events = _advance_evolutions(
        _FakeRun((pick,)), next_stage_index=5, next_stage_level=100, species_by_id=SPECIES_BY_ID
    )
    assert picks[0].evolution_stage_index == 0
    assert events == ()


def test_current_species_id_reads_the_resolved_stage_of_the_path() -> None:
    pick = _pick("mon1", "Basic", "basic", ("basic", "middle", "final"))
    assert _current_species_id(pick) == "basic"
    evolved = pick.model_copy(update={"evolution_stage_index": 2})
    assert _current_species_id(evolved) == "final"
    assert _current_species_id(_pick("mon2", "Static", "static", ())) == "static"


def test_with_evolutions_rewrites_only_the_evolved_blocks_and_keeps_evs() -> None:
    export = (
        "Basic\n"
        "Ability: Overgrow\n"
        "EVs: 252 Atk / 252 Spe / 4 HP\n"
        "Adamant Nature\n"
        "- Tackle\n"
        "\n"
        "Static\n"
        "Ability: Levitate\n"
        "EVs: 252 HP\n"
        "Bold Nature\n"
        "- Growl"
    )
    evolved_pick = _pick("mon1", "Basic", "basic", ("basic", "middle", "final")).model_copy(
        update={"evolution_stage_index": 2}
    )
    unevolved_pick = _pick("mon2", "Static", "static", ())
    result = _with_evolutions(export, _FakeRun((evolved_pick, unevolved_pick)), SPECIES_BY_ID)
    blocks = result.split("\n\n")
    assert blocks[0].splitlines()[0] == "Final @ Leftovers"
    assert "EVs: 252 Atk / 252 Spe / 4 HP" in blocks[0]  # Training EVs survive evolution
    assert "- Frenzy Plant" in blocks[0]
    # The un-evolved Pokemon's block is untouched, byte for byte.
    assert blocks[1] == export.split("\n\n")[1]


def test_with_evolutions_replaces_ivs_with_the_hidden_power_target_set() -> None:
    hidden_power_set = _set("Final", ("Hidden Power Rock",)).model_copy(
        update={
            "ivs": PokemonIvSpread(defense=30, spd=30, spe=30),
            "tera_type": "Rock",
        }
    )
    species_by_id = {
        **SPECIES_BY_ID,
        "final": SPECIES_BY_ID["final"].model_copy(
            update={"showdown_set": hidden_power_set}
        ),
    }
    export = (
        "Basic\n"
        "Ability: Overgrow\n"
        "EVs: 252 SpA / 252 Spe / 4 SpD\n"
        "Modest Nature\n"
        "IVs: 0 Atk\n"
        "- Tackle"
    )
    evolved_pick = _pick("mon1", "Basic", "basic", ("basic", "middle", "final")).model_copy(
        update={"evolution_stage_index": 2}
    )

    result = _with_evolutions(export, _FakeRun((evolved_pick,)), species_by_id)

    assert "EVs: 252 SpA / 252 Spe / 4 SpD" in result
    assert "IVs: 30 Def / 30 SpD / 30 Spe" in result
    assert "IVs: 0 Atk" not in result
    assert "Tera Type: Rock" in result
    assert "- Hidden Power Rock" in result


class _FakeRun:
    """The tiny slice of ChallengeRun the pure evolution helpers actually read."""

    def __init__(self, picks: tuple[DraftPick, ...]) -> None:
        self.picks = picks


def _branch_candidate() -> DraftCandidate:
    return DraftCandidate(
        entry_id="brancher",
        species="Brancher",
        showdown_id="brancher",
        base_species_id="brancher",
        national_dex_number=1,
        introduction_generation=1,
        types=("normal",),
        abilities=(PokemonAbility(slot="0", id="overgrow", name="Overgrow"),),
        showdown_set=_set("Brancher"),
        evolves_to=(
            EvolutionTrigger(id="brancha", name="BranchA", trigger_kind="useItem"),
            EvolutionTrigger(id="branchb", name="BranchB", trigger_kind="useItem"),
        ),
    )


def _decoy_candidate() -> DraftCandidate:
    return DraftCandidate(
        entry_id="static",
        species="Static",
        showdown_id="static",
        base_species_id="static",
        national_dex_number=2,
        introduction_generation=1,
        types=("normal",),
        showdown_set=_set("Static"),
    )


def _branching_run() -> ChallengeRun:
    now = datetime.now(UTC)
    definition = _definition("kanto-gym-gauntlet").model_copy(
        update={
            "draft_rules": _definition("kanto-gym-gauntlet").draft_rules.model_copy(
                update={
                    "roster_size": 2,
                    "rerolls": 0,
                    "type_rerolls": 0,
                    "generation_rerolls": 0,
                    "choice_count": 2,
                }
            )
        }
    )
    candidate = _branch_candidate()
    run = ChallengeRun(
        id=uuid4(),
        name="Evolution branch fixture",
        definition=definition,
        status=ChallengeStatus.DRAFTING,
        seed=1,
        draft_pool=DraftPoolSnapshot(
            showdown_version="unit-test",
            format=definition.format,
            format_generation=9,
            abilities_supported=True,
            catalog_hash="b" * 64,
            candidates=(candidate, _decoy_candidate()),
        ),
        draft_controller=DraftControllerSnapshot(kind=DraftControllerKind.HUMAN),
        battle_controller=BattleControllerSnapshot(agent_type=AgentType.HUMAN),
        opponent_controller=BattleControllerSnapshot(agent_type=AgentType.RANDOM),
        rerolls_remaining=0,
        type_rerolls_remaining=0,
        generation_rerolls_remaining=0,
        created_at=now,
        updated_at=now,
    )
    # The safe-offer rule intentionally exposes only one identity here. Pick a deterministic
    # fixture seed whose single option is the branching species; rarity weighting must not make
    # this evolution test depend on a historical RNG result.
    for seed in range(100):
        offered = attach_offer(run.model_copy(update={"seed": seed}))
        if any(option.entry_id == "brancher" for option in offered.current_offer.options):
            return offered
    raise AssertionError("branching fixture could not produce the expected offer")


@pytest.mark.asyncio
async def test_a_human_pick_of_a_branching_species_requires_a_valid_choice(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'evo.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    run = _branching_run()
    assert run.current_offer is not None
    entry_id = next(o.entry_id for o in run.current_offer.options if o.entry_id == "brancher")
    await repository.create(run)
    catalog = ShowdownSpeciesCatalog("http://127.0.0.1:9")
    catalog.set_entries_for_test(tuple(SPECIES_BY_ID.values()), format_id=run.definition.format)
    service = ChallengeService(repository, catalog, cast(Any, None))

    with pytest.raises(ValueError, match="evolution_choice"):
        await service.pick(run.id, entry_id, run.current_offer.fingerprint, run.revision)

    picked = await service.pick(
        run.id,
        entry_id,
        run.current_offer.fingerprint,
        run.revision,
        evolution_choice="branchb",
    )
    assert picked.picks[0].evolution_path == ("brancher", "branchb")


@pytest.mark.asyncio
async def test_random_controlled_drafting_never_stalls_on_an_unresolved_branch(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'evo-random.db'}")
    await database.create_schema()
    repository = ChallengeRepository(database)
    run = _branching_run().model_copy(
        update={"draft_controller": DraftControllerSnapshot(kind=DraftControllerKind.RANDOM)}
    )
    assert run.current_offer is not None
    entry_id = next(o.entry_id for o in run.current_offer.options if o.entry_id == "brancher")
    await repository.create(run)
    catalog = ShowdownSpeciesCatalog("http://127.0.0.1:9")
    catalog.set_entries_for_test(tuple(SPECIES_BY_ID.values()), format_id=run.definition.format)
    service = ChallengeService(repository, catalog, cast(Any, None))

    picked = await service.pick(
        run.id,
        entry_id,
        run.current_offer.fingerprint,
        run.revision,
        selected_by=DraftControllerKind.RANDOM,
    )
    assert picked.picks[0].evolution_path == ("brancher", "brancha")
