#!/usr/bin/env python3
"""Refresh the committed offline Draft Rarity snapshot from Smogon's public example board."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DOCUMENT_ID = "1o1xtv7o_eBbxnW3JcMV1aik6YWtvJveAbR_666Z4CqA"
SOURCE_URL = f"https://docs.google.com/spreadsheets/d/{DOCUMENT_ID}/edit?usp=sharing"
CSV_URL = f"https://docs.google.com/spreadsheets/d/{DOCUMENT_ID}/gviz/tq?" + urlencode(
    {"sheet": "Pokédex", "tqx": "out:csv"}
)
OUTPUT = (
    Path(__file__).resolve().parents[1]
    / "backend/koalabattle/challenges/content/smogon-draft-points.json"
)


def normalized_id(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, help="Use an already-downloaded CSV")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--updated-on", required=True, help="Snapshot date in YYYY-MM-DD form")
    args = parser.parse_args()
    if args.source:
        raw = args.source.read_bytes()
    else:
        request = Request(CSV_URL, headers={"User-Agent": "KoalaBattle rarity snapshot updater"})
        with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed public source
            raw = response.read(2_000_000)

    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    if not rows:
        raise SystemExit("Smogon sheet returned no rows")
    headers = rows[0]
    try:
        name_index = headers.index("PS! Name -")
        points_index = headers.index("9N. -")
    except ValueError as error:
        raise SystemExit(f"Smogon sheet columns changed: {headers}") from error

    points: dict[str, int] = {}
    banned: set[str] = set()
    for row in rows[1:]:
        if max(name_index, points_index) >= len(row):
            continue
        species_id = normalized_id(row[name_index])
        raw_points = row[points_index].strip()
        if not species_id or not raw_points.isdigit() or "mega" in species_id:
            continue
        value = int(raw_points)
        if value == 99:
            banned.add(species_id)
        elif 1 <= value <= 20:
            points[species_id] = value

    if len(points) < 900 or not banned:
        raise SystemExit(
            f"Refusing suspicious snapshot: {len(points)} priced entries, {len(banned)} banned"
        )
    material = json.dumps(
        {"points": points, "banned": sorted(banned)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    payload = {
        "schema_version": "1.0",
        "source_name": "Smogon Draft League Example Draft Boards 2026",
        "source_url": SOURCE_URL,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "sheet": "Pokédex",
        "column": "9N. -",
        "updated_on": args.updated_on,
        "catalog_hash": hashlib.sha256(material).hexdigest(),
        "points": dict(sorted(points.items())),
        "banned": sorted(banned),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}: {len(points)} priced, {len(banned)} banned")


if __name__ == "__main__":
    main()
