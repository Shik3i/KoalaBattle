from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

PokemonPerspective = Literal["front", "back"]
PokemonAssetKind = Literal["sprite", "icon"]


class AssetResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    species_id: str
    perspective: PokemonPerspective
    animated: bool
    kind: PokemonAssetKind
    found: bool
    relative_path: str | None = None
    resolved_path: str | None = None


class AssetCategoryStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    directory: str
    files: int
    installed: bool


class AssetScanReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    root: str
    valid: bool
    pokemon_species: int
    categories: dict[str, AssetCategoryStatus]
    invalid_files: tuple[str, ...]
    unresolved_species: tuple[str, ...]


class AssetProvider(Protocol):
    def pokemon(
        self,
        species: str,
        *,
        perspective: PokemonPerspective = "front",
        animated: bool = False,
        kind: PokemonAssetKind = "sprite",
    ) -> Path | None: ...


def normalize_species_id(species: str) -> str:
    """Return a filesystem-safe canonical identifier compatible with Showdown IDs."""
    gendered = species.casefold().replace("♀", "f").replace("♂", "m")
    ascii_name = unicodedata.normalize("NFKD", gendered).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", ascii_name)


def _legacy_species_id(species: str) -> str:
    normalized = unicodedata.normalize("NFKD", species.casefold())
    return re.sub(r"[^a-z0-9-]", "", normalized.replace(" ", "-"))


class LocalAssetProvider:
    """Resolve optional user-supplied media without assuming a copyrighted source."""

    _allowed_extensions = (".webp", ".png", ".gif", ".svg", ".jpg", ".jpeg")
    _audio_extensions = (".wav", ".ogg", ".mp3")
    _category_paths = {
        "pokemon_front": Path("pokemon/front"),
        "pokemon_back": Path("pokemon/back"),
        "pokemon_animated": Path("pokemon/animated"),
        "pokemon_icons": Path("pokemon/icons"),
        "trainers": Path("trainers"),
        "backgrounds": Path("backgrounds"),
        "effects": Path("effects"),
        "audio": Path("audio"),
    }

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._unresolved_species: set[str] = set()

    def resolve_pokemon(
        self,
        species: str,
        *,
        perspective: PokemonPerspective = "front",
        animated: bool = False,
        kind: PokemonAssetKind = "sprite",
    ) -> AssetResolution:
        species_id = normalize_species_id(species)
        if not species_id:
            self._unresolved_species.add("(invalid)")
            return AssetResolution(
                species_id=species_id,
                perspective=perspective,
                animated=animated,
                kind=kind,
                found=False,
            )

        for relative in self._pokemon_candidates(
            species,
            species_id=species_id,
            perspective=perspective,
            animated=animated,
            kind=kind,
        ):
            candidate = (self.root / relative).resolve()
            if candidate.is_relative_to(self.root) and candidate.is_file():
                return AssetResolution(
                    species_id=species_id,
                    perspective=perspective,
                    animated=animated,
                    kind=kind,
                    found=True,
                    relative_path=relative.as_posix(),
                    resolved_path=str(candidate),
                )

        self._unresolved_species.add(species_id)
        return AssetResolution(
            species_id=species_id,
            perspective=perspective,
            animated=animated,
            kind=kind,
            found=False,
        )

    def pokemon(
        self,
        species: str,
        *,
        perspective: PokemonPerspective = "front",
        animated: bool = False,
        kind: PokemonAssetKind = "sprite",
    ) -> Path | None:
        resolution = self.resolve_pokemon(
            species,
            perspective=perspective,
            animated=animated,
            kind=kind,
        )
        return Path(resolution.resolved_path) if resolution.resolved_path else None

    def audio(self, effect_id: str) -> Path | None:
        """Resolve one curated SFX id without accepting arbitrary local paths."""
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", effect_id):
            return None
        for extension in self._audio_extensions:
            candidate = (self.root / "audio" / f"{effect_id}{extension}").resolve()
            if candidate.is_relative_to(self.root) and candidate.is_file():
                return candidate
        return None

    def scan(self) -> AssetScanReport:
        categories: dict[str, AssetCategoryStatus] = {}
        invalid_files: list[str] = []
        pokemon_species: set[str] = set()

        for name, relative in self._category_paths.items():
            directory = (self.root / relative).resolve()
            count = 0
            if directory.is_relative_to(self.root) and directory.is_dir():
                for path in directory.rglob("*"):
                    if not path.is_file():
                        continue
                    relative_file = path.relative_to(self.root).as_posix()
                    allowed_extensions = (
                        self._audio_extensions if name == "audio" else self._allowed_extensions
                    )
                    if path.suffix.casefold() not in allowed_extensions:
                        invalid_files.append(relative_file)
                        continue
                    count += 1
                    if name.startswith("pokemon_"):
                        pokemon_species.add(normalize_species_id(path.stem))
            categories[name] = AssetCategoryStatus(
                directory=relative.as_posix(),
                files=count,
                installed=count > 0,
            )

        return AssetScanReport(
            root=str(self.root),
            valid=self.root.is_dir() and not invalid_files,
            pokemon_species=len(pokemon_species - {""}),
            categories=categories,
            invalid_files=tuple(sorted(invalid_files)),
            unresolved_species=tuple(sorted(self._unresolved_species)),
        )

    def _pokemon_candidates(
        self,
        species: str,
        *,
        species_id: str,
        perspective: PokemonPerspective,
        animated: bool,
        kind: PokemonAssetKind,
    ) -> tuple[Path, ...]:
        ids = tuple(dict.fromkeys((species_id, _legacy_species_id(species))))
        directories: list[Path]
        if kind == "icon":
            directories = [Path("pokemon/icons")]
        elif animated:
            directories = [
                Path("pokemon/animated") / perspective,
                Path("pokemon/animated"),
                Path("pokemon") / perspective,
            ]
        else:
            directories = [Path("pokemon") / perspective]
        if kind == "sprite":
            directories.append(Path("pokemon"))
        return tuple(
            directory / f"{identifier}{extension}"
            for directory in directories
            for identifier in ids
            for extension in self._allowed_extensions
            if identifier
        )
