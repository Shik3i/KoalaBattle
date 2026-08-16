from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from koalabattle.config import Settings
from koalabattle.core.models import BattleEvent, MatchConfig
from koalabattle.production import CreateProduction, ProductionService
from koalabattle.production.models import (
    PrepareSpeechRequest,
    ProductionStatus,
    SpeechProviderKind,
    SpeechRequest,
    Track,
)
from koalabattle.production.profiles import PRODUCTION_PROFILES
from koalabattle.production.speech import FakeSpeechProvider, SpeechCache, SpeechGenerationQueue
from koalabattle.production.speech.cache import speech_cache_key
from koalabattle.production.speech.system import SystemSpeechProvider
from koalabattle.production.timeline import build_timeline, segment_caption
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
    assert "NEVER SPEAK" not in serialized
    assert {cue.track.value for cue in first.cues} >= {
        "visual",
        "commentary",
        "captions",
        "director",
    }
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
