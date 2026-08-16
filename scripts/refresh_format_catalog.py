#!/usr/bin/env python3
"""Regenerate the bundled Showdown format snapshot from the pinned local Showdown build.

KoalaBattle never hand-maintains a format allowlist. The pinned Pokemon Showdown runtime is
the single source of truth; this script copies its registry into a snapshot the backend can
read when the Showdown container is not running (tests, offline start-up, CI).

    docker compose up -d showdown team-validator
    python scripts/refresh_format_catalog.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = (
    PROJECT_ROOT / "backend/koalabattle/formats/showdown-format-catalog.json"
)
DEFAULT_SOURCE = "http://localhost:8002"


def fetch(source: str, timeout: float) -> dict[str, object]:
    request = Request(
        f"{source.rstrip('/')}/formats", headers={"Accept": "application/json"}
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            payload = json.loads(response.read(8_000_000))
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise RuntimeError(
            f"could not read the Showdown format registry at {source}: {error}. "
            "Start it with: docker compose up -d showdown team-validator"
        ) from error
    if not isinstance(payload, dict) or not isinstance(payload.get("formats"), list):
        raise RuntimeError("Showdown format endpoint returned an unexpected payload")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()

    try:
        payload = fetch(args.source, args.timeout)
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1

    formats = payload["formats"]
    assert isinstance(formats, list)
    payload["formats"] = sorted(
        formats,
        key=lambda item: (-int(item.get("generation", 0)), str(item.get("id", ""))),
    )
    args.target.parent.mkdir(parents=True, exist_ok=True)
    args.target.write_text(
        json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    generations = sorted({int(item["generation"]) for item in payload["formats"]})
    print(f"Wrote {len(payload['formats'])} formats to {args.target}")
    print(f"Generations: {', '.join(str(item) for item in generations)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
