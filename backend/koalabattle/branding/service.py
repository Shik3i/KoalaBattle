from __future__ import annotations

import base64
import binascii
import hashlib
import secrets
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from koalabattle.models.orm import BrandAssetRow, ProductionRow
from koalabattle.storage.database import Database

from .marks import mark_ids
from .media import UnsupportedMedia, inspect
from .models import BrandAsset, BrandAssetKind, BrandAssetLibrary, UploadBrandAsset


class BrandAssetInUse(RuntimeError):
    """Deleting this asset would break a production that still references it."""

    def __init__(self, asset_id: str, productions: tuple[str, ...]) -> None:
        super().__init__(f"asset {asset_id} is referenced by {len(productions)} production(s)")
        self.asset_id = asset_id
        self.productions = productions


class BrandingService:
    """Stores user-uploaded logos, backgrounds, watermarks and fonts outside Git.

    Files live under ``settings.branding_root`` (``data/branding`` by default), named from
    a server-generated id. Only safe metadata reaches SQLite, so the database never carries
    an absolute path or an attacker-supplied filename.
    """

    def __init__(self, database: Database, root: Path) -> None:
        self.database = database
        self.root = root

    def _path(self, asset: BrandAsset) -> Path:
        return self.root / asset.relative_path

    async def library(self) -> BrandAssetLibrary:
        return BrandAssetLibrary(
            root=str(self.root), assets=await self.list_assets(), marks=mark_ids()
        )

    async def list_assets(self, kind: BrandAssetKind | None = None) -> tuple[BrandAsset, ...]:
        async with self.database.sessions() as session:
            statement = select(BrandAssetRow).order_by(BrandAssetRow.created_at.desc())
            if kind is not None:
                statement = statement.where(BrandAssetRow.kind == kind.value)
            rows = (await session.scalars(statement)).all()
        return tuple(_to_model(row) for row in rows)

    async def get(self, asset_id: str) -> BrandAsset | None:
        async with self.database.sessions() as session:
            row = await session.get(BrandAssetRow, asset_id)
        return _to_model(row) if row else None

    async def upload(self, request: UploadBrandAsset) -> BrandAsset:
        try:
            payload = base64.b64decode(request.data_base64, validate=True)
        except (binascii.Error, ValueError) as error:
            raise UnsupportedMedia("upload is not valid base64") from error
        if not payload:
            raise UnsupportedMedia("upload is empty")
        media = inspect(payload, request.kind)
        asset_id = secrets.token_hex(16)
        relative = f"{request.kind.value}/{asset_id}{media.extension}"
        destination = self.root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        asset = BrandAsset(
            id=asset_id,
            kind=request.kind,
            display_name=_clean_name(request.display_name),
            media_type=media.media_type,
            relative_path=relative,
            byte_size=len(payload),
            width=media.width,
            height=media.height,
            content_sha256=hashlib.sha256(payload).hexdigest(),
            created_at=datetime.now(UTC),
        )
        async with self.database.sessions() as session:
            session.add(
                BrandAssetRow(
                    id=asset.id,
                    schema_version=asset.schema_version,
                    kind=asset.kind.value,
                    display_name=asset.display_name,
                    media_type=asset.media_type,
                    relative_path=asset.relative_path,
                    byte_size=asset.byte_size,
                    width=asset.width,
                    height=asset.height,
                    content_sha256=asset.content_sha256,
                    created_at=asset.created_at,
                )
            )
            await session.commit()
        return asset

    async def media_path(self, asset_id: str) -> Path | None:
        """Resolve an asset to a file, refusing anything that escaped the media root."""
        asset = await self.get(asset_id)
        if asset is None:
            return None
        path = self._path(asset).resolve()
        if not path.is_relative_to(self.root.resolve()) or not path.is_file():
            return None
        return path

    async def references(self, asset_id: str) -> tuple[str, ...]:
        """Productions whose style still points at this asset."""
        async with self.database.sessions() as session:
            rows = (await session.scalars(select(ProductionRow))).all()
        return tuple(row.id for row in rows if asset_id in (row.style_json or ""))

    async def delete(self, asset_id: str, *, force: bool = False) -> bool:
        asset = await self.get(asset_id)
        if asset is None:
            return False
        used = await self.references(asset_id)
        if used and not force:
            raise BrandAssetInUse(asset_id, used)
        path = self._path(asset)
        path.unlink(missing_ok=True)
        async with self.database.sessions() as session:
            row = await session.get(BrandAssetRow, asset_id)
            if row is not None:
                await session.delete(row)
                await session.commit()
        return True

    async def missing(self, asset_ids: tuple[str, ...]) -> tuple[str, ...]:
        """Ids that no longer resolve to a readable file.

        A production that references a deleted logo must degrade to its documented
        fallback rather than crash or silently borrow an unrelated image, so callers need
        to be able to ask this question up front.
        """
        result: list[str] = []
        for asset_id in asset_ids:
            if await self.media_path(asset_id) is None:
                result.append(asset_id)
        return tuple(result)


def _clean_name(value: str) -> str:
    """Keep display names printable and free of anything that reads as a path.

    The name is a label and never a path, but a stored ``../../etc/passwd`` would still be
    a trap for any future code that forgot that. Strip the shape, not just the effect.
    """
    cleaned = "".join(character if character.isprintable() else " " for character in value)
    for token in ("/", "\\", ".."):
        cleaned = cleaned.replace(token, " ")
    cleaned = " ".join(cleaned.split())
    return cleaned[:80] or "Untitled asset"


def _to_model(row: BrandAssetRow) -> BrandAsset:
    return BrandAsset(
        schema_version=row.schema_version,
        id=row.id,
        kind=BrandAssetKind(row.kind),
        display_name=row.display_name,
        media_type=row.media_type,
        relative_path=row.relative_path,
        byte_size=row.byte_size,
        width=row.width,
        height=row.height,
        content_sha256=row.content_sha256,
        created_at=row.created_at,
    )
