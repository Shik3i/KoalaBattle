#!/usr/bin/env python3
"""Capture and compare deterministic 16:9 and 9:16 production frames.

    python scripts/visual_regression.py --landscape <production-id> --vertical <production-id> --accept
    python scripts/visual_regression.py --landscape <production-id> --vertical <production-id>

Baselines and current captures stay below ignored ``data/visual-regression`` because they may
contain locally installed Pokémon media. Exact matches pass immediately; a high SSIM threshold
tolerates only subpixel browser rasterization drift.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def similarity(expected: Path, current: Path) -> float:
    if digest(expected) == digest(current):
        return 1.0
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(expected), "-i", str(current), "-lavfi", "ssim", "-f", "null", "-"],
        check=False,
        capture_output=True,
        text=True,
    )
    match = re.search(r"All:([0-9.]+)", result.stderr)
    if result.returncode or not match:
        raise RuntimeError(f"FFmpeg could not compare {current.name}: {result.stderr[-500:]}")
    return float(match.group(1))


def production_duration(api: str, production_id: str) -> int:
    import json

    with urllib.request.urlopen(f"{api}/api/productions/{production_id}", timeout=30) as response:  # noqa: S310
        payload = json.load(response)
    return int(payload["duration_ms"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--landscape", required=True, help="16:9 production UUID")
    parser.add_argument("--vertical", required=True, help="9:16 production UUID")
    parser.add_argument("--frontend", default="http://localhost:3001")
    parser.add_argument("--api", default="http://localhost:8001")
    parser.add_argument("--output", type=Path, default=ROOT / "data/visual-regression")
    parser.add_argument("--accept", action="store_true", help="replace local baselines")
    parser.add_argument("--threshold", type=float, default=0.99, help="minimum FFmpeg SSIM")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        parser.error("Playwright is unavailable; install the backend renderer extra")

    baseline = args.output / "baseline"
    current = args.output / "current"
    baseline.mkdir(parents=True, exist_ok=True)
    current.mkdir(parents=True, exist_ok=True)
    cases = (("landscape", args.landscape, 1920, 1080), ("vertical", args.vertical, 1080, 1920))
    failures: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for label, production_id, width, height in cases:
            duration = production_duration(args.api, production_id)
            page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
            page.goto(f"{args.frontend}/render/{production_id}", wait_until="networkidle", timeout=60_000)
            page.wait_for_function("window.__KOALABATTLE_RENDER_READY === true", timeout=60_000)
            for beat, milliseconds in (("intro", 0), ("mid", duration // 2), ("result", max(0, duration - 100))):
                page.evaluate("ms => window.__KOALABATTLE_RENDER_AT(ms)", milliseconds)
                target = current / f"{label}-{beat}.png"
                page.screenshot(path=target)
                expected = baseline / target.name
                if args.accept or not expected.exists():
                    shutil.copyfile(target, expected)
                    print(f"accepted {expected.relative_to(ROOT)}")
                else:
                    score = similarity(expected, target)
                    if score >= args.threshold:
                        print(f"matched  {target.relative_to(ROOT)} · SSIM {score:.6f}")
                        continue
                    failures.append(target.name)
                    print(f"changed  {target.relative_to(ROOT)} · SSIM {score:.6f}")
            page.close()
        browser.close()

    if failures:
        print("visual regressions: " + ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
