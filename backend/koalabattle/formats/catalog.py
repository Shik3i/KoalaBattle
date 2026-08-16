from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

from .models import (
    FormatCatalog,
    FormatDescriptor,
    FormatGroup,
    FormatMechanics,
)

LOGGER = logging.getLogger(__name__)

SNAPSHOT_PATH = Path(__file__).with_name("showdown-format-catalog.json")

#: KoalaBattle normalizes exactly one active Pokemon per side, so only two-player singles
#: formats can be rendered, prompted and replayed correctly today.
SUPPORTED_GAME_TYPES = ("singles",)

_GAME_TYPE_REASONS = {
    "doubles": "Not yet supported by KoalaBattle battle renderer (doubles)",
    "triples": "Not yet supported by KoalaBattle battle renderer (triples)",
    "multi": "Not yet supported by KoalaBattle battle renderer (multi battles)",
    "freeforall": "Not yet supported by KoalaBattle battle renderer (free-for-all)",
}


def capability(descriptor: dict[str, Any]) -> tuple[bool, str | None]:
    """Decide whether KoalaBattle's normalized battle pipeline can run one Showdown format."""
    game_type = str(descriptor.get("game_type") or "singles")
    if game_type not in SUPPORTED_GAME_TYPES:
        reason = _GAME_TYPE_REASONS.get(
            game_type, f"Not yet supported by KoalaBattle battle renderer ({game_type})"
        )
        return False, reason
    if int(descriptor.get("player_count") or 2) != 2:
        return False, "Not yet supported by KoalaBattle battle renderer (more than two players)"
    if not descriptor.get("challenge_visible", True):
        return False, "The local Showdown server does not accept direct challenges in this format"
    return True, None


def _descriptor(payload: dict[str, Any]) -> FormatDescriptor:
    supported, reason = capability(payload)
    mechanics = payload.get("mechanics")
    return FormatDescriptor(
        id=str(payload["id"]),
        name=str(payload["name"]),
        display_name=str(payload.get("display_name") or payload["name"]),
        generation=int(payload["generation"]),
        mod=str(payload.get("mod") or f"gen{payload['generation']}"),
        section=str(payload.get("section") or "Other"),
        game_type=payload.get("game_type") or "singles",
        player_count=int(payload.get("player_count") or 2),
        team_source=str(payload.get("team_source") or "custom"),
        random_team=bool(payload.get("random_team", True)),
        custom_team_required=bool(payload.get("custom_team_required", False)),
        challenge_visible=bool(payload.get("challenge_visible", True)),
        tournament_visible=bool(payload.get("tournament_visible", True)),
        search_visible=bool(payload.get("search_visible", True)),
        rated=bool(payload.get("rated", False)),
        best_of_default=payload.get("best_of_default"),
        mechanics=(
            FormatMechanics.model_validate(mechanics)
            if isinstance(mechanics, dict)
            else FormatMechanics()
        ),
        supported=supported,
        unsupported_reason=reason,
    )


def build_catalog(payload: dict[str, Any], *, source: str) -> FormatCatalog:
    entries = payload.get("formats")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Showdown format payload contains no formats")
    formats = tuple(
        _descriptor(item) for item in entries if isinstance(item, dict) and item.get("id")
    )
    if not formats:
        raise ValueError("Showdown format payload contains no usable formats")
    return FormatCatalog(
        source="showdown-live" if source == "live" else "showdown-snapshot",
        showdown_version=str(payload.get("showdown_version") or "pinned-local-build"),
        format_count=len(formats),
        supported_count=sum(1 for item in formats if item.supported),
        supported_game_types=SUPPORTED_GAME_TYPES,
        formats=formats,
    )


def load_snapshot(path: Path = SNAPSHOT_PATH) -> FormatCatalog:
    """Load the catalog generated from the pinned Showdown build and shipped with the backend."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return build_catalog(payload, source="snapshot")


@lru_cache(maxsize=1)
def default_catalog() -> FormatCatalog:
    """The bundled snapshot, used wherever validation cannot await a live Showdown fetch."""
    return load_snapshot()


def describe_format(format_id: str) -> FormatDescriptor | None:
    normalized = format_id.strip().casefold()
    return next((item for item in default_catalog().formats if item.id == normalized), None)


class FormatCatalogService:
    """Serve the Showdown format registry, preferring the live pinned runtime when reachable."""

    def __init__(self, tools_url: str, *, timeout_seconds: float = 8.0) -> None:
        self.tools_url = tools_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._catalog: FormatCatalog | None = None

    @property
    def catalog(self) -> FormatCatalog:
        if self._catalog is None:
            self._catalog = load_snapshot()
        return self._catalog

    async def refresh(self) -> FormatCatalog:
        """Fetch the live registry; fall back to the bundled snapshot when Showdown is down."""
        import asyncio

        try:
            payload = await asyncio.to_thread(self._fetch)
            self._catalog = build_catalog(payload, source="live")
        except (OSError, ValueError, json.JSONDecodeError) as error:
            LOGGER.info("Falling back to the bundled Showdown format snapshot: %s", error)
            self._catalog = load_snapshot()
        return self._catalog

    def _fetch(self) -> dict[str, Any]:
        from urllib.request import Request, urlopen

        request = Request(f"{self.tools_url}/formats", headers={"Accept": "application/json"})
        with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
            payload = json.loads(response.read(8_000_000))
        if not isinstance(payload, dict):
            raise ValueError("Showdown format endpoint returned a non-object payload")
        return payload

    def get(self, format_id: str) -> FormatDescriptor | None:
        normalized = format_id.strip().casefold()
        return next((item for item in self.catalog.formats if item.id == normalized), None)

    def require(self, format_id: str) -> FormatDescriptor:
        descriptor = self.get(format_id)
        if descriptor is None:
            raise ValueError(f"unknown Showdown format {format_id!r}")
        return descriptor

    def require_supported(self, format_id: str) -> FormatDescriptor:
        descriptor = self.require(format_id)
        if not descriptor.supported:
            raise ValueError(
                f"{descriptor.name} is not runnable in KoalaBattle: {descriptor.unsupported_reason}"
            )
        return descriptor

    def supported(self) -> tuple[FormatDescriptor, ...]:
        return tuple(item for item in self.catalog.formats if item.supported)

    def grouped(self, *, supported_only: bool = False) -> tuple[FormatGroup, ...]:
        formats = self.supported() if supported_only else self.catalog.formats
        return group_by_generation(formats)

    def search(self, query: str, *, limit: int = 40) -> tuple[FormatDescriptor, ...]:
        return tuple(search_formats(self.catalog.formats, query)[:limit])


def group_by_generation(formats: Iterable[FormatDescriptor]) -> tuple[FormatGroup, ...]:
    buckets: dict[int, list[FormatDescriptor]] = {}
    for item in formats:
        buckets.setdefault(item.generation, []).append(item)
    return tuple(
        FormatGroup(
            generation=generation,
            label=f"Generation {generation}",
            formats=tuple(sorted(buckets[generation], key=_display_order)),
        )
        for generation in sorted(buckets, reverse=True)
    )


#: Ranking that keeps the formats people actually reach for at the top of each generation.
_PRIORITY = ("randombattle", "ou", "ubers", "uu", "ru", "nu", "pu", "lc", "monotype", "1v1")


def _display_order(descriptor: FormatDescriptor) -> tuple[int, str]:
    suffix = descriptor.id.removeprefix(f"gen{descriptor.generation}")
    try:
        rank = _PRIORITY.index(suffix)
    except ValueError:
        rank = len(_PRIORITY)
    return rank, descriptor.display_name.casefold()


#: Community shorthand the searchable selector should understand.
_ALIASES = {
    "rby": ("gen1",),
    "gsc": ("gen2",),
    "adv": ("gen3",),
    "rse": ("gen3",),
    "dpp": ("gen4",),
    "bw": ("gen5",),
    "b2w2": ("gen5",),
    "xy": ("gen6",),
    "oras": ("gen6",),
    "sm": ("gen7",),
    "usum": ("gen7",),
    "swsh": ("gen8",),
    "sv": ("gen9",),
    "rands": ("random",),
    "randbats": ("randombattle",),
}


def expand_query(query: str) -> tuple[str, ...]:
    """Turn a free-text query into normalized tokens, expanding generation shorthand."""
    raw = query.casefold().replace("-", " ").replace("_", " ").split()
    tokens: list[str] = []
    index = 0
    while index < len(raw):
        word = "".join(character for character in raw[index] if character.isalnum())
        if not word:
            index += 1
            continue
        # "gen 1" arrives as two words but means one token.
        if word == "gen" and index + 1 < len(raw) and raw[index + 1].isdigit():
            tokens.append(f"gen{raw[index + 1]}")
            index += 2
            continue
        tokens.extend(_ALIASES.get(word, (word,)))
        index += 1
    return tuple(tokens)


def _index_tokens(descriptor: FormatDescriptor) -> tuple[str, ...]:
    words = f"{descriptor.display_name} {descriptor.section}".casefold().replace("/", " ")
    return tuple(
        {
            descriptor.id,
            descriptor.id.removeprefix(f"gen{descriptor.generation}"),
            f"gen{descriptor.generation}",
            descriptor.game_type,
            *(
                "".join(character for character in word if character.isalnum())
                for word in words.split()
            ),
        }
        - {""}
    )


def search_formats(formats: Iterable[FormatDescriptor], query: str) -> list[FormatDescriptor]:
    """Prefix-match every query token against indexed words so "ou" never matches "doubles"."""
    tokens = expand_query(query)
    candidates = list(formats)
    if not tokens:
        return sorted(candidates, key=lambda item: (-item.generation, _display_order(item)))
    matches: list[tuple[int, FormatDescriptor]] = []
    for descriptor in candidates:
        indexed = _index_tokens(descriptor)
        if not all(any(word.startswith(token) for word in indexed) for token in tokens):
            continue
        exact = 0 if all(token in indexed for token in tokens) else 1
        matches.append((exact, descriptor))
    matches.sort(key=lambda item: (item[0], -item[1].generation, _display_order(item[1])))
    return [descriptor for _, descriptor in matches]
