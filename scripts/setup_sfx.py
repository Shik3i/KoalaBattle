#!/usr/bin/env python3
"""Install operator-curated third-party SFX into the ignored local asset tree.

The tool deliberately does not download packs. Operators must download a pack from its
official source, review its licence, and provide an explicit mapping of source files to
KoalaBattle event ids. This keeps click-through licences, large archives, and raw files out of
the repository and release artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

SUPPORTED_EXTENSIONS = (".wav", ".ogg", ".mp3")
MANIFEST_NAME = "sfx-manifest.json"
MANIFEST_SCHEMA_VERSION = 1
ASSET_DIRECTORY = Path("audio")
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"invalid SFX manifest {path}: {error}") from error
    if not isinstance(value, dict) or value.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise RuntimeError(f"unsupported SFX manifest {path}")
    packs = value.get("packs")
    if not isinstance(packs, dict):
        raise RuntimeError(f"SFX manifest has no pack map: {path}")
    return value


def validate_id(value: str, *, label: str) -> str:
    if not SAFE_ID.fullmatch(value):
        raise ValueError(f"{label} must contain only lowercase letters, numbers, '.', '_' or '-'")
    return value


def safe_source_path(source_root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"mapping source path escapes the source directory: {relative}")
    resolved = (source_root / candidate).resolve()
    if not resolved.is_relative_to(source_root.resolve()):
        raise ValueError(f"mapping source path escapes the source directory: {relative}")
    if resolved.suffix.casefold() not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"unsupported SFX extension: {relative}")
    if not resolved.is_file():
        raise ValueError(f"mapped SFX file does not exist: {relative}")
    return resolved


def load_mapping(path: Path) -> dict[str, tuple[str, ...]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"invalid SFX mapping {path}: {error}") from error
    if not isinstance(value, dict) or not value:
        raise ValueError("SFX mapping must be a non-empty JSON object")
    result: dict[str, tuple[str, ...]] = {}
    for raw_id, raw_sources in value.items():
        if not isinstance(raw_id, str):
            raise ValueError("SFX mapping ids must be strings")
        asset_id = validate_id(raw_id, label="SFX id")
        sources = (raw_sources,) if isinstance(raw_sources, str) else raw_sources
        if not isinstance(sources, list) or not sources or not all(
            isinstance(source, str) and source for source in sources
        ):
            raise ValueError(f"SFX mapping entry {asset_id} must be a path or non-empty path list")
        result[asset_id] = tuple(sources)
    return result


def copy_atomic(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
        with source.open("rb") as input_file:
            shutil.copyfileobj(input_file, temporary)
    os.replace(temporary_path, target)


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def command_install(args: argparse.Namespace) -> int:
    source_root = args.source.resolve()
    if not source_root.is_dir():
        raise ValueError(f"SFX source directory does not exist: {source_root}")
    pack_id = validate_id(args.pack, label="pack id")
    mapping = load_mapping(args.mapping.resolve())
    asset_root = args.asset_root.resolve()
    vendor_root = args.vendor_root.resolve()
    manifest_path = vendor_root / MANIFEST_NAME
    previous = load_manifest(manifest_path) or {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "packs": {},
    }
    packs = dict(previous["packs"])
    entries: list[dict[str, str]] = []
    for asset_id, sources in mapping.items():
        for index, relative_source in enumerate(sources, start=1):
            source = safe_source_path(source_root, relative_source)
            extension = source.suffix.casefold()
            target_name = f"{asset_id}-{index:02d}{extension}"
            relative_target = ASSET_DIRECTORY / target_name
            target = asset_root / relative_target
            copy_atomic(source, target)
            entries.append(
                {
                    "id": asset_id,
                    "variant": str(index),
                    "source": Path(relative_source).as_posix(),
                    "path": relative_target.as_posix(),
                    "sha256": sha256(target),
                }
            )
    packs[pack_id] = {
        "source_url": args.source_url,
        "license_url": args.license_url,
        "license": args.license,
        "source_directory": source_root.name,
        "files": sorted(entries, key=lambda entry: entry["path"]),
    }
    write_manifest(
        manifest_path,
        {"schema_version": MANIFEST_SCHEMA_VERSION, "packs": packs},
    )
    print(f"Installed {len(entries)} SFX files from pack {pack_id} into {asset_root / ASSET_DIRECTORY}")
    print(f"Manifest: {manifest_path}")
    return 0


def _manifest_entries(manifest: dict[str, Any]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for pack in manifest.get("packs", {}).values():
        if not isinstance(pack, dict):
            continue
        files = pack.get("files", [])
        if isinstance(files, list):
            entries.extend(entry for entry in files if isinstance(entry, dict))
    return entries


def verification(args: argparse.Namespace) -> tuple[bool, list[str]]:
    manifest = load_manifest(args.vendor_root.resolve() / MANIFEST_NAME)
    if not manifest:
        return False, [f"not installed: manifest missing at {args.vendor_root.resolve() / MANIFEST_NAME}"]
    asset_root = args.asset_root.resolve()
    problems: list[str] = []
    for entry in _manifest_entries(manifest):
        relative = entry.get("path")
        expected = entry.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            problems.append("manifest contains a malformed SFX entry")
            continue
        target = (asset_root / relative).resolve()
        if not target.is_relative_to(asset_root) or not target.is_relative_to((asset_root / ASSET_DIRECTORY).resolve()):
            problems.append(f"unsafe manifest path: {relative}")
        elif not target.is_file():
            problems.append(f"missing: {relative}")
        elif sha256(target) != expected:
            problems.append(f"checksum mismatch: {relative}")
    return not problems, problems


def command_status(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.vendor_root.resolve() / MANIFEST_NAME)
    packs = manifest.get("packs", {}) if manifest else {}
    entries = _manifest_entries(manifest) if manifest else []
    valid, problems = verification(args)
    print(f"SFX asset root: {args.asset_root.resolve() / ASSET_DIRECTORY}")
    print(f"Manifest: {'present' if manifest else 'missing'} ({len(entries)} managed files)")
    print(f"Packs: {len(packs)}")
    print(f"Managed installation: {'valid' if valid else 'not installed or incomplete'}")
    for problem in problems[:10]:
        print(f"- {problem}")
    return 0


def command_verify(args: argparse.Namespace) -> int:
    valid, problems = verification(args)
    if valid:
        manifest = load_manifest(args.vendor_root.resolve() / MANIFEST_NAME)
        print(f"Verified {len(_manifest_entries(manifest)) if manifest else 0} managed SFX files")
        return 0
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1


def command_remove(args: argparse.Namespace) -> int:
    manifest_path = args.vendor_root.resolve() / MANIFEST_NAME
    manifest = load_manifest(manifest_path)
    if not manifest:
        print("No managed SFX installation found")
        return 0
    packs = dict(manifest["packs"])
    selected = set(packs) if args.pack is None else {validate_id(args.pack, label="pack id")}
    remaining_paths = {
        entry.get("path")
        for pack_id, pack in packs.items()
        if pack_id not in selected and isinstance(pack, dict)
        for entry in pack.get("files", [])
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }
    removed = 0
    asset_root = args.asset_root.resolve()
    for pack_id in selected:
        pack = packs.pop(pack_id, None)
        if not isinstance(pack, dict):
            continue
        for entry in pack.get("files", []):
            relative = entry.get("path") if isinstance(entry, dict) else None
            if not isinstance(relative, str):
                continue
            target = (asset_root / relative).resolve()
            if (
                relative not in remaining_paths
                and target.is_relative_to(asset_root / ASSET_DIRECTORY)
                and target.is_file()
            ):
                target.unlink()
                removed += 1
    if packs:
        write_manifest(manifest_path, {"schema_version": MANIFEST_SCHEMA_VERSION, "packs": packs})
    else:
        manifest_path.unlink(missing_ok=True)
    print(f"Removed {removed} managed SFX files; unrelated local audio was preserved")
    return 0


def parser() -> argparse.ArgumentParser:
    project_root = Path(__file__).resolve().parents[1]
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--asset-root", type=Path, default=project_root / "data/assets")
    result.add_argument("--vendor-root", type=Path, default=project_root / "data/vendor")
    subparsers = result.add_subparsers(dest="command", required=True)
    install = subparsers.add_parser("install", help="install explicitly mapped local SFX files")
    install.add_argument("--source", type=Path, required=True)
    install.add_argument("--mapping", type=Path, required=True)
    install.add_argument("--pack", required=True)
    install.add_argument("--source-url", required=True)
    install.add_argument("--license-url", required=True)
    install.add_argument("--license", default="operator-verified")
    subparsers.add_parser("status", help="report local installation state")
    subparsers.add_parser("verify", help="validate managed files and checksums")
    remove = subparsers.add_parser("remove", help="remove only files managed by this tool")
    remove.add_argument("--pack", help="remove only one managed pack")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        return {
            "install": command_install,
            "status": command_status,
            "verify": command_verify,
            "remove": command_remove,
        }[args.command](args)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"SFX setup failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
