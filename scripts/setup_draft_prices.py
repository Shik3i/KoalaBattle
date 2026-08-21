#!/usr/bin/env python3
"""Import and verify an operator-provided draft pricing board.

Examples:
    python scripts/setup_draft_prices.py status
    python scripts/setup_draft_prices.py import ./my-board.xlsx --board-name "My SV NatDex copy"
    python scripts/setup_draft_prices.py import --url "https://docs.google.com/spreadsheets/d/.../edit" --board-name "My copy"
    python scripts/setup_draft_prices.py verify
    python scripts/setup_draft_prices.py clear
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from koalabattle.challenges.pricing import DraftPriceStore, parse_catalog  # noqa: E402

DEFAULT_ROOT = PROJECT_ROOT / "data/draft-prices"
MAX_DOWNLOAD_BYTES = 20_000_000


def _google_export_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != "docs.google.com":
        raise ValueError(
            "--url must be an explicit https://docs.google.com/spreadsheets URL"
        )
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 3 or parts[0] != "spreadsheets" or parts[1] != "d":
        raise ValueError("--url is not a Google Sheets document URL")
    document_id = parts[2]
    if not document_id.replace("-", "").replace("_", "").isalnum():
        raise ValueError("Google Sheets document ID is invalid")
    return f"https://docs.google.com/spreadsheets/d/{document_id}/export?format=xlsx"


def _download(value: str) -> bytes:
    request = Request(
        _google_export_url(value), headers={"User-Agent": "KoalaBattle draft importer"}
    )
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310
            data = response.read(MAX_DOWNLOAD_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise RuntimeError(
            f"could not download the explicitly supplied Google Sheet: {error}"
        ) from error
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise ValueError("downloaded workbook exceeds 20 MB")
    return data


def _status(store: DraftPriceStore) -> int:
    try:
        catalog = store.load()
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    if catalog is None:
        print(f"No draft pricing catalog installed at {store.path}")
        return 0
    states = {
        state: sum(item.state == state for item in catalog.entries)
        for state in ("priced", "banned", "missing")
    }
    print(f"Board: {catalog.board_name}")
    print(f"Context: {catalog.context}")
    print(f"Catalog: {catalog.catalog_hash}")
    print(f"Source SHA-256: {catalog.source_sha256}")
    print(
        f"Entries: {catalog.parsed_entries} ({states['priced']} priced, {states['banned']} banned, {states['missing']} missing)"
    )
    print(f"Imported: {catalog.imported_at.isoformat()}")
    print(f"Path: {store.path}")
    return 0


def _verify(store: DraftPriceStore) -> int:
    try:
        catalog = store.load()
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    if catalog is None:
        print("No normalized catalog is installed.", file=sys.stderr)
        return 1
    verified, detail = store.verify_source(catalog)
    if not verified:
        print(detail, file=sys.stderr)
        return 1
    print(
        f"Verified catalog schema {catalog.schema_version}, parser {catalog.parser_version}, "
        f"and source SHA-256. {detail}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("verify")
    commands.add_parser("clear")
    importing = commands.add_parser("import")
    importing.add_argument("source", type=Path, nargs="?")
    importing.add_argument("--url")
    importing.add_argument("--board-name", required=True)
    importing.add_argument("--context", default="sv-natdex")
    importing.add_argument("--price-column")
    importing.add_argument("--sheet", default="Pokedex")
    importing.add_argument("--mechanics-assumption", action="append", default=[])
    args = parser.parse_args()
    store = DraftPriceStore(args.root)
    if args.command == "status":
        return _status(store)
    if args.command == "verify":
        return _verify(store)
    if args.command == "clear":
        removed = store.clear()
        for path in store.root.glob("source.*"):
            if path.is_file():
                path.unlink()
                removed = True
        print(
            "Cleared local draft pricing data."
            if removed
            else "No local draft pricing data was installed."
        )
        return 0
    if bool(args.source) == bool(args.url):
        parser.error("import requires exactly one local source path or --url")
    if args.url:
        data = _download(args.url)
        filename = "source.xlsx"
    else:
        source = args.source.resolve()
        if not source.is_file():
            parser.error(f"source file does not exist: {source}")
        if source.stat().st_size > MAX_DOWNLOAD_BYTES:
            parser.error("local workbook exceeds 20 MB")
        data = source.read_bytes()
        filename = f"source{source.suffix.lower()}"
    try:
        catalog = parse_catalog(
            data,
            filename,
            board_name=args.board_name,
            context=args.context,
            price_column=args.price_column,
            sheet_name=args.sheet,
            mechanics_assumptions=tuple(args.mechanics_assumption),
        )
    except ValueError as error:
        print(f"Import failed: {error}", file=sys.stderr)
        return 1
    store.root.mkdir(parents=True, exist_ok=True)
    for old in store.root.glob("source.*"):
        if old.is_file():
            old.unlink()
    (store.root / filename).write_bytes(data)
    store.save(catalog)
    print(
        f"Imported {catalog.parsed_entries} rows; normalized catalog {catalog.catalog_hash}"
    )
    return _verify(store)


if __name__ == "__main__":
    raise SystemExit(main())
