from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from koalabattle.config import Settings
from koalabattle.core.models import BattleEvent, MatchConfig, MatchStatus
from koalabattle.production import CreateProduction, ProductionService
from koalabattle.production.models import (
    PrepareSpeechRequest,
    ProductionCue,
    ProductionStatus,
    SpeechArtifact,
    SpeechProviderKind,
    SpeechRequest,
    Track,
    VoicePreset,
)
from koalabattle.production.profiles import PRODUCTION_PROFILES
from koalabattle.production.speech import FakeSpeechProvider, SpeechCache, SpeechGenerationQueue
from koalabattle.production.speech.cache import speech_cache_key
from koalabattle.production.speech.system import SystemSpeechProvider
from koalabattle.production.timeline import build_timeline, retime_for_audio, segment_caption
from koalabattle.storage import BattleRepository, Database
from koalabattle.video.models import ExportBackend, RendererCapabilities
from koalabattle.video.service import VideoExportService


async def _archive(tmp_path: Path, match_config: MatchConfig):  # type: ignore[no-untyped-def]
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'production.db'}")
    await database.create_schema()
    repository = BattleRepository(database)
    match_id = uuid4()
    await repository.create_match(
        match_id,
        match_config,
        engine="test",
        engine_version="1",
        showdown_version="test",
        poke_env_version="0.15.0",
    )
    await repository.append_event(
        BattleEvent(
            match_id=match_id,
            sequence=0,
            turn=1,
            event_type="agent_decision",
            payload={
                "side": "p1",
                "commentary": "Public move explanation for viewers.",
                "banter": "That switch was sharper than expected.",
                "public_text": (
                    "Public move explanation for viewers. "
                    "That switch was sharper than expected."
                ),
                "strategy_memory": "NEVER SPEAK THIS",
                "raw_response": "NEVER SPEAK RAW",
                "prompt": "NEVER SPEAK PROMPT",
            },
        )
    )
    archive = await repository.get_match(match_id)
    assert archive is not None
    return database, archive


@pytest.mark.asyncio
async def test_timeline_is_deterministic_and_only_uses_public_commentary(
    tmp_path: Path, match_config: MatchConfig
) -> None:
    database, archive = await _archive(tmp_path, match_config)
    first = build_timeline(archive, PRODUCTION_PROFILES["live-stream"])
    assert first.voice_assignments == {"p1": "edge-neural-p1", "p2": "edge-neural-p2"}
    second = build_timeline(
        archive,
        PRODUCTION_PROFILES["live-stream"],
        production_id=first.id,
        voices=first.voice_assignments,
    )
    assert [cue.model_dump(exclude={"id"}) for cue in first.cues] == [
        cue.model_dump(exclude={"id"}) for cue in second.cues
    ]
    serialized = first.model_dump_json()
    assert "Public move explanation" in serialized
    assert "That switch was sharper" in serialized
    assert "NEVER SPEAK" not in serialized
    assert {cue.track.value for cue in first.cues} >= {
        "visual",
        "commentary",
        "captions",
        "director",
    }
    await database.close()


@pytest.mark.asyncio
async def test_internal_stream_events_do_not_create_replay_time(
    tmp_path: Path, match_config: MatchConfig
) -> None:
    database, archive = await _archive(tmp_path, match_config)
    repository = BattleRepository(database)
    await repository.append_event(
        BattleEvent(
            match_id=archive.id,
            sequence=1,
            turn=1,
            event_type="agent_progress",
            payload={"side": "p1", "progress": "private progress"},
        )
    )
    await repository.append_event(
        BattleEvent(
            match_id=archive.id,
            sequence=2,
            turn=1,
            event_type="state_snapshot",
            payload={"state": {}},
        )
    )
    await repository.append_event(
        BattleEvent(
            match_id=archive.id,
            sequence=3,
            turn=1,
            event_type="showdown_message",
            payload={"command": "|private"},
        )
    )
    refreshed = await repository.get_match(archive.id)
    assert refreshed is not None

    timeline = build_timeline(refreshed, PRODUCTION_PROFILES["youtube"])

    assert not any(
        cue.kind in {"agent_progress", "agent_state", "showdown_message"}
        for cue in timeline.cues
    )
    snapshot = next(cue for cue in timeline.cues if cue.kind == "state_snapshot")
    assert snapshot.duration_ms == 0
    public_event_end = max(
        cue.start_ms + cue.duration_ms
        for cue in timeline.cues
        if cue.event_sequence is not None and cue.duration_ms > 0
    )
    assert timeline.duration_ms == public_event_end
    await database.close()


def test_broadcast_profiles_do_not_hold_short_turns_for_twenty_seconds() -> None:
    assert PRODUCTION_PROFILES["live-stream"].turn_target_ms == 12_000
    assert PRODUCTION_PROFILES["youtube"].turn_target_ms == 12_000


def test_turn_timing_has_no_intra_turn_gaps_and_uses_fixed_slots() -> None:
    profile = PRODUCTION_PROFILES["youtube"]
    cues = (
        ProductionCue(
            id="director-intro",
            track=Track.DIRECTOR,
            kind="match-intro",
            start_ms=0,
            duration_ms=profile.intro_duration_ms,
        ),
        ProductionCue(
            id="event-1-visual",
            track=Track.VISUAL,
            kind="agent_decision",
            start_ms=0,
            duration_ms=100,
            event_sequence=1,
            turn=1,
        ),
        ProductionCue(
            id="event-1-commentary",
            track=Track.COMMENTARY,
            kind="public-agent-commentary",
            start_ms=0,
            duration_ms=400,
            event_sequence=1,
            turn=1,
        ),
        ProductionCue(
            id="event-2-visual",
            track=Track.VISUAL,
            kind="damage",
            start_ms=0,
            duration_ms=100,
            event_sequence=2,
            turn=1,
        ),
        ProductionCue(
            id="event-3-visual",
            track=Track.VISUAL,
            kind="damage",
            start_ms=0,
            duration_ms=100,
            event_sequence=3,
            turn=2,
        ),
        ProductionCue(
            id="director-result",
            track=Track.DIRECTOR,
            kind="result",
            start_ms=0,
            duration_ms=profile.result_duration_ms,
        ),
        ProductionCue(
            id="director-outro",
            track=Track.DIRECTOR,
            kind="outro",
            start_ms=0,
            duration_ms=profile.outro_duration_ms,
        ),
    )

    retimed, duration_ms = retime_for_audio(cues, profile)
    starts = {cue.id: cue.start_ms for cue in retimed}

    assert starts["event-1-visual"] == profile.intro_duration_ms
    assert starts["event-2-visual"] == profile.intro_duration_ms + 400
    assert starts["event-3-visual"] == (
        profile.intro_duration_ms + profile.turn_target_ms + profile.turn_pause_ms
    )
    assert starts["director-result"] == (
        profile.intro_duration_ms
        + profile.turn_target_ms
        + profile.turn_pause_ms
        + profile.turn_target_ms
    )
    assert duration_ms == (
        starts["director-result"] + profile.result_duration_ms + profile.outro_duration_ms
    )


@pytest.mark.asyncio
async def test_speech_preparation_schedules_all_cues_concurrently(
    tmp_path: Path, match_config: MatchConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, archive = await _archive(tmp_path, match_config)
    repository = BattleRepository(database)
    await repository.append_event(
        BattleEvent(
            match_id=archive.id,
            sequence=1,
            turn=1,
            event_type="agent_decision",
            payload={"side": "p2", "commentary": "Second public explanation."},
        )
    )
    refreshed = await repository.get_match(archive.id)
    assert refreshed is not None
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'production.db'}",
        speech_audio_root=tmp_path / "audio",
        video_root=tmp_path / "videos",
    )
    service = ProductionService(database, repository, settings)
    await service.start()
    active = 0
    peak = 0

    async def fake_synthesize(
        text: str, preset: VoicePreset, *, allow_paid: bool, force: bool = False
    ) -> SpeechArtifact:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return SpeechArtifact(
            cache_key=("a" if text else "b") * 64,
            media_url="/api/production/media/test",
            duration_ms=900,
            byte_size=1,
            content_sha256="b" * 64,
        )

    monkeypatch.setattr(service, "synthesize", fake_synthesize)
    production = await service.create(
        refreshed.id,
        CreateProduction(
            profile_id="youtube",
            voice_assignments={"p1": "edge-neural-p1", "p2": "edge-neural-p2"},
        ),
    )
    prepared = await service.prepare(production.id, PrepareSpeechRequest())

    assert peak == 2
    assert len([cue for cue in prepared.cues if cue.track is Track.VOICE]) == 2
    await service.close()
    await database.close()


def test_caption_segments_are_bounded_contiguous_and_independent() -> None:
    segments = segment_caption(
        "A long public sentence that should become several readable caption segments.",
        maximum=24,
        duration_ms=3000,
    )
    assert len(segments) >= 2
    assert segments[0].start_ms == 0
    assert segments[-1].end_ms == 3000
    assert all(len(segment.text) <= 24 for segment in segments)
    assert all(
        left.end_ms == right.start_ms for left, right in zip(segments, segments[1:], strict=False)
    )


@pytest.mark.asyncio
async def test_fake_speech_cache_is_deterministic_atomic_and_rejects_corruption(
    tmp_path: Path,
) -> None:
    request = SpeechRequest(
        text="Cached public commentary.",
        provider=SpeechProviderKind.FAKE,
        model="fake-v1",
        voice="test-a",
    )
    assert speech_cache_key(request) == speech_cache_key(request.model_copy())
    provider = FakeSpeechProvider()
    content = await provider.synthesize(request)
    cache = SpeechCache(tmp_path / "audio")
    key = speech_cache_key(request)
    stored = cache.store(key, content)
    assert cache.validate(key) == stored
    assert not list(stored.path.parent.glob(f".{key}-*"))
    stored.path.write_bytes(b"partial")
    assert cache.validate(key) is None
    with pytest.raises(ValueError):
        cache.path_for("../escape")


@pytest.mark.asyncio
async def test_generation_queue_deduplicates_and_cancels_safely() -> None:
    queue = SpeechGenerationQueue(1)
    calls = 0

    async def work() -> bytes:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return b"audio"

    one, two = await asyncio.gather(queue.generate("same", work), queue.generate("same", work))
    assert one == two == b"audio"
    assert calls == 1
    blocked = asyncio.create_task(queue.generate("cancel", lambda: asyncio.sleep(5, result=b"x")))
    await asyncio.sleep(0)
    assert await queue.cancel("cancel") is True
    with pytest.raises(asyncio.CancelledError):
        await blocked
    await queue.close()


@pytest.mark.asyncio
async def test_installed_system_speech_produces_valid_local_wav(tmp_path: Path) -> None:
    provider = SystemSpeechProvider()
    if not provider.status().available:
        pytest.skip("no system speech executable installed")
    request = SpeechRequest(
        text="KoalaBattle local speech test.",
        provider=SpeechProviderKind.SYSTEM,
        model="system",
        voice="system-default",
    )
    content = await provider.synthesize(request)
    assert SpeechCache(tmp_path / "system-audio").store(speech_cache_key(request), content)


@pytest.mark.asyncio
async def test_speech_outage_keeps_captions_and_marks_production_partial(
    tmp_path: Path, match_config: MatchConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    class UnavailableSpeechProvider(SystemSpeechProvider):
        async def synthesize(self, request: SpeechRequest) -> bytes:
            raise RuntimeError("simulated Edge outage")

    database, archive = await _archive(tmp_path, match_config)
    battles = BattleRepository(database)
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'production.db'}",
        speech_audio_root=tmp_path / "audio",
        video_root=tmp_path / "videos",
    )
    service = ProductionService(
        database,
        battles,
        settings,
    )
    await service.start()
    service.providers[SpeechProviderKind.SYSTEM] = UnavailableSpeechProvider()
    production = await service.create(
        archive.id,
        CreateProduction(
            profile_id="live-stream",
            voice_assignments={"p1": "edge-neural-p1", "p2": "edge-neural-p2"},
        ),
    )

    degraded = await service.prepare(production.id, PrepareSpeechRequest())

    assert degraded.status is ProductionStatus.PARTIAL
    assert degraded.overrides["speech_failures"]
    assert any(cue.track is Track.CAPTIONS for cue in degraded.cues)
    assert not any(cue.track is Track.VOICE for cue in degraded.cues)

    video = VideoExportService(database, battles, service, settings)

    async def available_renderer() -> RendererCapabilities:
        return RendererCapabilities(
            offline_available=True,
            obs_configured=False,
            ffmpeg_available=True,
            ffprobe_available=True,
            chromium_available=True,
            playwright_available=True,
            native_compositor_available=True,
            raw_frame_available=True,
            output_writable=True,
            output_root=str(tmp_path / "videos"),
            free_bytes=2_000_000_000,
            storage_bytes=0,
            concurrency=1,
            obs_host="127.0.0.1",
            obs_port=4455,
            obs_scene="KoalaBattle",
        )

    monkeypatch.setattr(video, "capabilities", available_renderer)
    preflight = await video.preflight(degraded.id, ExportBackend.OFFLINE)
    assert preflight.ready is True
    assert preflight.missing_speech
    assert preflight.warnings == (
        "Speech is unavailable for some commentary; captions remain and those cues "
        "will render silently.",
    )
    system_production = await service.create(
        archive.id,
        CreateProduction(
            profile_id="live-stream",
            voice_assignments={"p1": "system-p1", "p2": "system-p2"},
        ),
    )
    system_preflight = await video.preflight(system_production.id, ExportBackend.OFFLINE)
    assert system_preflight.checks["voice_quality"] == "basic offline system speech"
    assert system_preflight.warnings == (
        "Speech is unavailable for some commentary; captions remain and those cues "
        "will render silently.",
        "This production uses basic offline system speech. Regenerate it with the "
        "Edge Neural presets before a production export.",
    )
    await service.close()
    await database.close()


@pytest.mark.asyncio
async def test_archived_replay_automatically_prepares_edge_speech(
    tmp_path: Path, match_config: MatchConfig
) -> None:
    database, archive = await _archive(tmp_path, match_config)
    battles = BattleRepository(database)
    await battles.enqueue_match(archive.id)
    await battles.set_status(archive.id, MatchStatus.STARTING)
    await battles.set_status(archive.id, MatchStatus.RUNNING)
    await battles.complete_match(archive.id, winner=None, turns=1, raw_showdown_log=None)

    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'production.db'}",
        speech_audio_root=tmp_path / "audio",
        video_root=tmp_path / "videos",
    )
    service = ProductionService(database, battles, settings)
    await service.start()
    # Keep the test offline while exercising the Edge Neural voice assignments and the
    # automatic archived-replay lifecycle.
    service.providers[SpeechProviderKind.SYSTEM] = FakeSpeechProvider()

    production = await service.create(
        archive.id,
        CreateProduction(
            profile_id="youtube",
            voice_assignments={"p1": "edge-neural-p1", "p2": "edge-neural-p2"},
        ),
    )

    assert production.status is ProductionStatus.READY
    assert any(cue.track is Track.VOICE for cue in production.cues)
    assert not service._needs_speech_preparation(production)
    rebuilt = await service.rebuild(production.id)
    assert rebuilt.id == production.id
    assert rebuilt.revision == production.revision + 1
    await service.close()
    await database.close()
