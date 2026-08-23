from __future__ import annotations

import asyncio
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from .models import (
    EvolutionTrigger,
    MegaEvolutionOption,
    PokemonAbility,
    PokemonBaseStats,
    ShowdownCompetitiveSet,
)


def showdown_id(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


class SpeciesMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    base_species_id: str
    national_dex_number: int = Field(ge=1)
    introduction_generation: int = Field(ge=1, le=9)
    # Lowest level at which the pinned Showdown set can be validated.  This captures both
    # evolution-level rules and event-origin restrictions that are not visible in the move list.
    minimum_level: int = Field(default=1, ge=1, le=100)
    types: tuple[str, ...] = Field(min_length=1, max_length=2)
    base_stat_total: int | None = Field(default=None, ge=1, le=2000)
    base_stats: PokemonBaseStats | None = None
    max_hp: int | None = Field(default=None, ge=1, le=999)
    abilities: tuple[PokemonAbility, ...] = ()
    recommended_moves: tuple[str, ...] = Field(default=(), max_length=4)
    showdown_set: ShowdownCompetitiveSet | None = None
    required_item: str | None = Field(default=None, min_length=1, max_length=120)
    battle_only: bool = False
    cosmetic: bool = False
    unavailable: bool = False
    is_mega: bool = False
    is_gmax: bool = False
    is_legendary: bool = False
    prevo_id: str | None = None
    evolves_to: tuple[EvolutionTrigger, ...] = ()
    mega_evolutions: tuple[MegaEvolutionOption, ...] = ()


_SPECIES = TypeAdapter(tuple[SpeciesMetadata, ...])


class SpeciesCatalogSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    showdown_version: str
    format: str
    format_generation: int = Field(ge=1, le=9)
    abilities_supported: bool
    species_count: int = Field(ge=1)
    species: tuple[SpeciesMetadata, ...]

    @model_validator(mode="after")
    def count_matches_species(self) -> SpeciesCatalogSnapshot:
        if self.species_count != len(self.species):
            raise ValueError("pinned Showdown species count does not match catalog")
        return self


class ShowdownSpeciesCatalog:
    FETCH_ATTEMPTS = 3
    FETCH_TIMEOUT_SECONDS = 5

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._snapshots: dict[str, SpeciesCatalogSnapshot] = {}

    async def snapshot(self, format_id: str) -> SpeciesCatalogSnapshot:
        if not re.fullmatch(r"[a-z0-9]+", format_id):
            raise ValueError("format id must be a normalized Showdown id")
        if format_id in self._snapshots:
            return self._snapshots[format_id]
        request = Request(
            f"{self.base_url}/dex-species?{urlencode({'format': format_id})}",
            headers={"Accept": "application/json"},
        )
        payload: object | None = None
        last_error: Exception | None = None
        for attempt in range(self.FETCH_ATTEMPTS):
            try:
                payload = await asyncio.to_thread(self._fetch, request)
                break
            except HTTPError as error:
                raise RuntimeError(
                    f"could not load species metadata from pinned Showdown: {error}"
                ) from error
            except (URLError, TimeoutError, OSError) as error:
                last_error = error
                if attempt + 1 < self.FETCH_ATTEMPTS:
                    await asyncio.sleep(0.2 * (attempt + 1))
        if last_error is not None:
            raise RuntimeError(
                f"could not load species metadata from pinned Showdown: {last_error}"
            ) from last_error
        if not isinstance(payload, dict) or not isinstance(payload.get("species"), list):
            raise RuntimeError("pinned Showdown returned an invalid species catalog")
        snapshot = SpeciesCatalogSnapshot.model_validate(
            {**payload, "species": _SPECIES.validate_python(payload["species"])}
        )
        self._snapshots[format_id] = snapshot
        return snapshot

    async def entries(self, format_id: str) -> tuple[SpeciesMetadata, ...]:
        return (await self.snapshot(format_id)).species

    @staticmethod
    def _fetch(request: Request) -> object:
        with urlopen(request, timeout=ShowdownSpeciesCatalog.FETCH_TIMEOUT_SECONDS) as response:  # noqa: S310
            return json.loads(response.read(8_000_000))

    def set_entries_for_test(
        self,
        entries: tuple[SpeciesMetadata, ...],
        *,
        format_id: str = "gen9natdexdraft",
        generation: int = 9,
        abilities_supported: bool = True,
    ) -> None:
        self._snapshots[format_id] = SpeciesCatalogSnapshot(
            schema_version="1.0",
            showdown_version="unit-test",
            format=format_id,
            format_generation=generation,
            abilities_supported=abilities_supported,
            species_count=len(entries),
            species=entries,
        )
