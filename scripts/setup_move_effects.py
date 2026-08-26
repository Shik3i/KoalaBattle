#!/usr/bin/env python3
"""Install optional, license-tracked move-effect textures into ignored local storage."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

SCHEMA = 1
MANIFEST = "move-effects-manifest.json"
ASSET_DIR = Path("effects")
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
EXTENSIONS = (".png", ".webp", ".jpg", ".jpeg")
SHOWDOWN_COMMIT = "daa28cfeb19775dea9f19f90a8c8f1418bac316a"
SHOWDOWN_REPOSITORY = "https://github.com/smogon/pokemon-showdown-client"
SHOWDOWN_BASE = (
    f"https://raw.githubusercontent.com/smogon/pokemon-showdown-client/{SHOWDOWN_COMMIT}/"
    "play.pokemonshowdown.com/fx/"
)
SHOWDOWN_LICENSE = f"https://raw.githubusercontent.com/smogon/pokemon-showdown-client/{SHOWDOWN_COMMIT}/play.pokemonshowdown.com/src/battle-animations.ts"
SHOWDOWN_FILES = (
    "wisp.png", "poisonwisp.png", "waterwisp.png", "mudwisp.png", "blackwisp.png",
    "fireball.png", "bluefireball.png", "leaf1.png", "leaf2.png", "caltrop.png",
    "greenmetal1.png", "greenmetal2.png", "poisoncaltrop.png", "shadowball.png",
    "energyball.png", "electroball.png", "mistball.png", "iceball.png", "flareball.png",
    "moon.png", "fist.png", "fist1.png", "foot.png", "topbite.png", "bottombite.png",
    "web.png", "leftclaw.png", "rightclaw.png", "leftslash.png", "rightslash.png",
    "leftchop.png", "rightchop.png", "angry.png", "heart.png", "pointer.png",
    "sword.png", "impact.png", "stare.png", "shine.png", "feather.png", "shell.png",
    "petal.png", "gear.png", "rainbow.png", "hitmarker.png",
)
BLOCKED = {
    "icicle.png", "icicle-pink.png", "lightning.png", "bone.png", "rocks.png",
    "rock1.png", "rock2.png", "rock3.png", "pokeball.png", "alpha.png", "omega.png",
    "z-symbol.png", "ultra.png",
}


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_manifest(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA or not isinstance(value.get("packs"), dict):
        raise RuntimeError(f"unsupported move-effect manifest: {path}")
    return value


def write_manifest(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def safe_id(value: str, label: str) -> str:
    if not SAFE_ID.fullmatch(value):
        raise ValueError(f"{label} must contain only lowercase letters, numbers, '.', '_' or '-'")
    return value


def atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
        temporary = Path(output.name)
        with source.open("rb") as input_file:
            shutil.copyfileobj(input_file, output)
    os.replace(temporary, target)


def manifest_for(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    path = args.vendor_root.resolve() / MANIFEST
    return path, read_manifest(path) or {"schema_version": SCHEMA, "packs": {}}


def command_showdown(args: argparse.Namespace) -> int:
    if set(SHOWDOWN_FILES) & BLOCKED:
        raise RuntimeError("the Showdown allowlist contains a blocked or unclear-license file")
    asset_root = args.asset_root.resolve()
    target_root = asset_root / ASSET_DIR / "showdown-cc0"
    entries: list[dict[str, str]] = []
    for filename in SHOWDOWN_FILES:
        asset_id = Path(filename).stem
        target = target_root / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(
            SHOWDOWN_BASE + filename,
            headers={"User-Agent": "KoalaBattle optional-asset-installer/1.0"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read(2 * 1024 * 1024 + 1)
        if len(payload) > 2 * 1024 * 1024 or not payload.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError(f"invalid or oversized PNG from {SHOWDOWN_BASE + filename}")
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
            output.write(payload)
            temporary = Path(output.name)
        os.replace(temporary, target)
        entries.append({"id": asset_id, "path": target.relative_to(asset_root).as_posix(), "source": SHOWDOWN_BASE + filename, "sha256": checksum(target)})
    manifest_path, manifest = manifest_for(args)
    manifest["packs"]["showdown-cc0"] = {
        "source_url": SHOWDOWN_REPOSITORY, "source_commit": SHOWDOWN_COMMIT,
        "license": "CC0-1.0", "license_url": SHOWDOWN_LICENSE, "files": entries,
    }
    write_manifest(manifest_path, manifest)
    print(f"Installed {len(entries)} allowlisted CC0 textures into {target_root}")
    return 0


def command_local(args: argparse.Namespace) -> int:
    source_root = args.source.resolve()
    mapping = json.loads(args.mapping.resolve().read_text(encoding="utf-8"))
    if not source_root.is_dir() or not isinstance(mapping, dict) or not mapping:
        raise ValueError("source must be a directory and mapping a non-empty JSON object")
    pack = safe_id(args.pack, "pack id")
    entries: list[dict[str, str]] = []
    asset_root = args.asset_root.resolve()
    for raw_id, relative in mapping.items():
        asset_id = safe_id(raw_id, "effect id")
        if not isinstance(relative, str):
            raise ValueError(f"mapping value for {asset_id} must be a path")
        source = (source_root / relative).resolve()
        if not source.is_relative_to(source_root) or not source.is_file() or source.suffix.lower() not in EXTENSIONS:
            raise ValueError(f"unsafe, missing, or unsupported source: {relative}")
        target = asset_root / ASSET_DIR / pack / f"{asset_id}{source.suffix.lower()}"
        atomic_copy(source, target)
        entries.append({"id": asset_id, "path": target.relative_to(asset_root).as_posix(), "source": relative, "sha256": checksum(target)})
    manifest_path, manifest = manifest_for(args)
    manifest["packs"][pack] = {"source_url": args.source_url, "license": args.license, "license_url": args.license_url, "files": entries}
    write_manifest(manifest_path, manifest)
    print(f"Installed {len(entries)} local textures into {asset_root / ASSET_DIR / pack}")
    return 0


def verify(args: argparse.Namespace) -> tuple[bool, list[str]]:
    path, manifest = manifest_for(args)
    if not path.is_file():
        return False, [f"manifest missing: {path}"]
    root = args.asset_root.resolve()
    problems: list[str] = []
    for pack in manifest["packs"].values():
        for entry in pack.get("files", []):
            relative = entry.get("path", "")
            target = (root / relative).resolve()
            if not target.is_relative_to(root / ASSET_DIR):
                problems.append(f"unsafe path: {relative}")
            elif not target.is_file():
                problems.append(f"missing: {relative}")
            elif checksum(target) != entry.get("sha256"):
                problems.append(f"checksum mismatch: {relative}")
    return not problems, problems


# These packs are optional and supplied by the operator, because their sources carry
# licences this repository cannot redistribute. "Nothing installed" is therefore a
# normal resting state, not a fault, and saying "not installed or incomplete" for it
# put a defect-shaped line in every `make check` run for a repository that is fine.
# A manifest with missing or altered files is a real problem and still says so.
def command_status(args: argparse.Namespace) -> int:
    path, manifest = manifest_for(args)
    valid, problems = verify(args)
    count = sum(len(pack.get("files", [])) for pack in manifest["packs"].values())
    print(f"Move-effect root: {args.asset_root.resolve() / ASSET_DIR}")
    print(f"Manifest: {'present' if path.is_file() else 'missing'} ({count} managed files)")
    print(f"Managed installation: {('valid' if valid else 'incomplete — see below' if path.is_file() else 'not installed (optional)')}")
    for problem in problems[:10]:
        print(f"- {problem}")
    return 0


def command_verify(args: argparse.Namespace) -> int:
    valid, problems = verify(args)
    if valid:
        print("Move-effect installation verified")
        return 0
    print("\n".join(problems), file=sys.stderr)
    return 1


def command_remove(args: argparse.Namespace) -> int:
    path, manifest = manifest_for(args)
    selected = set(manifest["packs"]) if args.pack is None else {safe_id(args.pack, "pack id")}
    root = args.asset_root.resolve()
    removed = 0
    for pack_id in selected:
        pack = manifest["packs"].pop(pack_id, None)
        for entry in pack.get("files", []) if isinstance(pack, dict) else []:
            target = (root / entry.get("path", "")).resolve()
            if target.is_relative_to(root / ASSET_DIR) and target.is_file():
                target.unlink()
                removed += 1
    if manifest["packs"]:
        write_manifest(path, manifest)
    else:
        path.unlink(missing_ok=True)
    print(f"Removed {removed} managed textures; unrelated assets were preserved")
    return 0


def parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[1]
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--asset-root", type=Path, default=root / "data/assets")
    result.add_argument("--vendor-root", type=Path, default=root / "data/vendor")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("status").set_defaults(run=command_status)
    commands.add_parser("verify").set_defaults(run=command_verify)
    showdown = commands.add_parser("install-showdown")
    showdown.set_defaults(run=command_showdown)
    local = commands.add_parser("install-local")
    local.add_argument("--source", type=Path, required=True)
    local.add_argument("--mapping", type=Path, required=True)
    local.add_argument("--pack", required=True)
    local.add_argument("--source-url", required=True)
    local.add_argument("--license", required=True)
    local.add_argument("--license-url", required=True)
    local.set_defaults(run=command_local)
    remove = commands.add_parser("remove")
    remove.add_argument("--pack")
    remove.set_defaults(run=command_remove)
    return result


if __name__ == "__main__":
    try:
        arguments = parser().parse_args()
        raise SystemExit(arguments.run(arguments))
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2)
