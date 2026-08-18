from __future__ import annotations

from .models import ProductionProfile

PRODUCTION_PROFILES: dict[str, ProductionProfile] = {
    "live-stream": ProductionProfile(
        id="live-stream", display_name="Live Stream", turn_target_ms=12_000, turn_gap_ms=120
    ),
    "youtube": ProductionProfile(
        id="youtube",
        display_name="YouTube",
        event_gap_ms=180,
        turn_gap_ms=180,
        # A short turn should not spend four seconds staring at an idle arena after the
        # commentary and two attacks have already finished. Longer turns still extend from
        # their real cues; this is only the minimum pacing slot.
        turn_target_ms=12_000,
        commentary_max_characters=420,
    ),
    "shorts": ProductionProfile(
        id="shorts",
        display_name="Shorts",
        aspect_ratio="9:16",
        event_gap_ms=60,
        turn_gap_ms=60,
        turn_target_ms=10_000,
        intro_duration_ms=1_600,
        result_duration_ms=1_200,
        outro_duration_ms=400,
        commentary_max_characters=180,
        caption_max_characters=30,
    ),
    "fast-tournament": ProductionProfile(
        id="fast-tournament",
        display_name="Fast Tournament",
        intro_enabled=False,
        wait_for_speech=False,
        event_gap_ms=20,
        turn_gap_ms=20,
        turn_target_ms=12_000,
        result_duration_ms=1_200,
        outro_duration_ms=300,
        commentary_max_characters=160,
    ),
    "silent": ProductionProfile(
        id="silent",
        display_name="Silent",
        speech_enabled=False,
        captions_enabled=True,
        sfx_enabled=False,
        music_enabled=False,
        turn_target_ms=16_000,
        turn_gap_ms=80,
    ),
}
