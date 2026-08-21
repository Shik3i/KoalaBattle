from __future__ import annotations

import asyncio
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class SpeciesMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    base_species_id: str
    national_dex_number: int = Field(ge=1)
    introduction_generation: int = Field(ge=1, le=9)
    types: tuple[str, ...] = Field(min_length=1, max_length=2)
    base_stat_total: int | None = Field(default=None, ge=1, le=2000)
    battle_only: bool = False
    cosmetic: bool = False
    unavailable: bool = False
    is_mega: bool = False
    is_gmax: bool = False


_SPECIES = TypeAdapter(tuple[SpeciesMetadata, ...])


class ShowdownSpeciesCatalog:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._entries: tuple[SpeciesMetadata, ...] | None = None

    async def entries(self) -> tuple[SpeciesMetadata, ...]:
        if self._entries is not None:
            return self._entries
        request = Request(f"{self.base_url}/dex-species", headers={"Accept": "application/json"})
        try:
            payload = await asyncio.to_thread(self._fetch, request)
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            raise RuntimeError(
                f"could not load species metadata from pinned Showdown: {error}"
            ) from error
        if not isinstance(payload, dict) or not isinstance(payload.get("species"), list):
            raise RuntimeError("pinned Showdown returned an invalid species catalog")
        self._entries = _SPECIES.validate_python(payload["species"])
        return self._entries

    @staticmethod
    def _fetch(request: Request) -> object:
        with urlopen(request, timeout=15) as response:  # noqa: S310
            return json.loads(response.read(8_000_000))

    def set_entries_for_test(self, entries: tuple[SpeciesMetadata, ...]) -> None:
        self._entries = entries
