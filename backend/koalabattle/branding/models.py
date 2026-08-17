from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

BRANDING_SCHEMA_VERSION = "1.0"

#: Uploaded payload ceiling *before* base64 expansion. Fonts are smaller than images
#: because a production only needs a display face, not a full family.
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_FONT_BYTES = 4 * 1024 * 1024
#: Guards against decompression bombs: a 200-megapixel PNG is a few hundred kilobytes on
#: disk but gigabytes once decoded, so the dimensions are checked from the header and the
#: file is rejected before any decoder ever sees it.
MAX_IMAGE_PIXELS = 8192 * 8192
MAX_IMAGE_EDGE = 8192

AssetId = Annotated[str, Field(pattern=r"^[a-z0-9]{32}$")]


class FrozenBrandingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BrandAssetKind(StrEnum):
    LOGO = "logo"
    BACKGROUND = "background"
    WATERMARK = "watermark"
    FONT = "font"


class BrandAsset(FrozenBrandingModel):
    schema_version: str = BRANDING_SCHEMA_VERSION
    id: AssetId
    kind: BrandAssetKind
    display_name: str = Field(min_length=1, max_length=80)
    media_type: str = Field(max_length=60)
    #: Path relative to the branding root. Never user-controlled: the server generates it
    #: from the asset id, so an uploaded filename can never escape the media directory.
    relative_path: str = Field(max_length=160)
    byte_size: int = Field(ge=1)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: datetime

    @property
    def media_url(self) -> str:
        return f"/api/branding/assets/{self.id}/media"


class UploadBrandAsset(FrozenBrandingModel):
    kind: BrandAssetKind
    display_name: str = Field(min_length=1, max_length=80)
    #: Base64 file bytes. Using a JSON body rather than multipart keeps the API dependency
    #: free and makes the size ceiling checkable before anything is decoded or written.
    data_base64: str = Field(min_length=8, max_length=16 * 1024 * 1024)


class BrandAssetLibrary(FrozenBrandingModel):
    schema_version: str = BRANDING_SCHEMA_VERSION
    root: str
    assets: tuple[BrandAsset, ...] = ()
    marks: tuple[str, ...] = ()
