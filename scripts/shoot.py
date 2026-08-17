"""Screenshot KoalaBattle pages from inside the renderer container.

Runs against the Docker-internal frontend with the container's own headless Chromium, so no
browser is ever launched on the operator's desktop. Output lands in the mounted video root.

    docker compose cp scripts/shoot.py renderer:/tmp/shoot.py
    docker compose exec renderer python /tmp/shoot.py <match-id>
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

FRONTEND = "http://frontend:3000"
# The page is built for a human's browser and calls the API on localhost:8001. Inside the
# container that is the renderer itself, so the calls have to be pointed at the service name.
BROWSER_API = "http://localhost:8001"
CONTAINER_API = "http://backend:8001"
OUT = Path("/data/videos/shots")


def main() -> None:
    match_id = sys.argv[1]
    only = sys.argv[2] if len(sys.argv) > 2 else ""
    shots = [
        ("watch", f"{FRONTEND}/watch/{match_id}", 1920, 1080),
        ("control", f"{FRONTEND}/battle/{match_id}", 1600, 1500),
        ("new", f"{FRONTEND}/new", 1600, 1200),
    ]
    if only:
        shots = [shot for shot in shots if shot[0] == only]
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path="/usr/bin/chromium", args=["--no-sandbox"]
        )
        for name, url, width, height in shots:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.route(
                f"{BROWSER_API}/**",
                lambda route: route.continue_(
                    url=route.request.url.replace(BROWSER_API, CONTAINER_API)
                ),
            )
            problems: list[str] = []
            page.on(
                "console",
                lambda message: problems.append(f"console {message.type}: {message.text}"[:200])
                if message.type in {"error", "warning"}
                else None,
            )
            page.on("pageerror", lambda error: problems.append(f"pageerror: {error}"[:200]))
            page.on(
                "requestfailed",
                lambda request: problems.append(
                    f"failed {request.method} {request.url}: {request.failure}"[:200]
                ),
            )
            page.goto(url, wait_until="networkidle", timeout=60_000)
            page.wait_for_timeout(2500)
            target = OUT / f"{name}.png"
            page.screenshot(path=str(target))
            body = page.inner_text("body")[:120].replace("\n", " | ")
            print(f"{name:8} -> {target}  text={body!r}")
            for problem in problems[:6]:
                print(f"         {problem}")
            page.close()
        browser.close()


if __name__ == "__main__":
    main()
