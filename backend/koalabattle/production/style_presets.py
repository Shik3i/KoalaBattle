"""Built-in production styles.

Presets are meant to be *compositions*, not one-setting variations: a user picking
"Fighting" instead of "Minimal" should get a different-looking video, not a different
corner radius. Each entry below therefore changes stage, HUD, typography, callouts,
commentary and effects together.

Built-ins are read-only. The Studio duplicates one into a user preset for editing, so an
experiment can never destroy the baseline a user came back to.
"""

from __future__ import annotations

from .style import (
    BackgroundStyle,
    CaptionStyle,
    CommentaryStyle,
    DamageStyle,
    EffectStyle,
    FontFamily,
    HudStyle,
    Intensity,
    IntroStyle,
    MoveCalloutStyle,
    ProductionStyle,
    ResultStyle,
    StageStyle,
    StylePreset,
    TypographyStyle,
)

KOALA_BROADCAST = ProductionStyle(
    id="koala-broadcast",
    display_name="Koala Broadcast",
    stage=StageStyle(
        background=BackgroundStyle(kind="arena", color="#0b1f24", secondary_color="#06090f"),
        arena="grid",
        accent="#7dffae",
    ),
    hud=HudStyle(preset="broadcast", hp_shape="slash", hp_thickness=31),
    typography=TypographyStyle(display=FontFamily.SYSTEM, mono=FontFamily.MONO),
    move=MoveCalloutStyle(layout="banner"),
    commentary=CommentaryStyle(layout="fighter-card"),
    caption=CaptionStyle(preset="broadcast"),
    effect=EffectStyle(intensity=Intensity.STANDARD, camera="subtle"),
    intro=IntroStyle(enabled=True, length="standard"),
    result=ResultStyle(enabled=True),
)

FIGHTING = ProductionStyle(
    id="fighting",
    display_name="Fighting",
    stage=StageStyle(
        background=BackgroundStyle(
            kind="gradient", color="#2b0714", secondary_color="#07060f", vignette=0.6
        ),
        arena="stadium",
        stage_lighting=0.95,
        ambient_intensity=0.8,
        accent="#ff4d5e",
    ),
    hud=HudStyle(
        preset="fighting",
        hp_shape="pill",
        hp_thickness=44,
        damage_ghost=True,
        show_hp_exact=False,
        show_player_slot=True,
        show_provider=False,
    ),
    typography=TypographyStyle(
        display=FontFamily.GEOMETRIC,
        body=FontFamily.GROTESK,
        display_weight=950,
        letter_spacing=2.0,
        outline=True,
        scale=1.12,
    ),
    move=MoveCalloutStyle(layout="impact", duration_scale=1.25),
    damage=DamageStyle(intensity=Intensity.DRAMATIC),
    commentary=CommentaryStyle(layout="lower-third", animation="punch", show_label=False),
    caption=CaptionStyle(preset="high-contrast", outline=True, size_scale=1.1),
    effect=EffectStyle(intensity=Intensity.DRAMATIC, camera="dynamic", pacing="standard"),
    intro=IntroStyle(enabled=True, length="dramatic", show_game_number=True),
    result=ResultStyle(enabled=True, duration_ms=4200),
)

MINIMAL = ProductionStyle(
    id="minimal",
    display_name="Minimal",
    show_koala_branding=False,
    stage=StageStyle(
        background=BackgroundStyle(
            kind="solid", color="#0d1013", secondary_color="#0d1013", vignette=0.15
        ),
        arena="minimal-floor",
        stage_lighting=0.3,
        ambient_intensity=0.25,
        background_motion=False,
        accent="#cfd8d3",
    ),
    hud=HudStyle(
        preset="minimal",
        hp_shape="rounded",
        hp_thickness=14,
        show_provider=False,
        show_types=False,
        show_logo=False,
        team_indicators="fainted-only",
        show_weather=False,
    ),
    typography=TypographyStyle(
        display=FontFamily.GROTESK,
        display_weight=700,
        uppercase=False,
        shadow=False,
        scale=0.92,
    ),
    move=MoveCalloutStyle(layout="minimal", show_archetype=False),
    damage=DamageStyle(intensity=Intensity.MINIMAL, show_effectiveness=False),
    commentary=CommentaryStyle(layout="off"),
    caption=CaptionStyle(preset="minimal", background_opacity=0.55, size_scale=0.9),
    effect=EffectStyle(intensity=Intensity.MINIMAL, camera="static", idle_motion="subtle"),
    intro=IntroStyle(enabled=False, length="quick"),
    result=ResultStyle(enabled=True, show_logos=False, duration_ms=2200),
)

RETRO = ProductionStyle(
    id="retro",
    display_name="Retro",
    stage=StageStyle(
        background=BackgroundStyle(
            kind="gradient", color="#22301c", secondary_color="#0a1208", vignette=0.2
        ),
        arena="platform",
        stage_lighting=0.2,
        ambient_intensity=0.2,
        background_motion=False,
        accent="#9bbc0f",
    ),
    hud=HudStyle(
        preset="retro",
        hp_shape="square",
        hp_thickness=22,
        damage_ghost=False,
        show_hp_exact=True,
        show_level=True,
        show_provider=False,
        show_logo=False,
        team_indicators="revealed",
    ),
    typography=TypographyStyle(
        display=FontFamily.PIXEL,
        body=FontFamily.PIXEL,
        mono=FontFamily.PIXEL,
        display_weight=700,
        letter_spacing=1.0,
        shadow=False,
        scale=0.9,
    ),
    move=MoveCalloutStyle(layout="lower-third", show_archetype=False),
    damage=DamageStyle(intensity=Intensity.MINIMAL, show_critical=True),
    commentary=CommentaryStyle(layout="caption", show_logo=False),
    caption=CaptionStyle(preset="minimal", background_opacity=0.92, size_scale=0.95),
    effect=EffectStyle(
        intensity=Intensity.MINIMAL, camera="static", idle_motion="subtle", trails=False
    ),
    intro=IntroStyle(enabled=True, length="quick", show_player_logos=False),
    result=ResultStyle(enabled=True, show_logos=False, duration_ms=2600),
)

VERTICAL = ProductionStyle(
    id="vertical",
    display_name="Vertical",
    stage=StageStyle(
        background=BackgroundStyle(
            kind="arena", color="#141033", secondary_color="#05060d", vignette=0.5
        ),
        arena="platform",
        stage_lighting=0.75,
        accent="#8a7dff",
    ),
    hud=HudStyle(
        preset="esports",
        hp_shape="rounded",
        hp_thickness=26,
        show_provider=False,
        show_types=False,
        team_indicators="fainted-only",
    ),
    typography=TypographyStyle(display=FontFamily.GEOMETRIC, scale=1.15, letter_spacing=1.0),
    move=MoveCalloutStyle(layout="centered"),
    damage=DamageStyle(intensity=Intensity.DRAMATIC),
    commentary=CommentaryStyle(layout="lower-third", show_label=False, animation="slide"),
    caption=CaptionStyle(preset="vertical", size_scale=1.2, position="bottom"),
    effect=EffectStyle(intensity=Intensity.STANDARD, camera="dynamic", pacing="fast"),
    intro=IntroStyle(enabled=True, length="quick"),
    result=ResultStyle(enabled=True, duration_ms=2800),
)

BUILTIN_STYLES: dict[str, ProductionStyle] = {
    style.id: style for style in (KOALA_BROADCAST, FIGHTING, MINIMAL, RETRO, VERTICAL)
}

_DESCRIPTIONS = {
    "koala-broadcast": "The polished KoalaBattle house style. Full HUD, fighter cards, captions.",
    "fighting": "High-energy arcade broadcast: thick HP bars, impact callouts, dramatic camera.",
    "minimal": "Battle-focused and quiet. Thin HUD, no commentary panel, no branding.",
    "retro": "Pixel typography and a restrained stage, suited to early-generation battles.",
    "vertical": "Short-form framing with large captions and a compact HUD.",
}


def builtin_presets() -> tuple[StylePreset, ...]:
    return tuple(
        StylePreset(
            id=style.id,
            display_name=style.display_name,
            description=_DESCRIPTIONS[style.id],
            builtin=True,
            style=style,
        )
        for style in BUILTIN_STYLES.values()
    )


def suggest_style(*, generation: int, vertical: bool) -> str:
    """A suggestion only — the Studio pre-selects it and the user can always override."""
    if vertical:
        return "vertical"
    if generation <= 2:
        return "retro"
    return "koala-broadcast"
