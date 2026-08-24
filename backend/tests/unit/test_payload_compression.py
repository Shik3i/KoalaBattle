from __future__ import annotations

import json
import zlib

import pytest

from koalabattle.storage.payloads import (
    KEYFRAME_INTERVAL,
    ChainDecoder,
    ChainEncoder,
    compress_payload,
    decompress_payload,
)


def _snapshot(turn: int, hp: int) -> bytes:
    """A payload shaped like the real thing: mostly identical between turns."""
    team = [
        {
            "id": f"p1: Mon {index}",
            "name": f"Mon {index}",
            "species": f"Mon {index}",
            "level": 50,
            "types": ["Normal"],
            "moves": ["Tackle", "Protect", "Rest", "Sleep Talk"],
            "boosts": {"atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0},
            "current_hp": hp if index == 1 else 200,
            "max_hp": 200,
            "hp_fraction": hp / 200 if index == 1 else 1.0,
        }
        for index in range(1, 7)
    ]
    return json.dumps({"state": {"turn": turn, "player": {"team": team}}}).encode()


def test_a_chained_payload_round_trips_exactly() -> None:
    first, second = _snapshot(1, 200), _snapshot(2, 140)
    blob, keyframe = compress_payload(second, first)

    assert keyframe is False
    assert decompress_payload(blob, keyframe, first) == second


def test_chaining_beats_independent_compression_on_snapshot_shaped_data() -> None:
    """The whole point: consecutive snapshots differ by a few values, so the
    previous one is an excellent dictionary. If this stops holding, the extra
    machinery is not buying anything and should go."""
    first, second = _snapshot(1, 200), _snapshot(2, 140)
    chained, _ = compress_payload(second, first)
    independent, _ = compress_payload(second, None)

    assert len(chained) * 3 < len(independent), (
        f"chained {len(chained)}B vs independent {len(independent)}B"
    )


def test_a_missing_predecessor_raises_instead_of_returning_garbage() -> None:
    blob, keyframe = compress_payload(_snapshot(2, 140), _snapshot(1, 200))

    with pytest.raises(ValueError, match="predecessor"):
        decompress_payload(blob, keyframe, None)


def test_a_wrong_predecessor_never_passes_silently() -> None:
    """zlib records a checksum of the dictionary, so a mismatched chain is
    detected rather than decoded into a plausible-looking wrong payload."""
    blob, keyframe = compress_payload(_snapshot(2, 140), _snapshot(1, 200))

    with pytest.raises(zlib.error):
        decompress_payload(blob, keyframe, _snapshot(9, 7))


def test_the_encoder_emits_a_keyframe_at_the_configured_interval() -> None:
    encoder = ChainEncoder()
    keyframes = [encoder.encode("state_snapshot", _snapshot(i, 200 - i))[1] for i in range(70)]

    assert keyframes[0] is True
    assert [index for index, value in enumerate(keyframes) if value] == [
        index for index in range(70) if index % KEYFRAME_INTERVAL == 0
    ]


def test_each_event_type_keeps_its_own_chain() -> None:
    """Interleaved types must not use each other as dictionaries: the previous
    event of a *different* type is a useless dictionary, which measured as the
    difference between 5x and 14x on real archives."""
    encoder, decoder = ChainEncoder(), ChainDecoder()
    stream = [
        ("state_snapshot", _snapshot(1, 200)),
        ("move_used", b'{"actor":"p1a: Mon 1","move":"Tackle"}'),
        ("state_snapshot", _snapshot(2, 160)),
        ("move_used", b'{"actor":"p2a: Mon 4","move":"Protect"}'),
        ("state_snapshot", _snapshot(3, 120)),
    ]

    encoded = [(kind, *encoder.encode(kind, payload)) for kind, payload in stream]
    restored = [decoder.decode(kind, blob, keyframe) for kind, blob, keyframe in encoded]

    assert restored == [payload for _, payload in stream]
    # Only the first of each type is a keyframe; the rest chain within their type.
    assert [keyframe for _, _, keyframe in encoded] == [True, True, False, False, False]


def test_a_restarted_encoder_stays_correct_and_only_loses_compression() -> None:
    """The chain cache is an optimization. A process that restarts mid-match has
    no predecessors, and must produce readable rows rather than a broken chain."""
    payloads = [("state_snapshot", _snapshot(index, 200 - index)) for index in range(6)]
    first = ChainEncoder()
    encoded = [(kind, *first.encode(kind, payload)) for kind, payload in payloads[:3]]
    # ...restart: a fresh encoder with no memory of the match.
    second = ChainEncoder()
    encoded += [(kind, *second.encode(kind, payload)) for kind, payload in payloads[3:]]

    decoder = ChainDecoder()
    restored = [decoder.decode(kind, blob, keyframe) for kind, blob, keyframe in encoded]

    assert restored == [payload for _, payload in payloads]
    assert encoded[3][2] is True, "the first payload after a restart must be self-contained"


def test_an_empty_or_tiny_payload_round_trips() -> None:
    encoder, decoder = ChainEncoder(), ChainDecoder()
    for payload in (b"null", b"{}", b'{"a":1}'):
        blob, keyframe = encoder.encode("edge", payload)
        assert decoder.decode("edge", blob, keyframe) == payload
