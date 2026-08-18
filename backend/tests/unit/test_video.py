from __future__ import annotations

import asyncio
import json
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from koalabattle.config import Settings
from koalabattle.core.models import BattleEvent, MatchConfig, MatchStatus
from koalabattle.production import CreateProduction, ProductionService
from koalabattle.production.models import (
    ProductionCue,
    ProductionProfile,
    ProductionStatus,
    ProductionTimeline,
    Track,
)
from koalabattle.storage import BattleRepository, Database
from koalabattle.video.exporters import (
    OBSWebSocketClient,
    OfflineRendererExporter,
    WebCodecsChunkWriter,
    pipe_frame_batch,
    probe,
    srt_time,
    validate_probe,
)
from koalabattle.video.filesystem import VideoStorage, file_sha256, safe_stem
from koalabattle.video.models import (
    PACING_PROFILES,
    PRESETS,
    CreateVideoExport,
    ExportBackend,
    ExportStatus,
    RenderEngine,
    VideoExportJob,
    frame_count,
    frame_time_ms,
)
from koalabattle.video.repository import VideoExportRepository
from koalabattle.video.service import VideoExportService


def test_frame_mapping_uses_absolute_rational_time_without_drift() -> None:
    assert frame_count(1_000, 30) == 30
    assert frame_count(1_001, 30) == 31
    assert frame_count(16, 60) == 1
    assert frame_time_ms(18_000, 60) == 300_000
    assert frame_time_ms(3, 30) == 100
    assert PACING_PROFILES[PRESETS["fast-preview"].pacing_profile].version == "1.0"
    assert PRESETS["youtube-1080p30"].fps == 30
    assert PRESETS["vertical-1080p30"].fps == 30
    assert CreateVideoExport(production_id=uuid4()).render_engine is RenderEngine.NATIVE


def test_webcodecs_writer_preserves_annexb_and_frames_vp9(tmp_path: Path) -> None:
    annexb = tmp_path / "sample.h264"
    h264 = WebCodecsChunkWriter(annexb, width=1280, height=720, fps=30)
    h264.write_packets(
        [{"codecPath": "h264-annexb", "timestamp": 0, "type": "key", "data": "AAAAAQ=="}]
    )
    h264.close()
    assert annexb.read_bytes() == b"\x00\x00\x00\x01"
    ivf = tmp_path / "sample.ivf"
    vp9 = WebCodecsChunkWriter(ivf, width=1280, height=720, fps=30)
    vp9.write_packets(
        [{"codecPath": "vp9-ivf", "timestamp": 33_333, "type": "delta", "data": "AQID"}]
    )
    vp9.close()
    payload = ivf.read_bytes()
    assert payload[:4] == b"DKIF"
    assert int.from_bytes(payload[24:28], "little") == 1
    assert int.from_bytes(payload[32:36], "little") == 3


async def test_frame_pipe_preserves_order_and_waits_for_backpressure() -> None:
    class Sink:
        def __init__(self) -> None:
            self.operations: list[str] = []

        def write(self, image: bytes) -> None:
            self.operations.append(f"write:{image.decode()}")

        async def drain(self) -> None:
            self.operations.append("drain")

    sink = Sink()
    elapsed = await pipe_frame_batch(sink, [b"0", b"1", b"2"])
    assert sink.operations == [
        "write:0",
        "drain",
        "write:1",
        "drain",
        "write:2",
        "drain",
    ]
    assert elapsed >= 0


def test_video_storage_sanitizes_and_contains_paths(tmp_path: Path) -> None:
    storage = VideoStorage(tmp_path / "video")
    storage.prepare()
    assert safe_stem("../../GPT / Gemini: Final") == "gpt-gemini-final"
    final = storage.final(uuid4(), "../../unsafe")
    assert final.parent == storage.exports
    assert storage.registered("../../etc/passwd") is None
    with pytest.raises(ValueError, match="escapes"):
        storage.relative(tmp_path / "outside.mp4")
    sample = tmp_path / "sample.bin"
    sample.write_bytes(b"koalabattle")
    assert file_sha256(sample) == "9aaa7a3c26f351fc4358be2ff20cdf2bef3ae3bb1d1fefe81fd6fd51a947a888"


def test_renderer_heartbeat_is_bounded_and_rejects_stale_state(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        video_root=tmp_path / "videos",
    )
    database = Database(settings.database_url)
    battles = BattleRepository(database)
    productions = ProductionService(database, battles, settings)
    video = VideoExportService(database, battles, productions, settings)
    video.storage.prepare()
    path = video.storage.root / ".renderer-capabilities.json"
    path.write_text(
        json.dumps({"generated_at": time.time(), "capabilities": {"webcodecs_h264": True}}),
        encoding="utf-8",
    )
    assert video._renderer_heartbeat() == {"webcodecs_h264": True}
    path.write_text(
        json.dumps({"generated_at": time.time() - 31, "capabilities": {}}), encoding="utf-8"
    )
    assert video._renderer_heartbeat() is None


def test_native_transport_can_force_bounded_raw_fallback(tmp_path: Path) -> None:
    settings = Settings(video_root=tmp_path, video_native_transport="raw-rgba")
    exporter = OfflineRendererExporter(settings, VideoStorage(settings.video_root))
    assert exporter._native_transport() == "raw-rgba"


def test_native_transport_uses_compressed_keyframes_on_linux(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    settings = Settings(video_root=tmp_path, video_native_transport="auto")
    exporter = OfflineRendererExporter(settings, VideoStorage(settings.video_root))
    assert exporter._native_transport() == "mjpeg"


def job_fixture(
    *,
    status: ExportStatus = ExportStatus.QUEUED,
    production_id: object | None = None,
    match_id: object | None = None,
) -> VideoExportJob:
    now = datetime.now(UTC)
    return VideoExportJob(
        id=uuid4(),
        production_id=production_id or uuid4(),
        match_id=match_id or uuid4(),
        backend=ExportBackend.OFFLINE,
        preset=PRESETS["fast-preview"],
        output_name="safe",
        idempotency_key=f"test:{uuid4()}",
        end_ms=1_001,
        status=status,
        created_at=now,
        updated_at=now,
    )


async def test_export_repository_idempotency_and_restart_reconciliation(
    tmp_path: Path, match_config: MatchConfig
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    await database.create_schema()
    battles = BattleRepository(database)
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        speech_audio_root=tmp_path / "audio",
    )
    productions = ProductionService(database, battles, settings)
    await productions.start()
    match_id = uuid4()
    await battles.create_match(
        match_id,
        match_config,
        engine="test",
        engine_version="1",
        showdown_version=None,
        poke_env_version=None,
    )
    timeline = await productions.create(match_id, CreateProduction(profile_id="silent"))
    repository = VideoExportRepository(database)
    job = job_fixture(production_id=timeline.id, match_id=match_id)
    first = await repository.create(job)
    duplicate = await repository.create(job.model_copy(update={"id": uuid4()}))
    assert duplicate.id == first.id
    rendering = first.model_copy(update={"status": ExportStatus.RENDERING})
    await repository.save(rendering)
    assert await repository.reconcile_interrupted() == 1
    interrupted = await repository.get(first.id)
    assert interrupted is not None
    assert interrupted.status is ExportStatus.FAILED
    assert interrupted.error_category == "interrupted"
    await productions.close()
    await database.close()


async def test_live_production_appends_idempotently_and_finalizes(
    tmp_path: Path, match_config: MatchConfig
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    await database.create_schema()
    battles = BattleRepository(database)
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        speech_audio_root=tmp_path / "audio",
        video_root=tmp_path / "videos",
    )
    production = ProductionService(database, battles, settings)
    battles.set_production_hooks(
        event=production.on_event, completion=production.on_match_completed
    )
    await production.start()
    match_id = uuid4()
    await battles.create_match(
        match_id,
        match_config,
        engine="test",
        engine_version="1",
        showdown_version=None,
        poke_env_version=None,
    )
    await battles.enqueue_match(match_id)
    await battles.set_status(match_id, MatchStatus.STARTING)
    await battles.set_status(match_id, MatchStatus.RUNNING)
    started = await battles.append_event(
        BattleEvent(match_id=match_id, sequence=0, turn=0, event_type="battle_started")
    )
    live = (await production.repository.list_for_match(match_id))[0]
    assert live.status is ProductionStatus.LIVE
    before = len(live.cues)
    await production.on_event(started)
    assert len((await production.require(live.id)).cues) == before
    await battles.append_event(
        BattleEvent(match_id=match_id, sequence=0, turn=1, event_type="turn_started")
    )
    extended = await production.require(live.id)
    assert len(extended.cues) > before
    await battles.complete_match(match_id, winner=None, turns=1, raw_showdown_log=None)
    await production.close()
    finalized = await production.require(live.id)
    assert finalized.status is ProductionStatus.FINALIZED
    assert finalized.content_sha256
    assert [cue.id for cue in finalized.cues].count("director-result") == 1
    await database.close()


async def test_export_service_create_cancel_retry_is_separate_from_battle(
    tmp_path: Path, match_config: MatchConfig
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    await database.create_schema()
    battles = BattleRepository(database)
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        speech_audio_root=tmp_path / "audio",
        video_root=tmp_path / "videos",
        video_worker_enabled=False,
    )
    production = ProductionService(database, battles, settings)
    await production.start()
    match_id = uuid4()
    await battles.create_match(
        match_id,
        match_config,
        engine="test",
        engine_version="1",
        showdown_version=None,
        poke_env_version=None,
    )
    await battles.enqueue_match(match_id)
    await battles.set_status(match_id, MatchStatus.STARTING)
    await battles.set_status(match_id, MatchStatus.RUNNING)
    await battles.complete_match(match_id, winner=None, turns=0, raw_showdown_log=None)
    timeline = await production.create(match_id, CreateProduction(profile_id="silent"))
    video = VideoExportService(database, battles, production, settings)
    await video.start()
    job = await video.create(
        CreateVideoExport(
            production_id=timeline.id,
            preset_id="youtube-1080p60",
            idempotency_key="request:one",
        )
    )
    assert job.status is ExportStatus.QUEUED
    cancelled = await video.cancel(job.id)
    assert cancelled.status is ExportStatus.CANCELLED
    retried = await video.retry(job.id)
    assert retried.id != job.id
    assert retried.attempt == 2
    archive = await battles.get_match(match_id)
    assert archive is not None and archive.status is MatchStatus.COMPLETED
    await video.close()
    await production.close()
    await database.close()


class FakeSocket:
    def __init__(self) -> None:
        self.responses: asyncio.Queue[str] = asyncio.Queue()
        self.sent: list[dict[str, object]] = []
        self.closed = False

    async def send(self, value: str) -> None:
        payload = json.loads(value)
        self.sent.append(payload)
        if payload["op"] == 6:
            await self.responses.put(
                json.dumps(
                    {
                        "op": 7,
                        "d": {
                            "requestId": payload["d"]["requestId"],
                            "requestStatus": {"result": True, "code": 100},
                            "responseData": {"outputActive": False},
                        },
                    }
                )
            )

    async def recv(self) -> str:
        return await self.responses.get()

    async def close(self) -> None:
        self.closed = True


async def test_obs_v5_request_uses_structured_protocol() -> None:
    socket = FakeSocket()
    client = OBSWebSocketClient("127.0.0.1", 4455, None)
    client.socket = socket
    response = await client.request("GetRecordStatus")
    assert response == {"outputActive": False}
    assert socket.sent[0]["op"] == 6
    assert socket.sent[0]["d"]["requestType"] == "GetRecordStatus"  # type: ignore[index]


def test_probe_validation_allows_intentionally_silent_video() -> None:
    job = job_fixture()
    metadata = {
        "streams": [
            {
                "codec_type": "video",
                "width": 1280,
                "height": 720,
                "codec_name": "h264",
            }
        ],
        "format": {"duration": "1.001"},
    }
    validate_probe(metadata, job, audio_expected=False)
    with pytest.raises(ValueError, match="missing"):
        validate_probe(metadata, job, audio_expected=True)
    assert srt_time(3_723_004) == "01:02:03,004"


async def test_offline_audio_renders_generic_sfx_without_external_media(
    tmp_path: Path,
) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg tooling is unavailable")
    now = datetime.now(UTC)
    match_id = uuid4()
    production_id = uuid4()
    production = ProductionTimeline(
        id=production_id,
        match_id=match_id,
        profile=ProductionProfile(id="test", display_name="Test"),
        status=ProductionStatus.FINALIZED,
        cues=(
            ProductionCue(
                id="sfx-1",
                track=Track.SFX,
                kind="critical",
                start_ms=100,
                duration_ms=120,
            ),
        ),
        duration_ms=1_001,
        created_at=now,
        updated_at=now,
    )
    job = job_fixture(production_id=production_id, match_id=match_id)
    storage = VideoStorage(tmp_path / "videos")
    storage.prepare()
    exporter = OfflineRendererExporter(Settings(speech_audio_root=tmp_path / "audio"), storage)
    output = storage.temporary(job.id, ".audio.wav")
    assert await exporter._audio(production, job, output)
    metadata = await probe("ffprobe", output)
    audio = next(stream for stream in metadata["streams"] if stream.get("codec_type") == "audio")
    assert audio["sample_rate"] == "48000"
    assert audio["channels"] == 2
