from __future__ import annotations

from .models import ProductionProfile

PRODUCTION_PROFILES: dict[str, ProductionProfile] = {
    "live-stream": ProductionProfile(id="live-stream", display_name="Live Stream"),
    "youtube": ProductionProfile(
        id="youtube", display_name="YouTube", event_gap_ms=180, commentary_max_characters=420
    ),
    "shorts": ProductionProfile(
        id="shorts",
        display_name="Shorts",
        aspect_ratio="9:16",
        event_gap_ms=60,
        commentary_max_characters=180,
        caption_max_characters=30,
    ),
    "fast-tournament": ProductionProfile(
        id="fast-tournament",
        display_name="Fast Tournament",
        intro_enabled=False,
        wait_for_speech=False,
        event_gap_ms=20,
        commentary_max_characters=160,
    ),
    "silent": ProductionProfile(
        id="silent",
        display_name="Silent",
        speech_enabled=False,
        captions_enabled=True,
        sfx_enabled=False,
        music_enabled=False,
    ),
}
