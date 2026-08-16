"""Display names for abilities and items, generated from the pinned Showdown build.

Showdown reports these as IDs on a battle request (`ironfist`, `heavydutyboots`), and only
its Dex knows they read as "Iron Fist" and "Heavy-Duty Boots". poke-env ships no equivalent
table, so the names are snapshotted alongside the format catalog and refreshed by the same
script.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

DEX_NAMES_PATH = Path(__file__).with_name("showdown-dex-names.json")


@lru_cache(maxsize=1)
def _tables() -> tuple[dict[str, str], dict[str, str]]:
    if not DEX_NAMES_PATH.is_file():
        return {}, {}
    payload = json.loads(DEX_NAMES_PATH.read_text(encoding="utf-8"))
    abilities = payload.get("abilities")
    items = payload.get("items")
    return (
        abilities if isinstance(abilities, dict) else {},
        items if isinstance(items, dict) else {},
    )


def _identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def ability_name(value: str | None) -> str | None:
    """Resolve an ability ID to its Showdown display name, or fall back to the input."""
    if not value:
        return None
    return _tables()[0].get(_identifier(value), value)


def item_name(value: str | None) -> str | None:
    if not value:
        return None
    return _tables()[1].get(_identifier(value), value)
