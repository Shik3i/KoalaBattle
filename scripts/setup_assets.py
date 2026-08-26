#!/usr/bin/env python3
"""Opt-in installer for third-party Pokemon Showdown battle sprites."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen

SOURCE_BASE = "https://play.pokemonshowdown.com/sprites/"
SOURCE_REPOSITORY = "https://github.com/smogon/sprites"
MANIFEST_NAME = "pokemon-showdown-assets.json"
USER_AGENT = "KoalaBattle asset setup/0.11.0 (+https://github.com/Shik3i/KoalaBattle)"

KANTO_RB_TRAINERS = (
    "brock-gen1rb.png",
    "misty-gen1rb.png",
    "ltsurge-gen1rb.png",
    "erika-gen1rb.png",
    "koga-gen1rb.png",
    "sabrina-gen1rb.png",
    "blaine-gen1rb.png",
    "giovanni-gen1rb.png",
    "lorelei-gen1rb.png",
    "bruno-gen1rb.png",
    "agatha-gen1rb.png",
    "lance-gen1rb.png",
    "blue-gen1rbchampion.png",
)


@dataclass(frozen=True)
class Category:
    source: str
    target: Path
    extension: str
    required_files: tuple[str, ...] = ()


CATEGORIES = {
    "front": Category("gen5/", Path("pokemon/front"), ".png"),
    "back": Category("gen5-back/", Path("pokemon/back"), ".png"),
    "animated-front": Category("ani/", Path("pokemon/animated/front"), ".gif"),
    "animated-back": Category("ani-back/", Path("pokemon/animated/back"), ".gif"),
    "trainers": Category(
        "trainers/", Path("trainers"), ".png", required_files=KANTO_RB_TRAINERS
    ),
}


class IndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.hrefs.append(href)


def normalized_filename(source_name: str, extension: str) -> str:
    stem = Path(source_name).stem.casefold()
    normalized = "".join(
        character for character in stem if character.isascii() and character.isalnum()
    )
    if not normalized:
        raise ValueError(f"unsupported source filename: {source_name!r}")
    return f"{normalized}{extension}"


def parse_index(html: str, extension: str) -> list[str]:
    parser = IndexParser()
    parser.feed(html)
    names: set[str] = set()
    for href in parser.hrefs:
        parsed = urlparse(href)
        relative_path = parsed.path.removeprefix("./")
        name = Path(relative_path).name
        if (
            parsed.scheme
            or parsed.netloc
            or relative_path != name
            or not name.casefold().endswith(extension)
        ):
            continue
        names.add(name)
    return sorted(names)


def request_bytes(url: str, *, timeout: float = 30) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            return response.read()
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"download failed for {url}: {exc}") from exc


def fetch_index(category: Category, source_base: str) -> list[str]:
    url = urljoin(source_base, category.source)
    html = request_bytes(url).decode("utf-8", errors="replace")
    names = parse_index(html, category.extension)
    required_missing = set(category.required_files) - set(names)
    if (
        len(names) < 100
        or required_missing
        or (not category.required_files and not any(name.startswith("pikachu.") for name in names))
    ):
        raise RuntimeError(
            f"unexpected Pokemon Showdown directory structure at {url}: "
            f"found {len(names)} {category.extension} files"
        )
    return list(category.required_files) if category.required_files else names


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"invalid asset manifest {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise RuntimeError(f"unsupported asset manifest {path}")
    return value


def selected_categories(profile: str) -> dict[str, Category]:
    if profile == "static":
        return {
            name: category
            for name, category in CATEGORIES.items()
            if not name.startswith("animated")
        }
    return CATEGORIES


def build_plan(
    listings: dict[str, Iterable[str]], categories: dict[str, Category]
) -> list[tuple[str, str, Path]]:
    plan: list[tuple[str, str, Path]] = []
    seen: dict[Path, tuple[int, str]] = {}
    for category_name, category in categories.items():
        for source_name in listings[category_name]:
            target = category.target / normalized_filename(
                source_name, category.extension
            )
            previous = seen.get(target)
            if previous:
                previous_index, previous_source = previous
                canonical_stem = target.stem
                previous_is_canonical = (
                    Path(previous_source).stem.casefold() == canonical_stem
                )
                current_is_canonical = (
                    Path(source_name).stem.casefold() == canonical_stem
                )
                if current_is_canonical and not previous_is_canonical:
                    plan[previous_index] = (category_name, source_name, target)
                    seen[target] = (previous_index, source_name)
                continue
            seen[target] = (len(plan), source_name)
            plan.append((category_name, source_name, target))
    return plan


def install_file(
    item: tuple[str, str, Path], *, source_base: str, asset_root: Path
) -> dict[str, str]:
    category_name, source_name, relative_target = item
    category = CATEGORIES[category_name]
    target = asset_root / relative_target
    target.parent.mkdir(parents=True, exist_ok=True)
    url = urljoin(source_base, f"{category.source}{quote(source_name)}")
    payload = request_bytes(url)
    if not payload:
        raise RuntimeError(f"empty asset response from {url}")
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
        temporary.write(payload)
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, target)
    return {
        "category": category_name,
        "source": source_name,
        "path": relative_target.as_posix(),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def command_install(args: argparse.Namespace) -> int:
    categories = selected_categories(args.profile)
    listings = {
        name: fetch_index(category, args.source_base)
        for name, category in categories.items()
    }
    plan = build_plan(listings, categories)
    manifest_path = args.vendor_root / MANIFEST_NAME
    previous = load_manifest(manifest_path)
    previous_files = {
        entry["path"]: entry
        for entry in (previous or {}).get("files", [])
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }

    retained: list[dict[str, str]] = []
    pending: list[tuple[str, str, Path]] = []
    for item in plan:
        relative = item[2].as_posix()
        existing = previous_files.get(relative)
        target = args.asset_root / item[2]
        if (
            not args.refresh
            and existing
            and target.is_file()
            and existing.get("sha256") == sha256(target)
        ):
            retained.append(existing)
        else:
            pending.append(item)

    print(
        f"Source verified: {args.source_base} ({len(plan)} files; "
        f"{len(retained)} already valid; {len(pending)} to download)"
    )
    downloaded: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = [
            executor.submit(
                install_file,
                item,
                source_base=args.source_base,
                asset_root=args.asset_root,
            )
            for item in pending
        ]
        for number, future in enumerate(as_completed(futures), start=1):
            downloaded.append(future.result())
            if number % 250 == 0 or number == len(pending):
                print(f"Downloaded {number}/{len(pending)}")

    args.vendor_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "source": args.source_base,
        "source_repository": SOURCE_REPOSITORY,
        "profile": args.profile,
        "files": sorted(retained + downloaded, key=lambda entry: entry["path"]),
    }
    temporary_manifest = manifest_path.with_suffix(".tmp")
    temporary_manifest.write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary_manifest, manifest_path)
    print(f"Installed {len(manifest['files'])} assets in {args.asset_root}")
    return 0


def verification(
    args: argparse.Namespace, *, quiet: bool = False
) -> tuple[bool, list[str]]:
    manifest_path = args.vendor_root / MANIFEST_NAME
    manifest = load_manifest(manifest_path)
    if not manifest:
        return False, [f"not installed: manifest missing at {manifest_path}"]
    problems: list[str] = []
    files = manifest.get("files", [])
    if not isinstance(files, list) or not files:
        problems.append("manifest contains no files")
        return False, problems
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            problems.append("manifest contains a malformed file entry")
            continue
        target = (args.asset_root / entry["path"]).resolve()
        if not target.is_relative_to(args.asset_root.resolve()):
            problems.append(f"unsafe manifest path: {entry['path']}")
        elif not target.is_file():
            problems.append(f"missing: {entry['path']}")
        elif not quiet and entry.get("sha256") != sha256(target):
            problems.append(f"checksum mismatch: {entry['path']}")
    return not problems, problems


# These packs are optional and supplied by the operator, because their sources carry
# licences this repository cannot redistribute. "Nothing installed" is therefore a
# normal resting state, not a fault, and saying "not installed or incomplete" for it
# put a defect-shaped line in every `make check` run for a repository that is fine.
# A manifest with missing or altered files is a real problem and still says so.
def command_status(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.vendor_root / MANIFEST_NAME)
    installed = len(manifest.get("files", [])) if manifest else 0
    counts = {
        name: len(
            list((args.asset_root / category.target).glob(f"*{category.extension}"))
        )
        for name, category in CATEGORIES.items()
    }
    print(f"Asset root: {args.asset_root}")
    print(
        f"Manifest: {'present' if manifest else 'missing'} ({installed} managed files)"
    )
    for name, count in counts.items():
        print(f"{name}: {count}")
    valid, problems = verification(args, quiet=True)
    print(
        f"Managed installation: {('valid' if valid else 'incomplete — see below' if manifest else 'not installed (optional)')}"
    )
    for problem in problems[:10]:
        print(f"- {problem}")
    return 0


def command_verify(args: argparse.Namespace) -> int:
    valid, problems = verification(args)
    if valid:
        manifest = load_manifest(args.vendor_root / MANIFEST_NAME)
        print(
            f"Verified {len(manifest.get('files', [])) if manifest else 0} managed assets"
        )
        return 0
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1


def command_remove(args: argparse.Namespace) -> int:
    manifest_path = args.vendor_root / MANIFEST_NAME
    manifest = load_manifest(manifest_path)
    if not manifest:
        print("No managed Pokemon Showdown asset installation found")
        return 0
    removed = 0
    for entry in manifest.get("files", []):
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            continue
        target = (args.asset_root / entry["path"]).resolve()
        if target.is_relative_to(args.asset_root.resolve()) and target.is_file():
            target.unlink()
            removed += 1
    manifest_path.unlink(missing_ok=True)
    for category in CATEGORIES.values():
        directory = args.asset_root / category.target
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
    if args.vendor_root.is_dir() and not any(args.vendor_root.iterdir()):
        args.vendor_root.rmdir()
    print(f"Removed {removed} managed assets; unrelated local assets were preserved")
    return 0


def parser() -> argparse.ArgumentParser:
    project_root = Path(__file__).resolve().parents[1]
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--asset-root", type=Path, default=project_root / "data/assets")
    result.add_argument(
        "--vendor-root", type=Path, default=project_root / "data/vendor"
    )
    subparsers = result.add_subparsers(dest="command", required=True)
    install_parser = subparsers.add_parser("install", help="download optional sprites")
    install_parser.add_argument(
        "--profile", choices=("static", "full"), default="static"
    )
    install_parser.add_argument("--refresh", action="store_true")
    install_parser.add_argument("--jobs", type=int, choices=range(1, 17), default=6)
    install_parser.add_argument(
        "--source-base", default=SOURCE_BASE, help=argparse.SUPPRESS
    )
    subparsers.add_parser("verify", help="validate files and checksums")
    subparsers.add_parser("status", help="report local installation state")
    subparsers.add_parser("remove", help="remove only files managed by this tool")
    return result


def main() -> int:
    args = parser().parse_args()
    args.asset_root = args.asset_root.resolve()
    args.vendor_root = args.vendor_root.resolve()
    try:
        return {
            "install": command_install,
            "verify": command_verify,
            "status": command_status,
            "remove": command_remove,
        }[args.command](args)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"asset setup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
