#!/usr/bin/env python3
"""Export short MP4 review clips through the real KoalaBattle production pipeline.

Screenshots cannot show choreography, pacing, HP interpolation or speech timing, so visual
review needs actual video. Every clip here is a time range of a real production exported by
the normal path:

    battle archive -> ProductionTimeline -> native compositor -> audio/captions -> ffmpeg mux

Nothing is stitched together from stills and nothing bypasses the exporter, so a clip that
looks wrong is evidence of a real production problem.

    docker compose up -d showdown team-validator
    # backend on :8001, frontend on :5173
    python scripts/capture_review_clips.py --match <uuid> --output data/review-pack/<name>
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "data/review-pack/dogfooding-media"

#: Cue kinds that carry the visual beats a reviewer needs to judge.
ACTION_KINDS = {"move_used", "damage", "critical_hit", "super_effective", "move_missed"}


@dataclass(frozen=True)
class Clip:
    name: str
    preset: str
    start_ms: int
    end_ms: int
    description: str


def request(url: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    call = urllib.request.Request(
        url, data=data, headers=headers, method="POST" if data else "GET"
    )
    with urllib.request.urlopen(call, timeout=600) as response:  # noqa: S310
        return json.loads(response.read())


def ensure_production(
    api: str, match_id: str, profile: str, voices: dict[str, str]
) -> dict[str, object]:
    """Reuse a production for this profile when one exists, so speech stays cached."""
    existing = json.loads(
        urllib.request.urlopen(  # noqa: S310
            f"{api}/api/matches/{match_id}/productions", timeout=120
        ).read()
    )
    for item in existing:
        if item["profile"]["id"] == profile and item["voice_assignments"] == voices:
            return item
    return request(
        f"{api}/api/matches/{match_id}/productions",
        {"profile_id": profile, "voice_assignments": voices},
    )


def prepare_speech(api: str, production_id: str) -> tuple[dict[str, object], float]:
    """Synthesize any missing speech and return the production that now owns those cues.

    Order matters: `rebuild` regenerates the timeline from the archive and drops synthesized
    voice cues, so it must never run after preparation.
    """
    started = time.monotonic()
    production = request(
        f"{api}/api/productions/{production_id}/prepare",
        {"force": False, "allow_paid": False},
    )
    return production, time.monotonic() - started


def fetch_production(api: str, production_id: str) -> dict[str, object]:
    """Always read the stored production before computing a clip window.

    Preparation retimes the whole clock against real speech durations, so any object held
    from before that call describes the wrong moments. Computing a window from a stale copy
    is what put the result card outside the "victory" range.
    """
    return json.loads(
        urllib.request.urlopen(
            f"{api}/api/productions/{production_id}", timeout=120
        ).read()  # noqa: S310
    )


def cues(production: dict[str, object]) -> list[dict[str, object]]:
    value = production.get("cues", [])
    return list(value) if isinstance(value, list) else []


def window(
    production: dict[str, object], *, anchor_kind: str, lead_ms: int, length_ms: int
) -> tuple[int, int] | None:
    """Find the first cue of a kind and return a clip window that leads into it."""
    for cue in cues(production):
        if cue.get("kind") != anchor_kind:
            continue
        start = max(0, int(cue["start_ms"]) - lead_ms)
        return start, start + length_ms
    return None


def commentary_action_window(
    production: dict[str, object], *, length_ms: int
) -> tuple[int, int] | None:
    """Frame the complete beat: commentary and speech, then the move landing.

    Anchoring on the first commentary wastes most of a short clip, because a turn holds for
    both players' speech before any action resolves. Anchoring on the action and walking
    back to the commentary that introduced it keeps the whole beat with the least dead air.
    """
    ordered = sorted(cues(production), key=lambda cue: int(cue["start_ms"]))
    commentaries = [c for c in ordered if c.get("kind") == "public-agent-commentary"]
    if not commentaries:
        return None
    moves = [c for c in ordered if c.get("kind") == "move_used"]
    damages = [c for c in ordered if c.get("kind") == "damage"]
    for move in moves:
        move_at = int(move["start_ms"])
        if not any(move_at <= int(d["start_ms"]) <= move_at + 2_500 for d in damages):
            continue
        preceding = [c for c in commentaries if int(c["start_ms"]) < move_at]
        if not preceding:
            continue
        start = max(0, int(preceding[-1]["start_ms"]) - 800)
        # Only accept the window when the action actually fits inside it.
        if move_at + 2_500 <= start + length_ms:
            return start, start + length_ms
    return None


def effects_window(
    production: dict[str, object], *, length_ms: int
) -> tuple[int, int] | None:
    """Pick the densest stretch of distinct visual beats, so one clip shows variety."""
    ordered = sorted(cues(production), key=lambda cue: int(cue["start_ms"]))
    visual = [
        cue
        for cue in ordered
        if cue.get("track") == "visual"
        and cue.get("kind")
        in ACTION_KINDS
        | {"pokemon_switched", "pokemon_fainted", "status_applied", "resisted"}
    ]
    best: tuple[int, int] | None = None
    best_score = -1
    for cue in visual:
        start = max(0, int(cue["start_ms"]) - 400)
        inside = [
            item
            for item in visual
            if start <= int(item["start_ms"]) < start + length_ms
        ]
        kinds = {item["kind"] for item in inside}
        score = len(kinds)
        # A faint that is never followed by its replacement leaves a body on the field for
        # the rest of the clip, so only reward it when the switch also fits.
        if "pokemon_fainted" in kinds and "pokemon_switched" not in kinds:
            score -= 2
        if score > best_score:
            best_score = score
            best = (start, start + length_ms)
    return best


def victory_window(
    production: dict[str, object], *, length_ms: int
) -> tuple[int, int] | None:
    """End on the result banner, not just near it.

    Anchoring on the result cue's start clipped the clip before the banner played, so the
    "victory" clip showed two ordinary turns and then stopped.
    """
    duration = int(production.get("duration_ms") or 0)
    # Match on the track as well as the kind. The sfx track also uses kind "result", so
    # matching on kind alone picked a half-second sound cue several seconds before the
    # banner and ended the clip there — which is why the "victory" clip kept showing two
    # ordinary turns and stopping.
    result = next(
        (
            cue
            for cue in cues(production)
            if cue.get("track") == "director" and cue.get("kind") == "result"
        ),
        None,
    )
    if result is not None:
        end = int(result["start_ms"]) + int(result["duration_ms"])
        if duration:
            end = min(duration, end)
        return max(0, end - length_ms), end
    if duration:
        return max(0, duration - length_ms), duration
    return None


def export(api: str, production_id: str, clip: Clip, encoder: str) -> dict[str, object]:
    started = time.monotonic()
    job = request(
        f"{api}/api/video/jobs",
        {
            "production_id": production_id,
            "backend": "offline",
            "preset_id": clip.preset,
            "output_name": clip.name,
            "start_ms": clip.start_ms,
            "end_ms": clip.end_ms,
            "encoder": encoder,
            "render_engine": "native",
        },
    )
    job_id = job["id"]
    while True:
        current = json.loads(
            urllib.request.urlopen(f"{api}/api/video/jobs/{job_id}", timeout=120).read()  # noqa: S310
        )
        status = current["status"]
        if status in {"completed", "failed", "cancelled"}:
            current["wall_seconds"] = round(time.monotonic() - started, 2)
            return current
        time.sleep(1.0)


def still(source: Path, target: Path, at_seconds: float) -> bool:
    """Pull one frame out of an exported clip.

    Stills taken from the clip are the same pixels the reviewer sees in motion, so a
    screenshot can never flatter the production more than the video does.
    """
    import subprocess

    result = subprocess.run(  # noqa: S603
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-ss",
            f"{at_seconds:.3f}",
            "-i",
            str(source),
            "-frames:v",
            "1",
            str(target),
        ],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0 and target.exists()


def collect(api: str, job: dict[str, object], output: Path, name: str) -> list[Path]:
    written: list[Path] = []
    for kind, suffix in (("download", ".mp4"), ("captions", ".srt")):
        target = output / f"{name}{suffix}"
        try:
            with (
                urllib.request.urlopen(  # noqa: S310
                    f"{api}/api/video/jobs/{job['id']}/{kind}", timeout=300
                ) as response,
                target.open("wb") as handle,
            ):
                shutil.copyfileobj(response, handle)
        except urllib.error.HTTPError:
            continue
        written.append(target)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--match", required=True, help="completed match UUID")
    parser.add_argument("--api", default="http://localhost:8001")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--prefix", default="", help="prefix for every clip filename")
    parser.add_argument("--encoder", default="auto")
    parser.add_argument("--voice-p1", default="edge-neural-p1")
    parser.add_argument("--voice-p2", default="edge-neural-p2")
    parser.add_argument(
        "--clips",
        default="commentary,effects,victory,vertical",
        help="comma-separated subset of commentary,effects,victory,vertical",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    wanted = {item.strip() for item in args.clips.split(",") if item.strip()}

    voices = {"p1": args.voice_p1, "p2": args.voice_p2}
    landscape = ensure_production(args.api, args.match, "youtube", voices)
    _, speech_seconds = prepare_speech(args.api, str(landscape["id"]))
    landscape = fetch_production(args.api, str(landscape["id"]))
    voice_cues = sum(1 for cue in cues(landscape) if cue.get("track") == "voice")
    print(f"landscape production {landscape['id']} ({landscape['duration_ms']} ms)")
    print(f"speech preparation: {speech_seconds:.1f}s for {voice_cues} voice cues")

    plans: list[tuple[Clip, str]] = []
    if "commentary" in wanted:
        found = commentary_action_window(landscape, length_ms=12_000)
        if found:
            plans.append(
                (
                    Clip(
                        f"{args.prefix}clip-a-commentary-attack-damage",
                        "youtube-1080p60",
                        *found,
                        "commentary -> speech -> move -> impact -> damage -> HP",
                    ),
                    str(landscape["id"]),
                )
            )
    if "effects" in wanted:
        found = effects_window(landscape, length_ms=12_000)
        if found:
            plans.append(
                (
                    Clip(
                        f"{args.prefix}clip-b-battle-effects",
                        "youtube-1080p60",
                        *found,
                        "several representative action states back to back",
                    ),
                    str(landscape["id"]),
                )
            )
    if "victory" in wanted:
        found = victory_window(landscape, length_ms=9_000)
        if found:
            plans.append(
                (
                    Clip(
                        f"{args.prefix}clip-d-victory",
                        "youtube-1080p60",
                        *found,
                        "final attack -> faint -> result",
                    ),
                    str(landscape["id"]),
                )
            )

    if "vertical" in wanted:
        # Vertical uses its own production so pacing and commentary limits match the layout
        # rather than being a crop of the landscape timeline.
        vertical = ensure_production(args.api, args.match, "shorts", voices)
        _, vertical_speech = prepare_speech(args.api, str(vertical["id"]))
        vertical = fetch_production(args.api, str(vertical["id"]))
        print(
            f"vertical production {vertical['id']} ({vertical['duration_ms']} ms, "
            f"speech {vertical_speech:.1f}s)"
        )
        found = commentary_action_window(vertical, length_ms=12_000) or window(
            vertical, anchor_kind="damage", lead_ms=2_000, length_ms=12_000
        )
        if found:
            plans.append(
                (
                    Clip(
                        f"{args.prefix}clip-c-vertical",
                        "vertical-1080p60",
                        *found,
                        "commentary + action + HP + captions, 1080x1920",
                    ),
                    str(vertical["id"]),
                )
            )

    if not plans:
        print("no clip windows could be located in this production", file=sys.stderr)
        return 1

    failures = 0
    for clip, production_id in plans:
        print(f"\n-> {clip.name} [{clip.start_ms}..{clip.end_ms} ms] {clip.preset}")
        job = export(args.api, production_id, clip, args.encoder)
        if job["status"] != "completed":
            print(f"   FAILED: {job.get('error') or job.get('stage')}", file=sys.stderr)
            failures += 1
            continue
        written = collect(args.api, job, args.output, clip.name)
        print(
            f"   {job.get('video_duration_ms')} ms, "
            f"{job.get('output_frame_count')} frames, "
            f"{job.get('width')}x{job.get('height')}@{job.get('fps')}, "
            f"render {job.get('render_duration_ms')} ms, "
            f"wall {job['wall_seconds']}s, encoder {job.get('selected_encoder')}"
        )
        unique = job.get("unique_rendered_frames")
        held = job.get("static_held_frames")
        if unique is not None:
            print(
                f"   unique frames {unique}, held {held}, animated {job.get('animated_frames')}"
            )
        for path in written:
            print(f"   wrote {path}")

    print(f"\nReview clips: {args.output}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
