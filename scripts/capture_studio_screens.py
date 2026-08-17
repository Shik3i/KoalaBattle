#!/usr/bin/env python3
"""Screenshot the Video Studio workspace at several viewports.

Application UI cannot be judged from a rendered video frame, so the Studio itself is
captured separately. Output lands in an ignored review directory.

    # backend on :8001, frontend on :3000
    python scripts/capture_studio_screens.py --production <uuid> --match <uuid>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "data/review-pack/video-studio"

#: `details` summaries in the settings panel, opened one at a time so each screenshot shows
#: a real populated section rather than a wall of collapsed rows.
SECTIONS = (
    ("video-studio", None, 1600, 1100),
    ("video-studio-player-branding", "Player branding", 1600, 1100),
    ("video-studio-arena", "Arena", 1600, 1100),
    ("video-studio-hud", "HUD", 1600, 1100),
    ("video-studio-mobile", None, 390, 844),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production", required=True)
    parser.add_argument("--match", required=True)
    parser.add_argument("--frontend", default="http://localhost:3000")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed", file=sys.stderr)
        return 1

    written: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for name, section, width, height in SECTIONS:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(
                f"{args.frontend}/studio/{args.production}", wait_until="networkidle"
            )
            page.wait_for_selector("canvas", timeout=30_000)
            # The preview paints asynchronously; wait for a frame rather than a fixed sleep.
            page.wait_for_function(
                "() => { const c = document.querySelector('canvas');"
                " return c && c.width > 0 && c.height > 0; }",
                timeout=30_000,
            )
            if section:
                page.get_by_text(section, exact=True).click()
                page.wait_for_timeout(400)
            page.wait_for_timeout(900)
            target = args.output / f"{name}.png"
            page.screenshot(path=str(target), full_page=section is not None)
            written.append(target.name)
            page.close()

        page = browser.new_page(viewport={"width": 1600, "height": 1100})
        page.goto(f"{args.frontend}/replay/{args.match}", wait_until="networkidle")
        page.wait_for_timeout(1500)
        target = args.output / "replay-create-video.png"
        page.screenshot(path=str(target))
        written.append(target.name)
        page.close()
        browser.close()

    print("\n".join(written))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
