from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from time import perf_counter
from typing import Protocol
from uuid import uuid4

from koalabattle.agents.providers import LLMProvider, ProviderError, ProviderRequest
from koalabattle.core.models import ProviderUsage, TeamSource

from .models import (
    MAX_TEAM_TEXT_LENGTH,
    TEAM_BUILD_PROFILE_VERSION,
    TeamBuildAudit,
    TeamBuildRequest,
    TeamSnapshot,
    TeamValidationResult,
)
from .repository import TeamRepository

TEAM_OUTPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"team": {"type": "string", "maxLength": MAX_TEAM_TEXT_LENGTH}},
    "required": ["team"],
    "additionalProperties": False,
}


class TeamValidator(Protocol):
    async def validate(self, team_text: str, format_id: str) -> TeamValidationResult: ...


class TeamBuilder:
    def __init__(
        self,
        repository: TeamRepository,
        validator: TeamValidator,
    ) -> None:
        self.repository = repository
        self.validator = validator

    async def build(
        self,
        request: TeamBuildRequest,
        provider: LLMProvider,
    ) -> tuple[TeamBuildAudit, TeamSnapshot | None]:
        started = perf_counter()
        audit_id = uuid4()
        original_prompt = _build_prompt(request)
        prompt = original_prompt
        raw_responses: list[str] = []
        validation_errors: list[tuple[str, ...]] = []
        usages: list[ProviderUsage] = []
        snapshot = None
        for attempt in range(request.max_repair_attempts + 1):
            try:
                async with asyncio.timeout(request.configuration.timeout_seconds):
                    response = await provider.generate(
                        ProviderRequest(
                            prompt=prompt,
                            model=request.model,
                            timeout_seconds=request.configuration.timeout_seconds,
                            max_output_tokens=max(request.configuration.max_output_tokens, 2_048),
                            temperature=(
                                request.configuration.temperature
                                if provider.capabilities.temperature
                                else None
                            ),
                            output_schema_name="koalabattle_team",
                            output_schema=TEAM_OUTPUT_SCHEMA,
                        )
                    )
            except TimeoutError:
                validation_errors.append(("provider request timed out",))
                break
            except ProviderError as error:
                validation_errors.append((f"provider {error.category.value}: {error.detail}",))
                break
            raw_responses.append(response.text)
            if response.usage is not None:
                usages.append(response.usage)
            try:
                team_text = _parse_team_response(response.text)
                validation = await self.validator.validate(team_text, request.format)
            except ValueError as error:
                validation_errors.append((str(error),))
            else:
                validation_errors.append(validation.errors)
                if validation.valid:
                    snapshot = await self.repository.create_snapshot(
                        name=request.name,
                        source=TeamSource.AGENT_GENERATED,
                        submitted_text=team_text,
                        validation=validation,
                        generation_audit={
                            "audit_id": str(audit_id),
                            "provider": provider.name,
                            "model": response.model,
                            "prompt_profile_version": TEAM_BUILD_PROFILE_VERSION,
                        },
                    )
                    break
            if attempt < request.max_repair_attempts:
                prompt = _repair_prompt(original_prompt, validation_errors[-1])

        audit = TeamBuildAudit(
            id=audit_id,
            participant=request.participant,
            provider=provider.name,
            model=request.model,
            rendered_prompt=original_prompt,
            raw_responses=tuple(raw_responses),
            validation_errors=tuple(validation_errors),
            repair_attempts=max(0, len(raw_responses) - 1),
            success=snapshot is not None,
            team_snapshot_id=snapshot.id if snapshot else None,
            usage=_aggregate_usage(usages),
            latency_ms=round((perf_counter() - started) * 1000),
            created_at=datetime.now(UTC),
        )
        await self.repository.record_build_audit(audit)
        return audit, snapshot


def _build_prompt(request: TeamBuildRequest) -> str:
    return json.dumps(
        {
            "task": "team_build",
            "profile_version": TEAM_BUILD_PROFILE_VERSION,
            "format": "Gen 9 OU",
            "objective": "Build the strongest legal balanced team you can for this format.",
            "team_size": 6,
            "rules": [
                "Use current standard Gen 9 OU legality.",
                "Return a complete Pokemon Showdown import/export team.",
                "Do not include markdown fences or explanations inside the team field.",
            ],
            "response_schema": {"team": "Pokemon Showdown import/export text"},
        },
        indent=2,
        sort_keys=True,
    )


def _repair_prompt(original_prompt: str, errors: tuple[str, ...]) -> str:
    payload = json.loads(original_prompt)
    payload["repair"] = {
        "errors": list(errors),
        "instruction": "Return the complete corrected team, not a patch.",
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _parse_team_response(raw: str) -> str:
    try:
        payload: object = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("team builder response is not valid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("team builder response must contain one string field named `team`")
    team_value = payload.get("team")
    if not isinstance(team_value, str):
        raise ValueError("team builder response must contain one string field named `team`")
    team = team_value.strip()
    if not team or len(team.encode()) > MAX_TEAM_TEXT_LENGTH:
        raise ValueError(f"generated team must be 1-{MAX_TEAM_TEXT_LENGTH} UTF-8 bytes")
    return team


def _aggregate_usage(usages: list[ProviderUsage]) -> ProviderUsage | None:
    if not usages:
        return None

    def total(field: str) -> int | None:
        values = [getattr(usage, field) for usage in usages]
        present = [value for value in values if value is not None]
        return sum(present) if present else None

    return ProviderUsage(
        input_tokens=total("input_tokens"),
        output_tokens=total("output_tokens"),
        cached_tokens=total("cached_tokens"),
        total_tokens=total("total_tokens"),
        details={"requests": len(usages)},
    )
