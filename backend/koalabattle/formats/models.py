from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FORMAT_CATALOG_SCHEMA_VERSION = "1.0"

GameType = Literal["singles", "doubles", "triples", "multi", "freeforall"]


class FrozenFormatModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FormatMechanics(FrozenFormatModel):
    """Which battle mechanics exist in one format, as reported by the pinned Showdown build."""

    items: bool = False
    abilities: bool = False
    physical_special_split: bool = False
    mega_evolution: bool = False
    z_moves: bool = False
    dynamax: bool = False
    terastallization: bool = False
    hidden_power_types: bool = False
    natures: bool = False
    held_item_switching: bool = False

    #: Battle mechanics that need their own action to be usable. KoalaBattle only issues
    #: Terastallization today, so the others exist in the format but cannot be chosen.
    _OPTIONAL_MECHANIC_LABELS = {
        "mega_evolution": "Mega Evolution",
        "z_moves": "Z-Moves",
        "dynamax": "Dynamax",
        "terastallization": "Terastallization",
    }
    _ACTIONABLE = ("terastallization",)

    def actionable(self) -> tuple[str, ...]:
        """Mechanics an agent can actually select, because a legal action carries them."""
        return tuple(
            label
            for key, label in self._OPTIONAL_MECHANIC_LABELS.items()
            if key in self._ACTIONABLE and getattr(self, key)
        )

    def unavailable(self) -> tuple[str, ...]:
        """Mechanics this format has that KoalaBattle cannot issue an action for.

        Naming these is not pedantry: an agent told a mechanic is "available" will plan
        around a move it can never make, and an agent told nothing will be surprised when
        the opponent uses one.
        """
        return tuple(
            label
            for key, label in self._OPTIONAL_MECHANIC_LABELS.items()
            if key not in self._ACTIONABLE and getattr(self, key)
        )


class FormatDescriptor(FrozenFormatModel):
    """One normalized Showdown format plus KoalaBattle's own capability verdict."""

    schema_version: str = FORMAT_CATALOG_SCHEMA_VERSION
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=120)
    generation: int = Field(ge=1, le=9)
    mod: str = Field(min_length=1, max_length=40)
    section: str = Field(min_length=1, max_length=80)
    game_type: GameType = "singles"
    player_count: int = Field(default=2, ge=2, le=4)
    team_source: str = Field(default="custom", max_length=40)
    random_team: bool = True
    custom_team_required: bool = False
    challenge_visible: bool = True
    tournament_visible: bool = True
    search_visible: bool = True
    rated: bool = False
    best_of_default: bool | None = None
    mechanics: FormatMechanics = Field(default_factory=FormatMechanics)
    supported: bool = True
    unsupported_reason: str | None = Field(default=None, max_length=200)

    @property
    def generation_label(self) -> str:
        return f"Generation {self.generation}"

    @property
    def team_label(self) -> str:
        return "CUSTOM TEAM" if self.custom_team_required else "RANDOM TEAMS"

    def summary(self) -> str:
        return f"GEN {self.generation} · {self.team_label} · {self.game_type.upper()}"


class FormatGroup(FrozenFormatModel):
    generation: int = Field(ge=1, le=9)
    label: str
    formats: tuple[FormatDescriptor, ...]


class FormatCatalog(FrozenFormatModel):
    schema_version: str = FORMAT_CATALOG_SCHEMA_VERSION
    source: Literal["showdown-live", "showdown-snapshot"] = "showdown-snapshot"
    showdown_version: str = "pinned-local-build"
    format_count: int = Field(ge=0)
    supported_count: int = Field(ge=0)
    supported_game_types: tuple[GameType, ...] = ("singles",)
    formats: tuple[FormatDescriptor, ...] = ()
