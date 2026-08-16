from __future__ import annotations

import asyncio
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from koalabattle.formats import describe_format

from .models import MAX_TEAM_TEXT_LENGTH, TeamValidationResult


class ShowdownTeamValidator:
    def __init__(self, base_url: str, timeout_seconds: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def validate(self, team_text: str, format_id: str) -> TeamValidationResult:
        _validate_input(team_text, format_id)
        return await asyncio.to_thread(self._validate_sync, team_text, format_id)

    def _validate_sync(self, team_text: str, format_id: str) -> TeamValidationResult:
        body = json.dumps({"format": format_id, "team": team_text}).encode()
        request = Request(
            f"{self.base_url}/validate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                payload = json.loads(response.read(1_000_001))
        except HTTPError as error:
            detail = error.read(2_000).decode(errors="replace")
            raise ValueError(f"Showdown team validator rejected the request: {detail}") from error
        except (OSError, URLError) as error:
            raise RuntimeError("Showdown team validator is unavailable") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("valid"), bool):
            raise RuntimeError("Showdown team validator returned malformed JSON")
        return TeamValidationResult.model_validate(payload)


def _validate_input(team_text: str, format_id: str) -> None:
    descriptor = describe_format(format_id)
    if descriptor is None:
        raise ValueError(f"{format_id!r} is not a format in the pinned Showdown registry")
    if descriptor.random_team:
        raise ValueError(f"{descriptor.name} generates its own teams and takes no custom import")
    encoded = team_text.encode("utf-8")
    if not encoded or len(encoded) > MAX_TEAM_TEXT_LENGTH:
        raise ValueError(f"team text must be 1-{MAX_TEAM_TEXT_LENGTH} UTF-8 bytes")
    if any(ord(character) < 32 and character not in "\n\r\t" for character in team_text):
        raise ValueError("team text contains unsupported control characters")
