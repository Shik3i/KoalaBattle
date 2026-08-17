from __future__ import annotations

import base64
import json
import struct
import zlib
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from koalabattle.branding import BrandAssetInUse, BrandingService, UnsupportedMedia
from koalabattle.branding.marks import mark_for
from koalabattle.branding.media import inspect
from koalabattle.branding.models import BrandAssetKind, UploadBrandAsset
from koalabattle.config import Settings
from koalabattle.core.models import BattleEvent, MatchConfig
from koalabattle.production import CreateProduction, ProductionService
from koalabattle.production.models import (
    DuplicateProduction,
    PrepareSpeechRequest,
    ProductionTimeline,
    Track,
    UpdateProduction,
)
from koalabattle.production.style import ParticipantBranding, ProductionStyle, SaveStylePreset
from koalabattle.production.style_presets import BUILTIN_STYLES, builtin_presets, suggest_style
from koalabattle.storage import BattleRepository, Database
from koalabattle.video.exporters import style_snapshot


def png(width: int, height: int) -> bytes:
    """A structurally valid PNG. Only the header is ever parsed, but keep it honest."""
    header = struct.pack(">II", width, height) + bytes([8, 6, 0, 0, 0])

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"\x00" * (width * 4 + 1) * height))
        + chunk(b"IEND", b"")
    )


async def _service(tmp_path: Path, match_config: MatchConfig):  # type: ignore[no-untyped-def]
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'style.db'}")
    await database.create_schema()
    battles = BattleRepository(database)
    match_id = uuid4()
    await battles.create_match(
        match_id,
        match_config,
        engine="test",
        engine_version="1",
        showdown_version="test",
        poke_env_version="0.15.0",
    )
    await battles.append_event(
        BattleEvent(
            match_id=match_id,
            sequence=0,
            turn=1,
            event_type="agent_decision",
            payload={"side": "p1", "commentary": "Public move explanation for viewers."},
        )
    )
    settings = Settings(
        speech_audio_root=tmp_path / "audio",
        branding_root=tmp_path / "branding",
        video_root=tmp_path / "videos",
    )
    service = ProductionService(database, battles, settings)
    await service.start()
    return database, service, match_id, settings


# ------------------------------------------------------------------- style model


def test_style_rejects_anything_that_is_not_a_plain_colour() -> None:
    for value in ("url(evil.png)", "red; background:url(x)", "rgb(1,2,3)", "#12345", ""):
        with pytest.raises(ValidationError):
            ProductionStyle(stage={"accent": value})  # type: ignore[arg-type]
    assert ProductionStyle(stage={"accent": "#abc"}).stage.accent == "#abc"  # type: ignore[arg-type]


def test_style_rejects_asset_references_that_are_not_generated_ids() -> None:
    for value in ("../../etc/passwd", "a" * 31, "A" * 32, "logo.png"):
        with pytest.raises(ValidationError):
            ProductionStyle(watermark={"asset_id": value})  # type: ignore[arg-type]
    ok = ProductionStyle(watermark={"asset_id": "a" * 32})  # type: ignore[arg-type]
    assert ok.watermark.asset_id == "a" * 32


def test_style_collects_every_asset_it_references() -> None:
    style = ProductionStyle(
        stage={"background": {"kind": "image", "asset_id": "1" * 32}},  # type: ignore[arg-type]
        typography={"display_asset_id": "2" * 32},  # type: ignore[arg-type]
        watermark={"asset_id": "3" * 32},  # type: ignore[arg-type]
        players={"p1": ParticipantBranding(logo_asset_id="4" * 32)},
    )
    assert set(style.asset_ids()) == {"1" * 32, "2" * 32, "3" * 32, "4" * 32}


def test_builtin_presets_are_compositions_not_one_setting_variations() -> None:
    presets = builtin_presets()
    assert {preset.id for preset in presets} == {
        "koala-broadcast",
        "fighting",
        "minimal",
        "retro",
        "vertical",
    }
    assert all(preset.builtin for preset in presets)
    signatures = {
        (
            preset.style.stage.arena,
            preset.style.hud.preset,
            preset.style.hud.hp_shape,
            preset.style.typography.display,
            preset.style.move.layout,
            preset.style.commentary.layout,
            preset.style.caption.preset,
            preset.style.effect.intensity,
        )
        for preset in presets
    }
    assert len(signatures) == len(presets), "each built-in must differ across several axes"


def test_style_suggestion_is_generation_aware_but_never_binding() -> None:
    assert suggest_style(generation=1, vertical=False) == "retro"
    assert suggest_style(generation=9, vertical=False) == "koala-broadcast"
    assert suggest_style(generation=1, vertical=True) == "vertical"


def test_old_productions_without_a_style_load_with_documented_defaults() -> None:
    now = "2026-01-01T00:00:00Z"
    legacy = {
        "id": str(uuid4()),
        "match_id": str(uuid4()),
        "profile": {"id": "youtube", "display_name": "YouTube"},
        "created_at": now,
        "updated_at": now,
    }
    production = ProductionTimeline.model_validate(legacy)
    assert production.style.id == "koala-broadcast"
    assert production.style == BUILTIN_STYLES["koala-broadcast"]
    assert production.title is None


# ---------------------------------------------------------------- media safety


def test_media_inspection_accepts_supported_images_and_reads_their_size() -> None:
    inspected = inspect(png(320, 180), BrandAssetKind.LOGO)
    assert (inspected.media_type, inspected.width, inspected.height) == ("image/png", 320, 180)
    webp = b"RIFF" + b"\x00" * 4 + b"WEBPVP8L" + b"\x00" * 5 + (63).to_bytes(4, "little")
    assert inspect(webp, BrandAssetKind.BACKGROUND).media_type == "image/webp"


def test_media_inspection_refuses_svg_scripts_and_unknown_content() -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    for payload in (svg, b"GIF89a", b"not an image at all", b"<html>"):
        with pytest.raises(UnsupportedMedia):
            inspect(payload, BrandAssetKind.LOGO)


def test_media_inspection_refuses_a_decompression_bomb_before_decoding() -> None:
    # A 40000x40000 PNG is tiny on disk and ruinous in memory; the header check is enough.
    bomb = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 40_000, 40_000)
    with pytest.raises(UnsupportedMedia, match="edge exceeds"):
        inspect(bomb, BrandAssetKind.BACKGROUND)


def test_font_inspection_accepts_real_font_signatures_only() -> None:
    assert inspect(b"wOF2" + b"\x00" * 40, BrandAssetKind.FONT).media_type == "font/woff2"
    assert inspect(b"OTTO" + b"\x00" * 40, BrandAssetKind.FONT).media_type == "font/otf"
    with pytest.raises(UnsupportedMedia):
        inspect(b"MZ\x90\x00" + b"\x00" * 40, BrandAssetKind.FONT)


@pytest.mark.asyncio
async def test_uploads_are_stored_under_generated_names_outside_any_user_path(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'brand.db'}")
    await database.create_schema()
    service = BrandingService(database, tmp_path / "branding")
    asset = await service.upload(
        UploadBrandAsset(
            kind=BrandAssetKind.LOGO,
            display_name="../../etc/passwd",
            data_base64=base64.b64encode(png(64, 64)).decode(),
        )
    )
    assert "/" not in asset.display_name and ".." not in asset.display_name
    assert asset.relative_path == f"logo/{asset.id}.png"
    path = await service.media_path(asset.id)
    assert path is not None
    assert path.is_relative_to((tmp_path / "branding").resolve())
    assert await service.missing((asset.id,)) == ()
    await database.close()


@pytest.mark.asyncio
async def test_deleting_an_asset_in_use_is_refused_then_degrades_gracefully(
    tmp_path: Path, match_config: MatchConfig
) -> None:
    database, service, match_id, settings = await _service(tmp_path, match_config)
    branding = BrandingService(database, settings.branding_root)
    asset = await branding.upload(
        UploadBrandAsset(
            kind=BrandAssetKind.LOGO,
            display_name="Team mark",
            data_base64=base64.b64encode(png(48, 48)).decode(),
        )
    )
    production = await service.create(match_id, CreateProduction(profile_id="youtube"))
    style = production.style.model_copy(
        update={
            "players": {
                **production.style.players,
                "p1": production.style.branding_for("p1").model_copy(
                    update={"logo_asset_id": asset.id}
                ),
            }
        }
    )
    await service.update(production.id, UpdateProduction(style=style))
    with pytest.raises(BrandAssetInUse):
        await branding.delete(asset.id)
    assert await branding.delete(asset.id, force=True) is True
    # The production still loads; the missing logo is reported, not silently swapped.
    reloaded = await service.require(production.id)
    assert reloaded.style.branding_for("p1").logo_asset_id == asset.id
    assert await branding.missing(reloaded.style.asset_ids()) == (asset.id,)
    await database.close()


def test_no_third_party_logo_files_are_bundled() -> None:
    root = Path(__file__).resolve().parents[3]
    marks = mark_for("api", "openai")
    assert marks.id == "gpt" and marks.label == "GPT"
    assert mark_for("manual", "openai").id == "manual", "agent type wins over provider"
    tracked = (root / "backend" / "koalabattle" / "branding").rglob("*")
    assert not [path for path in tracked if path.suffix in {".png", ".svg", ".webp", ".jpg"}]


# ------------------------------------------------------- productions & presets


@pytest.mark.asyncio
async def test_new_production_gets_player_branding_from_the_match(
    tmp_path: Path, match_config: MatchConfig
) -> None:
    database, service, match_id, _ = await _service(tmp_path, match_config)
    production = await service.create(match_id, CreateProduction(profile_id="youtube"))
    for side, player in zip(("p1", "p2"), match_config.players, strict=True):
        branding = production.style.branding_for(side)
        assert branding.display_name == player.display_name
        assert branding.logo_mark
        assert branding.accent and branding.accent.startswith("#")
    await database.close()


@pytest.mark.asyncio
async def test_two_productions_of_one_match_stay_independent(
    tmp_path: Path, match_config: MatchConfig
) -> None:
    database, service, match_id, _ = await _service(tmp_path, match_config)
    first = await service.create(
        match_id, CreateProduction(profile_id="youtube", style_id="fighting", title="Broadcast cut")
    )
    second = await service.create(
        match_id, CreateProduction(profile_id="youtube", style_id="minimal", title="Quiet cut")
    )
    assert first.id != second.id
    assert first.style.id == "fighting" and second.style.id == "minimal"

    edited = first.style.model_copy(
        update={"stage": first.style.stage.model_copy(update={"arena": "none"})}
    )
    await service.update(first.id, UpdateProduction(style=edited, title="Edited"))

    reloaded_first = await service.require(first.id)
    reloaded_second = await service.require(second.id)
    assert reloaded_first.style.stage.arena == "none"
    assert reloaded_first.title == "Edited"
    assert reloaded_second.style.stage.arena == BUILTIN_STYLES["minimal"].stage.arena
    assert reloaded_second.style.id == "minimal"
    assert reloaded_second.title == "Quiet cut"

    # And the recorded match is untouched by any of it.
    archive = await service.battles.get_match(match_id)
    assert archive is not None
    assert [player.display_name for player in archive.config.players] == [
        player.display_name for player in match_config.players
    ]
    assert len(archive.events) == 1
    await database.close()


@pytest.mark.asyncio
async def test_duplicating_a_production_copies_presentation_not_history(
    tmp_path: Path, match_config: MatchConfig
) -> None:
    database, service, match_id, _ = await _service(tmp_path, match_config)
    source = await service.create(match_id, CreateProduction(profile_id="youtube"))
    copy = await service.duplicate(
        source.id, DuplicateProduction(title="Vertical cut", style_id="vertical")
    )
    assert copy.id != source.id
    assert copy.match_id == source.match_id
    assert copy.style.id == "vertical"
    assert copy.title == "Vertical cut"
    assert [cue.id for cue in copy.cues] == [cue.id for cue in source.cues]
    assert (await service.require(source.id)).style.id == source.style.id

    assert await service.delete(copy.id) is True
    assert await service.battles.get_match(match_id) is not None
    await database.close()


@pytest.mark.asyncio
async def test_rebuild_preserves_the_configured_presentation(
    tmp_path: Path, match_config: MatchConfig
) -> None:
    database, service, match_id, _ = await _service(tmp_path, match_config)
    production = await service.create(
        match_id, CreateProduction(profile_id="youtube", style_id="retro", title="Gen 1 cut")
    )
    rebuilt = await service.rebuild(production.id)
    assert rebuilt.style.id == "retro"
    assert rebuilt.title == "Gen 1 cut"
    await database.close()


@pytest.mark.asyncio
async def test_user_presets_save_and_never_shadow_a_builtin(
    tmp_path: Path, match_config: MatchConfig
) -> None:
    database, service, _, _ = await _service(tmp_path, match_config)
    saved = await service.save_style_preset(
        SaveStylePreset(display_name="Timo 1", description="mine", style=BUILTIN_STYLES["fighting"])
    )
    assert saved.id == "timo-1" and saved.builtin is False
    ids = [preset.id for preset in await service.styles()]
    assert ids[: len(BUILTIN_STYLES)] == list(BUILTIN_STYLES)
    assert "timo-1" in ids

    with pytest.raises(ValueError, match="cannot be overwritten"):
        await service.save_style_preset(
            SaveStylePreset(display_name="Fighting", style=BUILTIN_STYLES["minimal"])
        )
    with pytest.raises(ValueError, match="cannot be deleted"):
        await service.delete_style_preset("fighting")
    assert await service.delete_style_preset("timo-1") is True
    await database.close()


@pytest.mark.asyncio
async def test_preparing_speech_retimes_the_clock_for_an_archived_match(
    tmp_path: Path, match_config: MatchConfig
) -> None:
    """A Studio production of an old match must end up with a clock that matches its audio.

    Live matches were normalized by the finalization task. A production created later from
    the archive never ran that path, so its cue starts and duration still described the
    estimated commentary lengths while the cues carried real audio. Any window computed
    from it then pointed at the wrong moment — which is how a "victory" export range ended
    up stopping before the result card.
    """
    database, service, match_id, _ = await _service(tmp_path, match_config)
    production = await service.create(
        match_id,
        CreateProduction(
            profile_id="youtube",
            voice_assignments={"p1": "fake-test-a", "p2": "fake-test-b"},
        ),
    )
    prepared = await service.prepare(
        production.id, PrepareSpeechRequest(force=False, allow_paid=False)
    )
    assert prepared.cues
    end = max(cue.start_ms + cue.duration_ms for cue in prepared.cues)
    assert prepared.duration_ms >= end, "the clock must cover every cue after preparation"
    voiced = [cue for cue in prepared.cues if cue.track is Track.VOICE]
    assert voiced, "the fake provider must have produced speech to retime against"
    for voice in voiced:
        commentary = next(
            cue
            for cue in prepared.cues
            if cue.track is Track.COMMENTARY and cue.event_sequence == voice.event_sequence
        )
        # The spoken line and the panel that introduces it must start together and last as
        # long as the audio; that is the property a stale clock silently breaks.
        assert voice.start_ms == commentary.start_ms
        assert voice.duration_ms == commentary.duration_ms
    result = next((cue for cue in prepared.cues if cue.id == "director-result"), None)
    if result is not None:
        assert result.start_ms + result.duration_ms <= prepared.duration_ms
    # The stored copy agrees with what prepare returned, so a caller can trust either.
    stored = await service.require(production.id)
    assert stored.duration_ms == prepared.duration_ms
    assert [cue.start_ms for cue in stored.cues] == [cue.start_ms for cue in prepared.cues]
    await database.close()


@pytest.mark.asyncio
async def test_export_manifest_snapshots_the_style_without_media_or_secrets(
    tmp_path: Path, match_config: MatchConfig
) -> None:
    database, service, match_id, _ = await _service(tmp_path, match_config)
    production = await service.create(
        match_id, CreateProduction(profile_id="youtube", style_id="fighting", title="Cut A")
    )
    snapshot = style_snapshot(production)
    assert snapshot["preset_id"] == "fighting"
    assert snapshot["title"] == "Cut A"
    assert snapshot["hud"]["preset"] == "fighting"
    assert snapshot["brand_asset_ids"] == []
    serialized = json.dumps(snapshot)
    assert "base64" not in serialized and "api_key" not in serialized.lower()
    assert str(tmp_path) not in serialized, "no filesystem paths in the manifest"

    # Editing the saved preset later must not rewrite how this export looked.
    await service.save_style_preset(
        SaveStylePreset(
            display_name="Fighting mine",
            style=production.style.model_copy(update={"show_koala_branding": False}),
        )
    )
    assert style_snapshot(production)["koala_branding"] is True
    await database.close()
