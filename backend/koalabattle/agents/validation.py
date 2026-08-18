from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from koalabattle.core.models import (
    MAX_BANTER_CHARACTERS,
    MAX_COMMENTARY_CHARACTERS,
    MAX_STORED_COMMENTARY_CHARACTERS,
    MAX_STRATEGY_MEMORY_CHARACTERS,
)


class StructuredDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    commentary: str = Field(default="", max_length=MAX_STORED_COMMENTARY_CHARACTERS)
    # Trim after parsing so a wordy model response can still produce a legal turn.
    # AgentDecision applies the same maximum to the persisted/public value.
    banter: str | None = Field(default=None)
    strategy_memory: str | None = Field(default=None, max_length=MAX_STRATEGY_MEMORY_CHARACTERS)


def trim_commentary(commentary: str) -> str:
    """Keep public commentary to one readable line for the overlay and for TTS.

    Over-long commentary is trimmed rather than rejected: a usable action with a wordy
    explanation should never cost the agent its turn.
    """
    collapsed = " ".join(commentary.split())
    if len(collapsed) <= MAX_COMMENTARY_CHARACTERS:
        return collapsed
    clipped = collapsed[: MAX_COMMENTARY_CHARACTERS - 1]
    boundary = clipped.rfind(" ")
    if boundary > MAX_COMMENTARY_CHARACTERS // 2:
        clipped = clipped[:boundary]
    return f"{clipped.rstrip(' ,;:.')}…"


def trim_banter(banter: str | None) -> str:
    """Keep optional opponent-facing banter short, clean and safe to speak aloud."""
    if not banter:
        return ""
    collapsed = " ".join(banter.split())
    if len(collapsed) <= MAX_BANTER_CHARACTERS:
        return collapsed
    clipped = collapsed[: MAX_BANTER_CHARACTERS - 1]
    boundary = clipped.rfind(" ")
    if boundary > MAX_BANTER_CHARACTERS // 2:
        clipped = clipped[:boundary]
    return f"{clipped.rstrip(' ,;:.')}…"


def parse_structured_decision(raw_response: str, legal_ids: set[str]) -> StructuredDecision:
    try:
        payload = _decode_object(raw_response)
    except json.JSONDecodeError as error:
        raise ValueError("Response is not valid JSON.") from error
    try:
        response = StructuredDecision.model_validate(payload)
    except ValidationError as error:
        if isinstance(payload, dict) and "action" not in payload:
            raise ValueError("Missing `action`.") from error
        raise ValueError(f"Response schema is invalid: {error}") from error
    
    action = response.action.strip()
    if action not in legal_ids:
        # Check if action contains a legal id (e.g., 'move:1' in 'move:1 - Thunderbolt')
        matched = None
        for legal_id in sorted(legal_ids, key=len, reverse=True):
            if legal_id in action:
                matched = legal_id
                break
        if matched:
            action = matched
        else:
            raise ValueError("Selected action is no longer legal.")

    return response.model_copy(
        update={
            "action": action,
            "commentary": trim_commentary(response.commentary),
            "banter": trim_banter(response.banter),
        }
    )


def _decode_object(raw_response: str) -> object:
    stripped = raw_response.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as original:
        decoder = json.JSONDecoder()
        for index, character in enumerate(stripped):
            if character != "{":
                continue
            try:
                value, end = decoder.raw_decode(stripped[index:])
            except json.JSONDecodeError:
                continue
            suffix = stripped[index + end :].strip()
            if suffix and not suffix.startswith("```"):
                continue
            return value
        raise original
