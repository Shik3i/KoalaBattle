from __future__ import annotations

import random

from koalabattle.challenges.domain import _weighted_sample
from koalabattle.challenges.models import DraftCandidate
from koalabattle.challenges.rarity import (
    DraftRarity,
    load_draft_points,
    rarity_for_candidate,
    rarity_for_points,
)


def _candidate(entry_id: str, rarity: DraftRarity) -> DraftCandidate:
    return DraftCandidate(
        entry_id=entry_id,
        species=entry_id.title(),
        showdown_id=entry_id,
        base_species_id=entry_id,
        national_dex_number=1,
        introduction_generation=1,
        types=("normal",),
        draft_points=1 if rarity is DraftRarity.COMMON else 20,
        draft_rarity=rarity,
    )


def _evolved_candidate(entry_id: str, stage: int) -> DraftCandidate:
    return _candidate(entry_id, DraftRarity.COMMON).model_copy(update={"evolution_stage": stage})


def test_committed_smogon_snapshot_is_large_versioned_and_hash_validated() -> None:
    snapshot = load_draft_points()

    assert snapshot.schema_version == "1.0"
    assert snapshot.updated_on == "2026-08-22"
    assert len(snapshot.points) >= 1_000
    assert len(snapshot.banned) >= 40
    assert snapshot.points["charizard"] > snapshot.points["butterfree"]


def test_draft_points_map_to_five_explicit_rarity_tiers() -> None:
    assert [rarity_for_points(points) for points in (3, 4, 6, 7, 10, 11, 15, 16)] == [
        DraftRarity.COMMON,
        DraftRarity.UNCOMMON,
        DraftRarity.UNCOMMON,
        DraftRarity.RARE,
        DraftRarity.RARE,
        DraftRarity.SUPER_RARE,
        DraftRarity.SUPER_RARE,
        DraftRarity.ULTRA_RARE,
    ]


def test_legendary_tier_base_stats_have_a_scarcity_floor() -> None:
    assert rarity_for_candidate(3, 580) is DraftRarity.SUPER_RARE
    assert rarity_for_candidate(3, 600) is DraftRarity.ULTRA_RARE
    assert rarity_for_candidate(3, 500) is DraftRarity.COMMON


def test_is_legendary_floors_rarity_even_at_low_bst_and_points() -> None:
    # Some Restricted Legendary / Sub-Legendary species (e.g. Kubfu, Cosmog) have a modest BST,
    # so the points/BST calculation alone would otherwise rate them as common.
    assert rarity_for_candidate(3, 300, is_legendary=False) is DraftRarity.COMMON
    assert rarity_for_candidate(3, 300, is_legendary=True) is DraftRarity.SUPER_RARE
    # The flag only floors the tier; it never demotes a species points/BST already rate higher.
    assert rarity_for_candidate(16, 300, is_legendary=True) is DraftRarity.ULTRA_RARE
    assert rarity_for_candidate(3, 600, is_legendary=True) is DraftRarity.ULTRA_RARE


def test_ultra_rare_candidates_are_statistically_less_frequent_across_seeds() -> None:
    common = _candidate("common", DraftRarity.COMMON)
    ultra = _candidate("ultra", DraftRarity.ULTRA_RARE)
    counts = {common.entry_id: 0, ultra.entry_id: 0}

    for seed in range(5_000):
        picked = _weighted_sample(random.Random(seed), (common, ultra), 1)[0]
        counts[picked.entry_id] += 1

    assert counts["common"] > counts["ultra"] * 5


def test_already_evolved_forms_are_much_rarer_than_base_forms() -> None:
    base = _evolved_candidate("base", 0)
    middle = _evolved_candidate("middle", 1)
    final = _evolved_candidate("final", 2)
    counts = {item.entry_id: 0 for item in (base, middle, final)}

    for seed in range(10_000):
        picked = _weighted_sample(random.Random(seed), (base, middle, final), 1)[0]
        counts[picked.entry_id] += 1

    assert counts["base"] > counts["middle"] * 3
    assert counts["middle"] > counts["final"] * 2
