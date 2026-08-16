#!/usr/bin/env python3
"""Capture the local visual review pack for a dogfooding pass.

Screenshots and clips land in an ignored directory; nothing from this script is committed,
and no Pokemon-derived media leaves the machine.

    docker compose up -d showdown team-validator
    # backend on :8001, frontend on :5173
    python scripts/capture_review_pack.py --match <manual-match-uuid>
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "data/review-pack/dogfooding-fix"


def post(url: str, payload: dict[str, object]) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return json.loads(response.read())


def get(url: str) -> dict[str, object] | list[object]:
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
        return json.loads(response.read())


def advance(api: str, match_id: str, commentary: str) -> int:
    """Answer every pending manual request with its first legal action."""
    pending = get(f"{api}/api/matches/{match_id}/pending")
    assert isinstance(pending, dict)
    requests = pending.get("requests", [])
    assert isinstance(requests, list)
    for item in requests:
        assert isinstance(item, dict)
        actions = item["legal_actions"]
        post(
            f"{api}/api/decisions/{item['request_id']}",
            {
                "raw_response": json.dumps(
                    {
                        "action": actions[0]["id"],
                        "commentary": commentary,
                        "strategy_memory": "Keep a healthy pivot in reserve.",
                    }
                )
            },
        )
    return len(requests)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--match", required=True, help="manual vs manual match UUID")
    parser.add_argument("--gen1-match", default=None, help="completed Gen 1 match UUID")
    parser.add_argument("--frontend", default="http://localhost:5173")
    parser.add_argument("--api", default="http://localhost:8001")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed in this environment", file=sys.stderr)
        return 1

    args.output.mkdir(parents=True, exist_ok=True)
    control = f"{args.frontend}/battle/{args.match}"
    watch = f"{args.frontend}/watch/{args.match}"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()

        def shot(
            name: str,
            url: str,
            width: int,
            height: int,
            *,
            settle: float = 3.0,
            full_page: bool = False,
            scroll_to: str | None = None,
        ) -> None:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(url, wait_until="networkidle")
            if scroll_to:
                page.locator(scroll_to).first.scroll_into_view_if_needed()
            time.sleep(settle)
            page.screenshot(path=args.output / name, full_page=full_page)
            page.close()
            print(f"wrote {name}")

        shot("new-match-desktop.png", f"{args.frontend}/new", 1440, 1000)
        shot(
            "new-match-format-picker.png",
            f"{args.frontend}/new",
            1440,
            1000,
            settle=1.0,
        )
        shot("battle-neutral.png", watch, 1920, 1080)
        shot("battle-vertical.png", f"{watch}?layout=standard-vertical", 1080, 1920)
        shot("control-desktop.png", control, 1440, 1000, full_page=True)
        shot("control-mobile.png", control, 390, 844, full_page=True)

        # Manual workspaces, one screenshot per agent tab. The workspace only exists while a
        # manual turn is pending, so skip rather than fail on a match that is not waiting.
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(control, wait_until="networkidle")
        time.sleep(3)
        if page.locator(".workspace").count():
            tabs = page.locator(".agent-tabs button")
            for index, name in enumerate(("manual-gemini.png", "manual-chatgpt.png")):
                if index < tabs.count() and tabs.nth(index).is_enabled():
                    tabs.nth(index).click()
                    time.sleep(1)
                page.locator(".workspace").scroll_into_view_if_needed()
                time.sleep(0.6)
                page.screenshot(path=args.output / name)
                print(f"wrote {name}")
        else:
            print(
                "no manual turn pending; skipped the workspace shots", file=sys.stderr
            )
        page.close()

        # Live capture: commentary panel, then the damage readout on the same turn.
        viewer = browser.new_page(viewport={"width": 1920, "height": 1080})
        viewer.goto(watch, wait_until="networkidle")
        time.sleep(2)
        advance(
            args.api, args.match, "Pressing the advantage before the matchup turns."
        )
        time.sleep(1.2)
        viewer.screenshot(path=args.output / "battle-commentary.png")
        print("wrote battle-commentary.png")
        captured = False
        for _ in range(90):
            if viewer.locator(".hp-delta").count():
                viewer.screenshot(path=args.output / "battle-damage.png")
                print("wrote battle-damage.png")
                captured = True
                break
            time.sleep(0.1)
        if not captured:
            print("no damage readout appeared in the capture window", file=sys.stderr)
        viewer.close()

        if args.gen1_match:
            shot(
                "battle-gen1.png",
                f"{args.frontend}/watch/{args.gen1_match}",
                1920,
                1080,
            )

        browser.close()

    print(f"\nReview pack: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
