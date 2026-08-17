#!/usr/bin/env python3
"""Render one recorded match through several Video Studio presentations.

Every clip here goes through the normal path:

    battle archive -> Production + ProductionStyle -> native compositor -> ffmpeg mux

so a clip that looks wrong is evidence of a real production problem, never of a shortcut
taken by this script. Custom logos and backgrounds are synthetic fixtures generated here,
because KoalaBattle must not redistribute third-party brand images.

    docker compose up -d showdown team-validator
    # backend on :8001
    python scripts/capture_studio_pack.py --match <uuid> --output data/review-pack/studio
"""

from __future__ import annotations

import argparse
import base64
import json
import struct
import subprocess
import sys
import urllib.request
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from capture_review_clips import (  # noqa: E402
    Clip,
    collect,
    commentary_action_window,
    cues,
    export,
    fetch_production,
    prepare_speech,
    request,
    still,
    victory_window,
    window,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "data/review-pack/video-studio"


def png(width: int, height: int, pixel: tuple[int, int, int, int]) -> bytes:
    """A real RGBA PNG. Used for synthetic branding fixtures only."""
    raw = b"".join(b"\x00" + bytes(pixel) * width for _ in range(height))

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">II", width, height) + bytes([8, 6, 0, 0, 0]))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def gradient_png(
    width: int, height: int, left: tuple[int, int, int], right: tuple[int, int, int]
) -> bytes:
    rows = []
    for _ in range(height):
        row = bytearray(b"\x00")
        for x in range(width):
            ratio = x / max(1, width - 1)
            row += bytes(
                (
                    int(left[0] + (right[0] - left[0]) * ratio),
                    int(left[1] + (right[1] - left[1]) * ratio),
                    int(left[2] + (right[2] - left[2]) * ratio),
                    255,
                )
            )
        rows.append(bytes(row))

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">II", width, height) + bytes([8, 6, 0, 0, 0]))
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 6))
        + chunk(b"IEND", b"")
    )


def upload(api: str, kind: str, name: str, payload: bytes) -> dict[str, object]:
    return request(
        f"{api}/api/branding/assets",
        {
            "kind": kind,
            "display_name": name,
            "data_base64": base64.b64encode(payload).decode(),
        },
    )


def styles(api: str) -> dict[str, dict[str, object]]:
    presets = json.loads(
        urllib.request.urlopen(f"{api}/api/production/styles", timeout=60).read()
    )  # noqa: S310
    return {preset["id"]: preset["style"] for preset in presets}


def create_production(
    api: str,
    match_id: str,
    profile: str,
    style_id: str,
    title: str,
    voices: dict[str, str],
) -> dict[str, object]:
    return request(
        f"{api}/api/matches/{match_id}/productions",
        {
            "profile_id": profile,
            "voice_assignments": voices,
            "style_id": style_id,
            "title": title,
        },
    )


def apply_style(
    api: str, production_id: str, style: dict[str, object]
) -> dict[str, object]:
    return request(
        f"{api}/api/productions/{production_id}/update",
        {"style": style, "title": None, "clear_title": False},
    )


def probe(path: Path) -> str:
    result = subprocess.run(  # noqa: S603
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,avg_frame_rate,nb_frames",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return "probe failed"
    data = json.loads(result.stdout)
    stream = data["streams"][0]
    return (
        f"{stream['width']}x{stream['height']} @ {stream['avg_frame_rate']} "
        f"· {float(data['format']['duration']):.1f}s"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--match", required=True)
    parser.add_argument("--api", default="http://localhost:8001")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--prefix", default="")
    parser.add_argument("--encoder", default="auto")
    parser.add_argument("--length-ms", type=int, default=11_000)
    parser.add_argument(
        "--presets",
        default="fighting,minimal,retro,vertical",
        help="comma-separated style ids to render",
    )
    parser.add_argument("--skip-assets", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    wanted = [item.strip() for item in args.presets.split(",") if item.strip()]
    voices = {"p1": "edge-neural-p1", "p2": "edge-neural-p2"}
    library = styles(args.api)

    assets: dict[str, str] = {}
    if not args.skip_assets:
        # Deliberately awkward shapes: a transparent square, a wide non-square banner and a
        # portrait background, so fit and aspect handling are exercised rather than assumed.
        fixtures = {
            "logo_square": (
                "logo",
                "Fixture square logo",
                png(256, 256, (64, 220, 160, 190)),
            ),
            "logo_wide": (
                "logo",
                "Fixture wide logo",
                png(512, 128, (255, 140, 90, 255)),
            ),
            "background_wide": (
                "background",
                "Fixture 16:9 background",
                gradient_png(960, 540, (34, 8, 40), (10, 30, 66)),
            ),
            "background_portrait": (
                "background",
                "Fixture portrait background",
                gradient_png(540, 960, (12, 40, 30), (40, 12, 24)),
            ),
            "watermark": (
                "watermark",
                "Fixture watermark",
                png(128, 128, (255, 255, 255, 120)),
            ),
        }
        for key, (kind, name, payload) in fixtures.items():
            asset = upload(args.api, kind, name, payload)
            assets[key] = str(asset["id"])
            print(f"uploaded {kind}: {asset['display_name']} -> {asset['id']}")

    manifest: list[dict[str, object]] = []
    for style_id in wanted:
        base = library.get(style_id)
        if base is None:
            print(f"unknown style {style_id}", file=sys.stderr)
            continue
        vertical = style_id == "vertical"
        profile = "shorts" if vertical else "youtube"
        preset = "vertical-1080p60" if vertical else "youtube-1080p60"
        production = create_production(
            args.api,
            args.match,
            profile,
            style_id,
            f"{base['display_name']} cut",
            voices,
        )
        production_id = str(production["id"])

        if style_id == "fighting" and assets:
            # The Fighting cut also proves custom media: uploaded logos, an uploaded
            # background and a watermark all have to survive the offline compositor.
            style = json.loads(json.dumps(production["style"]))
            style["stage"]["background"].update(
                {
                    "kind": "image",
                    "asset_id": assets["background_wide"],
                    "fit": "cover",
                    "brightness": 0.85,
                    "blur": 2,
                    "overlay_opacity": 0.15,
                }
            )
            style["players"]["p1"]["logo_asset_id"] = assets["logo_square"]
            style["players"]["p2"]["logo_asset_id"] = assets["logo_wide"]
            style["watermark"].update(
                {
                    "enabled": True,
                    "asset_id": assets["watermark"],
                    "opacity": 0.5,
                    "size": 0.8,
                }
            )
            style["series"].update(
                {"game_number": 2, "best_of": 3, "score_p1": 1, "score_p2": 0}
            )
            style["intro"].update({"show_game_number": True, "show_series_score": True})
            production = apply_style(args.api, production_id, style)
        if style_id == "vertical" and assets:
            style = json.loads(json.dumps(production["style"]))
            style["stage"]["background"].update(
                {
                    "kind": "image",
                    "asset_id": assets["background_portrait"],
                    "fit": "cover",
                }
            )
            production = apply_style(args.api, production_id, style)

        _, speech_seconds = prepare_speech(args.api, production_id)
        # Preparation retimes the clock; never reuse the pre-preparation object.
        production = fetch_production(args.api, production_id)
        voice_cues = sum(1 for cue in cues(production) if cue.get("track") == "voice")
        print(
            f"{style_id}: production {production_id} "
            f"({production['duration_ms']} ms, speech {speech_seconds:.1f}s, {voice_cues} voice cues)"
        )

        found = commentary_action_window(
            production, length_ms=args.length_ms
        ) or window(
            production, anchor_kind="damage", lead_ms=2_000, length_ms=args.length_ms
        )
        if not found:
            print(f"{style_id}: no action window found", file=sys.stderr)
            continue
        name = f"{args.prefix}customization-{style_id}"
        job = export(
            args.api, production_id, Clip(name, preset, *found, style_id), args.encoder
        )
        if job["status"] != "completed":
            print(
                f"{style_id}: export failed: {job.get('error_detail')}", file=sys.stderr
            )
            continue
        written = collect(args.api, job, args.output, name)
        video = next((path for path in written if path.suffix == ".mp4"), None)
        if video:
            still(video, args.output / f"style-{style_id}.png", 5.0)
        manifest.append(
            {
                "style": style_id,
                "production": production_id,
                "clip": name,
                "probe": probe(video) if video else "missing",
                "speed_ratio": job.get("render_duration_ms")
                and round(
                    (int(job["end_ms"]) - int(job["start_ms"]))
                    / int(job["render_duration_ms"]),
                    3,
                ),
                "render_ms": job.get("render_duration_ms"),
                "frames": job.get("output_frame_count"),
                "unique_frames": job.get("unique_rendered_frames"),
            }
        )
        print(
            f"{style_id}: {video.name if video else 'no video'} {manifest[-1]['probe']}"
        )

        # Intro proof: the same production rendered with and without format text, so the
        # toggle can be judged rather than taken on trust.
        if style_id == "fighting":
            # Track *and* kind: other tracks reuse director kind names, and matching on
            # kind alone is what pointed the victory window at an sfx cue.
            intro_cue = next(
                (
                    cue
                    for cue in cues(production)
                    if cue.get("track") == "director"
                    and cue.get("kind") == "match-intro"
                ),
                None,
            )
            if intro_cue is not None:
                middle = int(intro_cue["start_ms"]) + int(intro_cue["duration_ms"]) // 2
                for label, patch in (
                    (
                        "intro-format-on",
                        {"show_format": True, "show_player_logos": True},
                    ),
                    (
                        "intro-format-off",
                        {"show_format": False, "show_player_logos": True},
                    ),
                    (
                        "intro-player-logos",
                        {"show_format": True, "show_player_logos": False},
                    ),
                ):
                    style = json.loads(json.dumps(production["style"]))
                    style["intro"].update(patch)
                    apply_style(args.api, production_id, style)
                    shot = export(
                        args.api,
                        production_id,
                        Clip(
                            f"{args.prefix}{label}",
                            preset,
                            max(0, middle - 500),
                            middle + 900,
                            label,
                        ),
                        args.encoder,
                    )
                    if shot["status"] != "completed":
                        continue
                    files = collect(
                        args.api, shot, args.output, f"{args.prefix}{label}"
                    )
                    clip = next((path for path in files if path.suffix == ".mp4"), None)
                    if clip:
                        still(clip, args.output / f"{label}.png", 0.6)
                        clip.unlink(missing_ok=True)
                        (args.output / f"{args.prefix}{label}.srt").unlink(
                            missing_ok=True
                        )
                apply_style(args.api, production_id, production["style"])
                production = fetch_production(args.api, production_id)

    victory = victory_window(production, length_ms=8_000) if manifest else None
    if victory:
        job = export(
            args.api,
            str(production["id"]),
            Clip(f"{args.prefix}customization-result", preset, *victory, "result card"),
            args.encoder,
        )
        if job["status"] == "completed":
            written = collect(
                args.api, job, args.output, f"{args.prefix}customization-result"
            )
            video = next((path for path in written if path.suffix == ".mp4"), None)
            if video:
                still(
                    video, args.output / "style-result.png", float(8_000 - 1_200) / 1000
                )
                manifest.append(
                    {"style": "result", "clip": video.stem, "probe": probe(video)}
                )

    (args.output / "studio-pack.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))
    return 0 if manifest else 1


if __name__ == "__main__":
    raise SystemExit(main())
