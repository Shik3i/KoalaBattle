from __future__ import annotations

import json
import subprocess
import zipfile
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest

from koalabattle.challenges.pricing import DraftPriceStore, parse_catalog

FIXTURE = Path(__file__).parents[1] / "fixtures/draft-prices/sv-natdex-synthetic.csv"


def test_csv_import_preserves_exact_points_and_explicit_missing_states(tmp_path: Path) -> None:
    data = FIXTURE.read_bytes()
    catalog = parse_catalog(
        data,
        FIXTURE.name,
        board_name="Synthetic SV NatDex",
        context="sv-natdex",
        price_column="SV NatDex",
    )
    assert [entry.points for entry in catalog.entries] == [12, 7, None, None]
    assert [entry.state for entry in catalog.entries] == ["priced", "priced", "banned", "missing"]
    assert catalog.source_sha256
    store = DraftPriceStore(tmp_path / "draft-prices")
    store.save(catalog)
    assert store.load() == catalog


def test_catalog_hash_ignores_import_clock_but_changes_with_exact_price() -> None:
    source = b"Pokemon,SV NatDex\nExamplemon,9\n"
    first = parse_catalog(
        source,
        "fixture.csv",
        board_name="Fixture",
        context="sv-natdex",
        price_column="SV NatDex",
        imported_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    later = parse_catalog(
        source,
        "fixture.csv",
        board_name="Fixture",
        context="sv-natdex",
        price_column="SV NatDex",
        imported_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=1),
    )
    changed = parse_catalog(
        b"Pokemon,SV NatDex\nExamplemon,10\n",
        "fixture.csv",
        board_name="Fixture",
        context="sv-natdex",
        price_column="SV NatDex",
    )
    assert first.catalog_hash == later.catalog_hash
    assert first.catalog_hash != changed.catalog_hash


def test_store_rejects_normalized_catalog_tampering_and_verifies_exact_source(
    tmp_path: Path,
) -> None:
    source = b"Pokemon,SV NatDex\nExamplemon,9\n"
    catalog = parse_catalog(
        source,
        "fixture.csv",
        board_name="Fixture",
        context="sv-natdex",
        price_column="SV NatDex",
    )
    store = DraftPriceStore(tmp_path / "draft-prices")
    store.save(catalog)
    assert store.verify_source(catalog)[0] is False
    (store.root / "source.csv").write_bytes(source)
    assert store.verify_source(catalog)[0] is True

    payload = json.loads(store.path.read_text(encoding="utf-8"))
    payload["entries"][0]["points"] = 10
    store.path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="catalog hash mismatch"):
        store.load()


def test_xlsx_with_invalid_shared_string_reference_fails_closed() -> None:
    malformed = _xlsx([["Pokemon", "SV NatDex"], ["Examplemon", "9"]]).replace(
        b'<c r="A1" t="s"><v>0</v></c>',
        b'<c r="A1" t="s"><v>999</v></c>',
    )
    with pytest.raises(ValueError, match="not a readable XLSX"):
        parse_catalog(
            malformed,
            "fixture.xlsx",
            board_name="Fixture",
            context="sv-natdex",
            price_column="SV NatDex",
        )


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (b"Creature,Points\nExamplemon,9\n", "no Pokemon/Species/Name header"),
        (b"Pokemon,Wrong\nExamplemon,9\n", "was not found exactly once"),
        (b"Pokemon,SV NatDex\nExamplemon,9\nExample-mon,8\n", "duplicate species/form"),
        (b"Pokemon,SV NatDex\nExamplemon,OU\n", "unsupported price"),
    ],
)
def test_bad_columns_duplicates_and_tier_text_are_rejected(source: bytes, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_catalog(
            source,
            "fixture.csv",
            board_name="Fixture",
            context="sv-natdex",
            price_column="SV NatDex",
        )


def _xlsx(rows: list[list[str]]) -> bytes:
    shared = [value for row in rows for value in row]
    indexes = iter(range(len(shared)))
    sheet_rows = []
    for row_number, row in enumerate(rows, start=1):
        cells = []
        for column, _ in enumerate(row):
            reference = f"{chr(65 + column)}{row_number}"
            cells.append(f'<c r="{reference}" t="s"><v>{next(indexes)}</v></c>')
        sheet_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Pokedex" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/sharedStrings.xml",
            '<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            + "".join(f"<si><t>{value}</t></si>" for value in shared)
            + "</sst>",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            + "".join(sheet_rows)
            + "</sheetData></worksheet>",
        )
    return buffer.getvalue()


def test_xlsx_pokedex_sheet_and_wide_context_column_are_supported() -> None:
    catalog = parse_catalog(
        _xlsx([["Pokemon", "SV", "SV NatDex"], ["Examplemon", "6", "11"]]),
        "fixture.xlsx",
        board_name="Synthetic workbook",
        context="sv-natdex",
        price_column="SV NatDex",
    )
    assert catalog.entries[0].points == 11


def test_repository_contains_no_normalized_or_raw_pricing_catalog() -> None:
    project = Path(__file__).parents[3]
    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert [
        path
        for path in tracked
        if path == "data/draft-prices/catalog.json" or path.startswith("data/draft-prices/source.")
    ] == []
