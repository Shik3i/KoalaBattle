"""Declarative, versioned presentation settings for a production.

A :class:`ProductionStyle` describes *how* a replay should look and sound. It never
describes *what* happened: battle events, decisions, teams and the winner are owned by the
match archive and are untouched by anything in this module. One match may therefore carry
any number of productions, each with its own style, and rendering one can never change
another.

Every field here has to survive the trip to the native offline compositor, so the model
stays declarative — bounded enumerations and numbers, never CSS, markup or file paths.
Assets are referenced by generated :class:`~koalabattle.branding.models.BrandAsset` ids.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

STYLE_SCHEMA_VERSION = "1.0"

#: A CSS-safe colour. Only `#rgb` / `#rrggbb` is accepted so a style can never smuggle
#: arbitrary CSS (`url(...)`, `expression(...)`) into a rendering surface.
Color = Annotated[str, Field(pattern=r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")]
AssetId = Annotated[str, Field(pattern=r"^[a-z0-9]{32}$")]
PresetId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,58}[a-z0-9]$")]


class FrozenStyleModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Intensity(StrEnum):
    OFF = "off"
    MINIMAL = "minimal"
    STANDARD = "standard"
    DRAMATIC = "dramatic"


class FontFamily(StrEnum):
    """Curated font choices.

    These are local stacks rather than downloaded webfonts: the offline renderer must not
    depend on a network fetch, and KoalaBattle must not redistribute fonts it has no
    licence to ship. Users who want a specific typeface add it themselves as a font asset.
    """

    SYSTEM = "system"
    GEOMETRIC = "geometric"
    GROTESK = "grotesk"
    SERIF = "serif"
    MONO = "mono"
    PIXEL = "pixel"
    CUSTOM = "custom"


class BackgroundStyle(FrozenStyleModel):
    kind: Literal["arena", "solid", "gradient", "image"] = "arena"
    color: Color = "#0b1f24"
    secondary_color: Color = "#06090f"
    asset_id: AssetId | None = None
    fit: Literal["cover", "contain"] = "cover"
    position: Literal["center", "top", "bottom", "left", "right"] = "center"
    brightness: float = Field(default=1.0, ge=0.2, le=1.6)
    contrast: float = Field(default=1.0, ge=0.5, le=1.8)
    blur: int = Field(default=0, ge=0, le=40)
    overlay_opacity: float = Field(default=0.0, ge=0.0, le=0.9)
    vignette: float = Field(default=0.35, ge=0.0, le=1.0)


class StageStyle(FrozenStyleModel):
    background: BackgroundStyle = Field(default_factory=BackgroundStyle)
    arena: Literal["none", "stadium", "platform", "minimal-floor", "grid"] = "grid"
    floor_visible: bool = True
    ground_shadow: bool = True
    stage_lighting: float = Field(default=0.6, ge=0.0, le=1.0)
    ambient_intensity: float = Field(default=0.6, ge=0.0, le=1.0)
    background_motion: bool = True
    accent: Color = "#7dffae"


class HudStyle(FrozenStyleModel):
    preset: Literal["broadcast", "fighting", "minimal", "esports", "retro"] = "broadcast"
    hp_shape: Literal["slash", "rounded", "square", "pill"] = "slash"
    hp_thickness: int = Field(default=31, ge=8, le=54)
    damage_ghost: bool = True
    show_hp_percent: bool = True
    show_hp_exact: bool = True
    show_level: bool = False
    show_types: bool = True
    show_status: bool = True
    show_player_name: bool = True
    show_provider: bool = True
    show_logo: bool = True
    show_player_slot: bool = False
    #: ``revealed`` only shows opponent Pokemon the spectator has already seen. Nothing in
    #: this enum can widen visibility beyond the public presentation archive.
    team_indicators: Literal["full", "revealed", "fainted-only", "hidden"] = "full"
    show_turn: bool = True
    show_weather: bool = True


class TypographyStyle(FrozenStyleModel):
    display: FontFamily = FontFamily.SYSTEM
    body: FontFamily = FontFamily.SYSTEM
    mono: FontFamily = FontFamily.MONO
    display_asset_id: AssetId | None = None
    body_asset_id: AssetId | None = None
    scale: float = Field(default=1.0, ge=0.8, le=1.3)
    display_weight: int = Field(default=950, ge=400, le=950)
    letter_spacing: float = Field(default=0.0, ge=-2.0, le=6.0)
    uppercase: bool = True
    outline: bool = False
    shadow: bool = True


class MoveCalloutStyle(FrozenStyleModel):
    layout: Literal["banner", "impact", "minimal", "lower-third", "centered", "off"] = "banner"
    show_type: bool = True
    show_archetype: bool = True
    duration_scale: float = Field(default=1.0, ge=0.5, le=2.0)


class DamageStyle(FrozenStyleModel):
    show_damage: bool = True
    show_healing: bool = True
    show_effectiveness: bool = True
    show_critical: bool = True
    show_miss: bool = True
    show_immune: bool = True
    intensity: Intensity = Intensity.STANDARD


class CommentaryStyle(FrozenStyleModel):
    layout: Literal["fighter-card", "side-panel", "lower-third", "bubble", "caption", "off"] = (
        "fighter-card"
    )
    show_agent_name: bool = True
    show_logo: bool = True
    show_label: bool = True
    animation: Literal["fade", "slide", "punch", "minimal", "none"] = "fade"


class CaptionStyle(FrozenStyleModel):
    preset: Literal["broadcast", "minimal", "high-contrast", "vertical", "off"] = "broadcast"
    show_speaker: bool = False
    background_opacity: float = Field(default=0.88, ge=0.0, le=1.0)
    outline: bool = False
    size_scale: float = Field(default=1.0, ge=0.7, le=1.5)
    position: Literal["bottom", "center", "top"] = "bottom"


class EffectStyle(FrozenStyleModel):
    intensity: Intensity = Intensity.STANDARD
    camera: Literal["static", "subtle", "dynamic"] = "subtle"
    idle_motion: Literal["full", "subtle", "off"] = "full"
    pacing: Literal["cinematic", "standard", "fast"] = "standard"
    impact_flash: bool = True
    trails: bool = True


class IntroStyle(FrozenStyleModel):
    enabled: bool = True
    length: Literal["quick", "standard", "dramatic"] = "standard"
    show_player_logos: bool = True
    show_player_names: bool = True
    show_format: bool = True
    show_generation: bool = True
    show_game_number: bool = False
    show_series_score: bool = False
    show_tournament_round: bool = False

    @property
    def duration_ms(self) -> int:
        return {"quick": 1600, "standard": 3200, "dramatic": 5000}[self.length]


class ResultStyle(FrozenStyleModel):
    enabled: bool = True
    show_winner: bool = True
    show_logos: bool = True
    show_final_score: bool = False
    show_format: bool = True
    show_series: bool = False
    duration_ms: int = Field(default=3600, ge=800, le=12_000)


class WatermarkStyle(FrozenStyleModel):
    enabled: bool = False
    asset_id: AssetId | None = None
    text: str | None = Field(default=None, max_length=40)
    position: Literal["top-left", "top-right", "bottom-left", "bottom-right"] = "bottom-right"
    opacity: float = Field(default=0.55, ge=0.05, le=1.0)
    size: float = Field(default=1.0, ge=0.5, le=2.0)


class ParticipantBranding(FrozenStyleModel):
    """How one player is presented. Deliberately independent of which provider runs them.

    A Manual Web Chat player driven by a human pasting into ChatGPT may legitimately be
    presented as "ChatGPT"; a generic OpenAI-compatible endpoint may be presented as
    "My Local Model". Provider implementation and on-screen identity are separate concerns.
    """

    display_name: str | None = Field(default=None, min_length=1, max_length=40)
    short_name: str | None = Field(default=None, min_length=1, max_length=12)
    logo_asset_id: AssetId | None = None
    #: A bundled neutral provider mark (see ``koalabattle.branding.marks``).
    logo_mark: str | None = Field(default=None, max_length=24)
    accent: Color | None = None
    secondary_accent: Color | None = None


class SeriesDisplay(FrozenStyleModel):
    tournament_name: str | None = Field(default=None, max_length=60)
    round_name: str | None = Field(default=None, max_length=40)
    game_number: int | None = Field(default=None, ge=1, le=99)
    best_of: int | None = Field(default=None, ge=1, le=99)
    score_p1: int | None = Field(default=None, ge=0, le=99)
    score_p2: int | None = Field(default=None, ge=0, le=99)


class ProductionStyle(FrozenStyleModel):
    schema_version: str = STYLE_SCHEMA_VERSION
    id: PresetId = "koala-broadcast"
    display_name: str = Field(default="Koala Broadcast", min_length=1, max_length=60)
    version: str = Field(default="1.0", max_length=20)
    builtin: bool = True
    title: str | None = Field(default=None, min_length=1, max_length=90)
    show_format: bool = True
    show_generation: bool = True
    show_koala_branding: bool = True
    stage: StageStyle = Field(default_factory=StageStyle)
    hud: HudStyle = Field(default_factory=HudStyle)
    typography: TypographyStyle = Field(default_factory=TypographyStyle)
    move: MoveCalloutStyle = Field(default_factory=MoveCalloutStyle)
    damage: DamageStyle = Field(default_factory=DamageStyle)
    commentary: CommentaryStyle = Field(default_factory=CommentaryStyle)
    caption: CaptionStyle = Field(default_factory=CaptionStyle)
    effect: EffectStyle = Field(default_factory=EffectStyle)
    intro: IntroStyle = Field(default_factory=IntroStyle)
    result: ResultStyle = Field(default_factory=ResultStyle)
    watermark: WatermarkStyle = Field(default_factory=WatermarkStyle)
    players: dict[str, ParticipantBranding] = Field(default_factory=dict)
    series: SeriesDisplay = Field(default_factory=SeriesDisplay)

    def asset_ids(self) -> tuple[str, ...]:
        """Every brand asset this style needs, for preflight and manifest snapshots."""
        candidates = [
            self.stage.background.asset_id,
            self.typography.display_asset_id,
            self.typography.body_asset_id,
            self.watermark.asset_id,
            *(branding.logo_asset_id for branding in self.players.values()),
        ]
        seen: dict[str, None] = {}
        for candidate in candidates:
            if candidate:
                seen.setdefault(candidate, None)
        return tuple(seen)

    def branding_for(self, side: str) -> ParticipantBranding:
        return self.players.get(side, ParticipantBranding())


class StylePreset(FrozenStyleModel):
    """A saved, reusable style. Built-in presets are read-only; users duplicate them."""

    id: PresetId
    display_name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=200)
    builtin: bool = False
    style: ProductionStyle
    created_at: str | None = None
    updated_at: str | None = None


class SaveStylePreset(FrozenStyleModel):
    display_name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=200)
    style: ProductionStyle


class UpdateProductionStyle(FrozenStyleModel):
    style: ProductionStyle
