from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field, ValidationError

PRICE_SCHEMA_VERSION = "1.0"
PARSER_VERSION = "1.0"
MAX_WORKBOOK_FILES = 10_000
MAX_WORKBOOK_UNCOMPRESSED_BYTES = 100_000_000
_NAME_HEADERS = {"pokemon", "pokémon", "species", "name", "pokemon name", "pokémon name"}
_BANNED = {"ban", "banned", "unavailable", "not available", "n/a", "na", "-"}


class DraftPriceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_id: str = Field(min_length=1, max_length=120)
    species: str = Field(min_length=1, max_length=120)
    points: int | None = Field(default=None, ge=1, le=100)
    state: Literal["priced", "banned", "missing"]
    reason: str | None = Field(default=None, max_length=300)


class DraftPriceCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    parser_version: str = PARSER_VERSION
    board_name: str = Field(min_length=1, max_length=200)
    context: str = Field(min_length=1, max_length=80)
    imported_at: datetime
    source_sha256: str = Field(min_length=64, max_length=64)
    catalog_hash: str = Field(min_length=64, max_length=64)
    parsed_entries: int = Field(ge=0)
    mechanics_assumptions: tuple[str, ...] = ()
    entries: tuple[DraftPriceEntry, ...]


def showdown_id(value: str) -> str:
    return "".join(
        character for character in value.lower() if character.isascii() and character.isalnum()
    )


def _header(value: str) -> str:
    return " ".join(value.strip().lower().replace("_", " ").split())


def _rows_from_csv(data: bytes) -> list[list[str]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("CSV source must be UTF-8 encoded") from error
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel_tab if text.count("\t") > text.count(",") else csv.excel
    return [[cell.strip() for cell in row] for row in csv.reader(io.StringIO(text), dialect)]


def _xlsx_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    return ["".join(node.text or "" for node in item.findall(".//x:t", namespace)) for item in root]


def _xlsx_sheet_path(archive: zipfile.ZipFile, sheet_name: str) -> str:
    namespace = {
        "x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "p": "http://schemas.openxmlformats.org/package/2006/relationships",
    }
    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    relationships = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {
        item.attrib["Id"]: item.attrib["Target"]
        for item in relationships.findall("p:Relationship", namespace)
    }
    sheets = workbook.findall("x:sheets/x:sheet", namespace)
    selected = next(
        (
            item
            for item in sheets
            if item.attrib.get("name", "").strip().lower() == sheet_name.lower()
        ),
        None,
    )
    if selected is None:
        names = ", ".join(item.attrib.get("name", "") for item in sheets)
        raise ValueError(f"XLSX has no {sheet_name!r} sheet; found: {names}")
    target = targets[selected.attrib[f"{{{namespace['r']}}}id"]]
    return target if target.startswith("xl/") else f"xl/{target.lstrip('/')}"


def _column_index(reference: str) -> int:
    letters = "".join(character for character in reference if character.isalpha())
    result = 0
    for character in letters:
        result = result * 26 + ord(character.upper()) - 64
    return result - 1


def _rows_from_xlsx(data: bytes, sheet_name: str) -> list[list[str]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        members = archive.infolist()
        if len(members) > MAX_WORKBOOK_FILES:
            raise ValueError("XLSX workbook contains too many files")
        if sum(member.file_size for member in members) > MAX_WORKBOOK_UNCOMPRESSED_BYTES:
            raise ValueError("XLSX workbook expands beyond the 100 MB safety limit")
        shared = _xlsx_strings(archive)
        root = ElementTree.fromstring(archive.read(_xlsx_sheet_path(archive, sheet_name)))
    except ValueError:
        raise
    except (zipfile.BadZipFile, KeyError, IndexError, ElementTree.ParseError) as error:
        raise ValueError("source is not a readable XLSX workbook") from error
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rows: list[list[str]] = []
    for row in root.findall(".//x:sheetData/x:row", namespace):
        values: dict[int, str] = {}
        for cell in row.findall("x:c", namespace):
            index = _column_index(cell.attrib.get("r", "A1"))
            kind = cell.attrib.get("t")
            value = cell.find("x:v", namespace)
            inline = cell.find("x:is", namespace)
            text = ""
            if kind == "s" and value is not None and value.text is not None:
                try:
                    text = shared[int(value.text)]
                except (IndexError, ValueError) as error:
                    raise ValueError("source is not a readable XLSX workbook") from error
            elif kind == "inlineStr" and inline is not None:
                text = "".join(node.text or "" for node in inline.findall(".//x:t", namespace))
            elif value is not None and value.text is not None:
                text = value.text
            values[index] = text.strip()
        if values:
            width = max(values) + 1
            rows.append([values.get(index, "") for index in range(width)])
    return rows


def read_table(data: bytes, filename: str, *, sheet_name: str = "Pokedex") -> list[list[str]]:
    suffix = Path(filename).suffix.lower()
    if suffix in {".csv", ".tsv"}:
        return _rows_from_csv(data)
    if suffix == ".xlsx":
        return _rows_from_xlsx(data, sheet_name)
    raise ValueError("pricing source must be .csv, .tsv, or .xlsx")


def parse_catalog(
    data: bytes,
    filename: str,
    *,
    board_name: str,
    context: str,
    price_column: str | None = None,
    sheet_name: str = "Pokedex",
    mechanics_assumptions: tuple[str, ...] = (),
    imported_at: datetime | None = None,
) -> DraftPriceCatalog:
    rows = read_table(data, filename, sheet_name=sheet_name)
    header_index = next(
        (
            index
            for index, row in enumerate(rows[:50])
            if any(_header(cell) in _NAME_HEADERS for cell in row)
        ),
        None,
    )
    if header_index is None:
        raise ValueError("pricing source has no Pokemon/Species/Name header in its first 50 rows")
    headers = [_header(cell) for cell in rows[header_index]]
    name_index = next(index for index, value in enumerate(headers) if value in _NAME_HEADERS)
    requested = _header(price_column or context)
    price_indexes = [index for index, value in enumerate(headers) if value == requested]
    if not price_indexes and price_column is None:
        aliases = {_header(context), _header(context.replace("-", " "))}
        price_indexes = [index for index, value in enumerate(headers) if value in aliases]
    if len(price_indexes) != 1:
        available = ", ".join(value for value in headers if value)
        raise ValueError(
            f"pricing column {price_column or context!r} was not found exactly once; "
            f"headers: {available}"
        )
    price_index = price_indexes[0]
    entries: list[DraftPriceEntry] = []
    seen: set[str] = set()
    for row_number, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        species = row[name_index].strip() if name_index < len(row) else ""
        if not species:
            continue
        entry_id = showdown_id(species)
        if not entry_id:
            raise ValueError(f"row {row_number} has an invalid species name")
        if entry_id in seen:
            raise ValueError(f"duplicate species/form row {species!r} at row {row_number}")
        seen.add(entry_id)
        raw = row[price_index].strip() if price_index < len(row) else ""
        normalized = raw.lower()
        if not raw:
            entry = DraftPriceEntry(
                entry_id=entry_id, species=species, state="missing", reason="empty price cell"
            )
        elif normalized in _BANNED:
            entry = DraftPriceEntry(entry_id=entry_id, species=species, state="banned", reason=raw)
        elif re.fullmatch(r"[1-9][0-9]*", raw):
            entry = DraftPriceEntry(
                entry_id=entry_id, species=species, points=int(raw), state="priced"
            )
        elif re.fullmatch(r"[1-9][0-9]*\.0+", raw):
            entry = DraftPriceEntry(
                entry_id=entry_id, species=species, points=int(float(raw)), state="priced"
            )
        else:
            raise ValueError(f"row {row_number} has unsupported price {raw!r} for {species}")
        entries.append(entry)
    if not entries:
        raise ValueError("pricing source contains no species rows")
    source_hash = hashlib.sha256(data).hexdigest()
    catalog_hash = _catalog_hash(
        schema_version=PRICE_SCHEMA_VERSION,
        parser_version=PARSER_VERSION,
        board_name=board_name,
        context=context,
        source_sha256=source_hash,
        mechanics_assumptions=mechanics_assumptions,
        entries=tuple(entries),
    )
    return DraftPriceCatalog(
        board_name=board_name,
        context=context,
        imported_at=imported_at or datetime.now(UTC),
        source_sha256=source_hash,
        catalog_hash=catalog_hash,
        parsed_entries=len(entries),
        mechanics_assumptions=mechanics_assumptions,
        entries=tuple(entries),
    )


def _catalog_hash(
    *,
    schema_version: str,
    parser_version: str,
    board_name: str,
    context: str,
    source_sha256: str,
    mechanics_assumptions: tuple[str, ...],
    entries: tuple[DraftPriceEntry, ...],
) -> str:
    canonical = json.dumps(
        {
            "schema_version": schema_version,
            "parser_version": parser_version,
            "board_name": board_name,
            "context": context,
            "source_sha256": source_sha256,
            "mechanics_assumptions": mechanics_assumptions,
            "entries": [entry.model_dump(mode="json") for entry in entries],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _computed_catalog_hash(catalog: DraftPriceCatalog) -> str:
    return _catalog_hash(
        schema_version=catalog.schema_version,
        parser_version=catalog.parser_version,
        board_name=catalog.board_name,
        context=catalog.context,
        source_sha256=catalog.source_sha256,
        mechanics_assumptions=catalog.mechanics_assumptions,
        entries=catalog.entries,
    )


class DraftPriceStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "catalog.json"

    def load(self) -> DraftPriceCatalog | None:
        if not self.path.is_file():
            return None
        try:
            catalog = DraftPriceCatalog.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as error:
            raise ValueError(
                f"invalid normalized pricing catalog at {self.path}: {error}"
            ) from error
        if _computed_catalog_hash(catalog) != catalog.catalog_hash:
            raise ValueError(
                f"invalid normalized pricing catalog at {self.path}: catalog hash mismatch"
            )
        return catalog

    def save(self, catalog: DraftPriceCatalog) -> None:
        if _computed_catalog_hash(catalog) != catalog.catalog_hash:
            raise ValueError("cannot save a pricing catalog with a mismatched catalog hash")
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / ".catalog.json.tmp"
        temporary.write_text(catalog.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def verify_source(self, catalog: DraftPriceCatalog) -> tuple[bool, str]:
        raw_files = tuple(path for path in self.root.glob("source.*") if path.is_file())
        if len(raw_files) != 1:
            return False, "Expected exactly one raw source file beside catalog.json."
        try:
            digest = hashlib.sha256(raw_files[0].read_bytes()).hexdigest()
        except OSError as error:
            return False, f"Could not read the imported source file: {error}"
        if digest != catalog.source_sha256:
            return False, "Imported source SHA-256 does not match the normalized catalog."
        return True, f"Verified against {raw_files[0].name}."

    def clear(self) -> bool:
        if not self.path.exists():
            return False
        self.path.unlink()
        return True
