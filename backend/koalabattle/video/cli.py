from __future__ import annotations

import argparse
import json
import time
from typing import Any, cast
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def call(api_url: str, path: str, payload: dict[str, object] | None = None) -> Any:
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(
        f"{api_url.rstrip('/')}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310
            return json.load(response)
    except HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise SystemExit(f"API {error.code}: {detail}") from error


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m koalabattle.video.cli")
    parser.add_argument("--api-url", default="http://localhost:8001")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("capabilities")
    render = sub.add_parser("render")
    render.add_argument("source", choices=("match", "production"))
    render.add_argument("id")
    render.add_argument("--preset", default="youtube-1080p60")
    render.add_argument("--backend", choices=("offline", "obs"), default="offline")
    render.add_argument("--profile", default="youtube")
    render.add_argument("--output-name")
    render.add_argument("--encoder", default="auto")
    render.add_argument("--render-engine", choices=("native", "legacy"), default="native")
    render.add_argument("--wait", action="store_true")
    args = parser.parse_args()
    if args.command == "capabilities":
        print(json.dumps(call(args.api_url, "/api/video/capabilities"), indent=2))
        return
    production_id = args.id
    if args.source == "match":
        productions = cast(
            list[dict[str, object]], call(args.api_url, f"/api/matches/{args.id}/productions")
        )
        candidates = [
            item
            for item in productions
            if cast(dict[str, object], item["profile"])["id"] == args.profile
            and item["status"] in {"finalized", "ready", "partial"}
        ]
        matching = next(
            (
                item
                for item in candidates
                if (voices := item.get("voice_assignments"))
                and isinstance(voices, dict)
                and all(str(value).startswith("edge-neural-") for value in voices.values())
            ),
            None,
        ) or (candidates[0] if candidates else None)
        if matching is None:
            matching = call(
                args.api_url,
                f"/api/matches/{args.id}/productions",
                {"profile_id": args.profile, "voice_assignments": {}},
            )
        production_id = str(matching["id"])
    job = cast(
        dict[str, object],
        call(
            args.api_url,
            "/api/video/jobs",
            {
                "production_id": production_id,
                "backend": args.backend,
                "preset_id": args.preset,
                "output_name": args.output_name,
                "encoder": args.encoder,
                "render_engine": args.render_engine,
            },
        ),
    )
    print(json.dumps(job, indent=2))
    while args.wait and job["status"] not in {"completed", "failed", "cancelled"}:
        time.sleep(1)
        job = cast(dict[str, object], call(args.api_url, f"/api/video/jobs/{job['id']}"))
        print(f"{job['status']} {job['progress']}% {job['stage']}")
    if args.wait and job["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
