from __future__ import annotations

import random

from koalabattle.challenges.domain import _weighted_sample
from koalabattle.challenges.models import DraftCandidate
from koalabattle.challenges.rarity import DraftRarity, load_draft_points, rarity_for_points


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


def test_committed_smogon_snapshot_is_large_versioned_and_hash_validated() -> None:
    snapshot = load_draft_points()

    assert snapshot.schema_version == "1.0"
    assert snapshot.updated_on == "2026-08-22"
    assert len(snapshot.points) >= 1_000
    assert len(snapshot.banned) >= 40
    assert snapshot.points["charizard"] > snapshot.points["butterfree"]


def test_draft_points_map_to_five_explicit_rarity_tiers() -> None:
    assert [rarity_for_points(points) for points in (4, 5, 8, 9, 12, 13, 16, 17)] == [
        DraftRarity.COMMON,
        DraftRarity.UNCOMMON,
        DraftRarity.UNCOMMON,
        DraftRarity.RARE,
        DraftRarity.RARE,
        DraftRarity.SUPER_RARE,
        DraftRarity.SUPER_RARE,
        DraftRarity.ULTRA_RARE,
    ]


def test_ultra_rare_candidates_are_statistically_less_frequent_across_seeds() -> None:
    common = _candidate("common", DraftRarity.COMMON)
    ultra = _candidate("ultra", DraftRarity.ULTRA_RARE)
    counts = {common.entry_id: 0, ultra.entry_id: 0}

    for seed in range(5_000):
        picked = _weighted_sample(random.Random(seed), (common, ultra), 1)[0]
        counts[picked.entry_id] += 1

    assert counts["common"] > counts["ultra"] * 5
