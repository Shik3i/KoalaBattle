from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

from koalabattle import __version__
from koalabattle.video.models import RENDERER_VERSION


def test_documentation_and_setup_references_are_current() -> None:
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [sys.executable, str(root / "scripts/check_docs.py")],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_release_version_is_consistent_across_artifacts() -> None:
    root = Path(__file__).resolve().parents[3]
    backend_package = tomllib.loads((root / "backend" / "pyproject.toml").read_text())
    frontend_package = json.loads((root / "frontend" / "package.json").read_text())
    frontend_lock = json.loads((root / "frontend" / "package-lock.json").read_text())

    assert backend_package["project"]["version"] == __version__
    assert frontend_package["version"] == __version__
    assert frontend_lock["version"] == __version__
    assert frontend_lock["packages"][""]["version"] == __version__
    assert RENDERER_VERSION.startswith(f"{__version__}-")
    assert f"KoalaBattle {__version__}" in (
        root / "docs" / "RELEASE_READINESS.md"
    ).read_text()
    assert f"KoalaBattle {__version__}" in (
        root / "frontend" / "src" / "routes" / "+layout.svelte"
    ).read_text()
    assert f"KOALABATTLE {__version__}" in (
        root / "frontend" / "src" / "routes" / "overlay" / "tournament" / "[id]" / "+page.svelte"
    ).read_text()
