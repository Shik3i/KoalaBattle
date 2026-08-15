from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class StructuredDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    commentary: str = Field(default="", max_length=1000)


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
    if response.action not in legal_ids:
        raise ValueError("Selected action is no longer legal.")
    return response


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
