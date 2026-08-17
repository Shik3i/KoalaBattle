"""Content inspection for user-uploaded branding media.

Everything here works on raw bytes and header fields only. No image or font decoder is
invoked, and the uploaded filename is never consulted or stored as a path — the caller
generates the on-disk name. That keeps the attack surface to "parse a few integers".

SVG is deliberately unsupported. A safe SVG subset needs a real sanitizer (scripts,
foreignObject, external references, XML entity expansion), and a half-sanitized SVG
rendered inside the app is worse than no SVG at all.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .models import (
    MAX_FONT_BYTES,
    MAX_IMAGE_BYTES,
    MAX_IMAGE_EDGE,
    MAX_IMAGE_PIXELS,
    BrandAssetKind,
)


class UnsupportedMedia(ValueError):
    """The upload is not a supported, well-formed image or font."""


@dataclass(frozen=True)
class InspectedMedia:
    media_type: str
    extension: str
    width: int | None
    height: int | None


_IMAGE_TYPES = {"image/png": ".png", "image/webp": ".webp", "image/jpeg": ".jpg"}
_FONT_TYPES = {"font/woff2": ".woff2", "font/ttf": ".ttf", "font/otf": ".otf"}


def inspect(payload: bytes, kind: BrandAssetKind) -> InspectedMedia:
    if kind is BrandAssetKind.FONT:
        return _inspect_font(payload)
    return _inspect_image(payload)


def _inspect_font(payload: bytes) -> InspectedMedia:
    if len(payload) > MAX_FONT_BYTES:
        raise UnsupportedMedia(f"font exceeds {MAX_FONT_BYTES // (1024 * 1024)} MB")
    if payload[:4] == b"wOF2":
        media_type = "font/woff2"
    elif payload[:4] in (b"\x00\x01\x00\x00", b"true", b"ttcf"):
        media_type = "font/ttf"
    elif payload[:4] == b"OTTO":
        media_type = "font/otf"
    else:
        raise UnsupportedMedia("unsupported font: expected WOFF2, TrueType or OpenType")
    return InspectedMedia(media_type, _FONT_TYPES[media_type], None, None)


def _inspect_image(payload: bytes) -> InspectedMedia:
    if len(payload) > MAX_IMAGE_BYTES:
        raise UnsupportedMedia(f"image exceeds {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
    size = _png_size(payload) or _webp_size(payload) or _jpeg_size(payload)
    if size is None:
        raise UnsupportedMedia("unsupported image: expected PNG, WebP or JPEG")
    media_type, width, height = size
    if width > MAX_IMAGE_EDGE or height > MAX_IMAGE_EDGE:
        raise UnsupportedMedia(f"image edge exceeds {MAX_IMAGE_EDGE}px")
    if width * height > MAX_IMAGE_PIXELS:
        raise UnsupportedMedia("image resolution exceeds the supported pixel budget")
    return InspectedMedia(media_type, _IMAGE_TYPES[media_type], width, height)


def _png_size(payload: bytes) -> tuple[str, int, int] | None:
    if payload[:8] != b"\x89PNG\r\n\x1a\n" or payload[12:16] != b"IHDR":
        return None
    if len(payload) < 24:
        raise UnsupportedMedia("truncated PNG header")
    width, height = struct.unpack(">II", payload[16:24])
    if not width or not height:
        raise UnsupportedMedia("PNG reports a zero dimension")
    return "image/png", width, height


def _webp_size(payload: bytes) -> tuple[str, int, int] | None:
    if payload[:4] != b"RIFF" or payload[8:12] != b"WEBP":
        return None
    chunk = payload[12:16]
    if chunk == b"VP8X" and len(payload) >= 30:
        width = int.from_bytes(payload[24:27], "little") + 1
        height = int.from_bytes(payload[27:30], "little") + 1
    elif chunk == b"VP8 " and len(payload) >= 30:
        width = int.from_bytes(payload[26:28], "little") & 0x3FFF
        height = int.from_bytes(payload[28:30], "little") & 0x3FFF
    elif chunk == b"VP8L" and len(payload) >= 25:
        bits = int.from_bytes(payload[21:25], "little")
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
    else:
        raise UnsupportedMedia("unsupported or truncated WebP variant")
    if not width or not height:
        raise UnsupportedMedia("WebP reports a zero dimension")
    return "image/webp", width, height


def _jpeg_size(payload: bytes) -> tuple[str, int, int] | None:
    if payload[:2] != b"\xff\xd8":
        return None
    index = 2
    limit = len(payload)
    while index + 9 < limit:
        if payload[index] != 0xFF:
            index += 1
            continue
        marker = payload[index + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        length = int.from_bytes(payload[index + 2 : index + 4], "big")
        if length < 2:
            raise UnsupportedMedia("malformed JPEG segment")
        # SOF0..SOF15, excluding the DHT/JPG/DAC markers that share the range.
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height = int.from_bytes(payload[index + 5 : index + 7], "big")
            width = int.from_bytes(payload[index + 7 : index + 9], "big")
            if not width or not height:
                raise UnsupportedMedia("JPEG reports a zero dimension")
            return "image/jpeg", width, height
        index += 2 + length
    raise UnsupportedMedia("JPEG has no frame header")
