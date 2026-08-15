#!/usr/bin/env python3
"""Lightweight repository documentation and setup consistency checks."""

from __future__ import annotations

import re
import sys
from pathlib import Path

LINK = re.compile(r"(?<!!)\[[^]]*]\(([^)]+)\)")
SCRIPT = re.compile(r"(?:python3?|\.venv/bin/python)\s+([\w./-]+\.py)\b")
COMPOSE_PATH = re.compile(r"(?:dockerfile:|(?:^|\s)-\s+\.?/)([^\s:#]+)", re.MULTILINE)
COMPOSE_ENV = re.compile(r"\b(KOALABATTLE_[A-Z0-9_]+)\s*:")


def markdown_files(root: Path) -> list[Path]:
    return [root / "README.md", *sorted((root / "docs").glob("*.md"))]


def check(root: Path) -> list[str]:
    problems: list[str] = []
    for document in markdown_files(root):
        text = document.read_text(encoding="utf-8")
        for raw_target in LINK.findall(text):
            target = raw_target.strip().split("#", 1)[0]
            if not target or "://" in target or target.startswith(("mailto:", "/")):
                continue
            resolved = (document.parent / target).resolve()
            if not resolved.exists():
                problems.append(f"{document.relative_to(root)}: broken link {raw_target}")
        for script in SCRIPT.findall(text):
            if not (root / script).is_file():
                problems.append(f"{document.relative_to(root)}: missing script {script}")

    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    for relative in COMPOSE_PATH.findall(compose):
        candidate = relative.rstrip("/")
        if candidate.startswith("${") or candidate in {"data", "data/assets"}:
            continue
        if not (root / candidate).exists():
            problems.append(f"docker-compose.yml: missing path {candidate}")

    env_text = (root / ".env.example").read_text(encoding="utf-8")
    env_keys = {
        line.split("=", 1)[0].strip()
        for line in env_text.splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }
    for key in sorted(set(COMPOSE_ENV.findall(compose)) - env_keys):
        if key not in {"KOALABATTLE_ASSET_ROOT"}:
            problems.append(f".env.example: missing Compose key {key}")

    required = {
        "scripts/setup_assets.py",
        "scripts/check_docs.py",
        "Dockerfile.backend",
        "Dockerfile.frontend",
        "showdown/Dockerfile",
    }
    for relative in sorted(required):
        if not (root / relative).is_file():
            problems.append(f"missing required setup path {relative}")
    return problems


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    problems = check(root)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print(f"Documentation check passed ({len(markdown_files(root))} Markdown files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
