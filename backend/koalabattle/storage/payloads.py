"""Lossless compression for stored battle-event payloads.

Event payloads dominate this database: a `state_snapshot` re-serializes both full
teams, and 82% of the events table was those snapshots. They are also extremely
repetitive — one snapshot differs from the previous snapshot of the same match by
a few HP values.

zlib can exploit that directly: a previous payload used as the compression
dictionary turns the repetition into a back-reference. Measured on real archives,
chaining each payload against the previous payload *of the same event type* takes
the events table from 5.0x (independent rows) to about 14x.

Chaining is only safe because of two properties of this schema:

* Events are always read as a whole match ordered by sequence (`_archive`), so
  the decoder walks the chain in the order it was built.
* Appends for one match are serialized by a per-match lock, so the chain cannot
  interleave.

Every `KEYFRAME_INTERVAL`-th payload of a type is stored independently anyway.
That bounds two things a pure chain leaves unbounded: how many rows one corrupt
row can take with it, and how far back a future random-access reader would have
to start decoding. The remaining loss is small — full chaining measured 15.0x
against 14.2x at this interval.

The encoding is otherwise self-describing: a row records whether it is a keyframe,
so a decoder needs no external dictionary file or version negotiation.
"""

from __future__ import annotations

import zlib

#: Independent payload every N payloads of the same type within a match.
KEYFRAME_INTERVAL = 32

#: zlib level 6 is the knee of the curve here; 9 costs noticeably more CPU per
#: append for well under a percent of size on this data.
_LEVEL = 6
#: zlib dictionaries read at most the trailing 32 KiB, so a longer one is wasted.
_MAX_DICTIONARY = 32 * 1024


def compress_payload(payload: bytes, previous: bytes | None) -> tuple[bytes, bool]:
    """Compress `payload`, optionally against the previous payload of its type.

    Returns `(blob, keyframe)`. `keyframe` is True when the blob decodes on its
    own; callers must record it, because the decoder cannot tell from the bytes.
    Passing `previous=None` always produces a keyframe, so a caller that has lost
    track of the chain (a restarted process, a fresh match) stays correct and
    only gives up compression.
    """
    if previous is None:
        return zlib.compress(payload, _LEVEL), True
    compressor = zlib.compressobj(
        _LEVEL, zlib.DEFLATED, zlib.MAX_WBITS, zlib.DEF_MEM_LEVEL, 0,
        previous[-_MAX_DICTIONARY:],
    )
    return compressor.compress(payload) + compressor.flush(), False


def decompress_payload(blob: bytes, keyframe: bool, previous: bytes | None) -> bytes:
    """Restore one payload. `previous` is the raw payload this row was chained to.

    A chained row without its predecessor is unrecoverable rather than subtly
    wrong, so that case raises instead of returning a plausible-looking result.
    """
    if keyframe:
        return zlib.decompress(blob)
    if previous is None:
        raise ValueError("a chained payload cannot be decoded without its predecessor")
    decompressor = zlib.decompressobj(zlib.MAX_WBITS, previous[-_MAX_DICTIONARY:])
    return decompressor.decompress(blob) + decompressor.flush()


class ChainEncoder:
    """Per-match compression state: the last raw payload seen for each event type.

    Held in memory rather than read back from the database on every append. A miss
    — first event of a type, or a process that restarted mid-match — simply emits
    a keyframe, so correctness never depends on this cache surviving.
    """

    def __init__(self) -> None:
        self._previous: dict[str, bytes] = {}
        self._counts: dict[str, int] = {}

    def encode(self, event_type: str, payload: bytes) -> tuple[bytes, bool]:
        index = self._counts.get(event_type, 0)
        previous = None if index % KEYFRAME_INTERVAL == 0 else self._previous.get(event_type)
        blob, keyframe = compress_payload(payload, previous)
        self._previous[event_type] = payload
        self._counts[event_type] = index + 1
        return blob, keyframe


class ChainDecoder:
    """Mirror of `ChainEncoder` for reading a match back in sequence order."""

    def __init__(self) -> None:
        self._previous: dict[str, bytes] = {}

    def decode(self, event_type: str, blob: bytes, keyframe: bool) -> bytes:
        payload = decompress_payload(blob, keyframe, self._previous.get(event_type))
        self._previous[event_type] = payload
        return payload
