from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DraftRarity(StrEnum):
    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    SUPER_RARE = "super-rare"
    ULTRA_RARE = "ultra-rare"


RARITY_WEIGHTS: dict[DraftRarity, float] = {
    DraftRarity.COMMON: 1.0,
    DraftRarity.UNCOMMON: 0.55,
    DraftRarity.RARE: 0.22,
    DraftRarity.SUPER_RARE: 0.07,
    DraftRarity.ULTRA_RARE: 0.015,
}


def rarity_for_points(points: int) -> DraftRarity:
    if points <= 3:
        return DraftRarity.COMMON
    if points <= 6:
        return DraftRarity.UNCOMMON
    if points <= 10:
        return DraftRarity.RARE
    if points <= 15:
        return DraftRarity.SUPER_RARE
    return DraftRarity.ULTRA_RARE


def rarity_for_candidate(points: int, base_stat_total: int | None) -> DraftRarity:
    """Apply a hard scarcity floor to legendary-tier stat lines.

    Draft points measure competitive value, not legendary status. A high-BST legendary could
    therefore otherwise land in a merely rare bucket. The floor keeps 570+ BST species scarce
    even when the upstream points snapshot underrates them.
    """
    rarity = rarity_for_points(points)
    if base_stat_total is not None and base_stat_total >= 600:
        return DraftRarity.ULTRA_RARE
    if base_stat_total is not None and base_stat_total >= 570:
        return max((rarity, DraftRarity.SUPER_RARE), key=lambda item: list(DraftRarity).index(item))
    return rarity


class DraftPointsSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    source_name: str = Field(min_length=1, max_length=200)
    source_url: str = Field(min_length=1, max_length=500)
    source_sha256: str = Field(min_length=64, max_length=64)
    sheet: str = Field(min_length=1, max_length=100)
    column: str = Field(min_length=1, max_length=40)
    updated_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    catalog_hash: str = Field(min_length=64, max_length=64)
    points: dict[str, int]
    banned: tuple[str, ...] = ()

    @model_validator(mode="after")
    def hash_matches_payload(self) -> DraftPointsSnapshot:
        material = json.dumps(
            {"points": self.points, "banned": self.banned},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        if hashlib.sha256(material).hexdigest() != self.catalog_hash:
            raise ValueError("draft-points snapshot catalog hash mismatch")
        return self


@lru_cache(maxsize=1)
def load_draft_points() -> DraftPointsSnapshot:
    path = Path(__file__).with_name("content") / "smogon-draft-points.json"
    return DraftPointsSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
