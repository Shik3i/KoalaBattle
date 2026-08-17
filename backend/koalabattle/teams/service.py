from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from time import perf_counter
from typing import Literal, Protocol
from uuid import uuid4

from koalabattle.agents.providers import LLMProvider, ProviderError, ProviderRequest
from koalabattle.core.models import ProviderUsage, TeamSource

from .models import (
    MAX_TEAM_TEXT_LENGTH,
    TEAM_BUILD_PROFILE_VERSION,
    TeamBuildAudit,
    TeamBuildRequest,
    TeamPromptContext,
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
    return render_team_prompt(
        request.format, request.participant, request.context, response="json"
    )


def render_team_prompt(
    format_id: str,
    participant: str,
    context: TeamPromptContext,
    *,
    response: Literal["text", "json"] = "text",
) -> str:
    """Render the team-building prompt for one participant.

    Both flows describe the same team; they differ only in how the answer comes back. The
    automated builder parses a structured `team` field, while the copy-and-paste flow feeds
    the reply straight into a paste box that expects a Showdown export — asking it for JSON
    there just makes the user paste a JSON blob the validator cannot read.
    """
    label = context.format_name or format_id
    rules = [
        f"Use current standard {label} legality.",
        "Return a complete Pokemon Showdown import/export team.",
    ]
    payload: dict[str, object] = {
        "task": "team_build",
        "profile_version": TEAM_BUILD_PROFILE_VERSION,
        "format": label,
        "format_id": format_id,
        "objective": f"Build the strongest legal balanced team you can for {label}.",
        "team_size": context.team_size,
    }
    if response == "json":
        payload["response_schema"] = {"team": "Pokemon Showdown import/export text"}
        rules.append("Do not include markdown fences or explanations inside the team field.")
    else:
        payload["response"] = (
            "Reply with the Showdown export text itself and nothing else. No JSON, no"
            " wrapper object, no code fences, no commentary before or after it. The reply is"
            " pasted straight into a team box, so the first line must be the first Pokemon."
        )
        rules.append(
            "Do not wrap the team in JSON or markdown. Literal \\n escapes are not accepted;"
            " use real line breaks."
        )
    if participant:
        payload["participant"] = participant
    if context.generation is not None:
        payload["generation"] = context.generation
        rules.append(
            f"Only Generation {context.generation} mechanics exist. Do not rely on later ones."
        )
    if context.game_type:
        payload["game_type"] = context.game_type
    if context.mechanics:
        payload["available_mechanics"] = list(context.mechanics)
    if context.absent_mechanics:
        payload["absent_mechanics"] = list(context.absent_mechanics)
    if context.opponent:
        payload["opponent"] = context.opponent
    if context.maximum_turns is not None:
        payload["maximum_turns"] = context.maximum_turns
        rules.append(
            f"The battle is cut off after {context.maximum_turns} turns; a stall win is not"
            " guaranteed."
        )
    competition = _competition_payload(context)
    if competition:
        payload["competition"] = competition
    payload["export_format"] = _export_format(context)
    rules.append(
        "Follow `export_format` exactly. Every set needs its EV line, or Showdown rejects the"
        " team with \"did you forget to EV it?\"."
    )
    payload["rules"] = rules
    return json.dumps(payload, indent=2, sort_keys=True)


def _export_format(context: TeamPromptContext) -> dict[str, object]:
    """Spell out the Showdown export syntax this format actually accepts.

    Without this the model returns a bare species-and-moves sketch, and Showdown refuses it:
    an unevved set fails validation outright, and older generations have no ability, item or
    nature line to give at all.
    """
    lines = ["<Species>" + (" @ <Item>" if context.has_items else "")]
    example = ["Snorlax @ Leftovers" if context.has_items else "Snorlax"]
    if context.has_abilities:
        lines.append("Ability: <Ability>")
        example.append("Ability: Thick Fat")
    lines.append("EVs: <n> HP / <n> Atk / <n> Def / <n> SpA / <n> SpD / <n> Spe")
    if context.has_natures:
        lines.append("<Nature> Nature")
        example.append("EVs: 252 HP / 252 Atk / 4 SpD")
        example.append("Adamant Nature")
    else:
        # Generations 1-2 have no natures and no EV cap; Showdown expects the maximum.
        example.append("EVs: 252 HP / 252 Atk / 252 Def / 252 SpA / 252 SpD / 252 Spe")
    lines.append("- <Move>  (one line per move, up to four)")
    example.extend(["- Body Slam", "- Earthquake", "- Hyper Beam", "- Self-Destruct"])
    notes = [
        "One blank line between sets.",
        "Plain text only: no numbering, no commentary, no markdown fences.",
    ]
    if context.has_natures:
        notes.append("EVs total at most 508, with at most 252 on any one stat.")
    else:
        notes.append(
            "This generation has no EV limit and no natures: give every stat 252 EVs and omit"
            " the nature line."
        )
    if not context.has_abilities:
        notes.append("This generation has no abilities: omit the Ability line.")
    if not context.has_items:
        notes.append("This generation has no held items: omit the ` @ Item` suffix.")
    return {
        "syntax": lines,
        "example_set": "\n".join(example),
        "notes": notes,
    }


def _competition_payload(context: TeamPromptContext) -> dict[str, object]:
    competition: dict[str, object] = {}
    if context.tournament_name:
        competition["name"] = context.tournament_name
    if context.tournament_structure:
        competition["structure"] = context.tournament_structure
    if context.rounds is not None:
        competition["rounds"] = context.rounds
    if context.games_per_series is not None:
        competition["games_per_series"] = context.games_per_series
    if context.team_reused_across_series is not None:
        competition["team_reused_across_series"] = context.team_reused_across_series
        competition["note"] = (
            "The same team is used for every series; build for a varied field, not one matchup."
            if context.team_reused_across_series
            else "The team may be rebuilt between series."
        )
    return competition


def _repair_prompt(original_prompt: str, errors: tuple[str, ...]) -> str:
    payload = json.loads(original_prompt)
    payload["repair"] = {
        "errors": list(errors),
        "instruction": "Return the complete corrected team, not a patch.",
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def unwrap_team_text(submitted: str) -> str:
    """Recover the Showdown export from a reply that came back wrapped.

    Chat models routinely answer with `{"team": "Tauros\\nEVs: ..."}` even when asked for bare
    text, and a code fence is just as common. Pasting that verbatim used to reach Showdown as
    one escaped line and fail with `The Pokemon "" does not exist.`, which says nothing about
    the real problem. Unwrap what is obviously a wrapper and let the validator judge the team.
    """
    text = submitted.strip()
    if text.startswith("```"):
        fenced = text.split("```")
        if len(fenced) >= 3:
            body = fenced[1]
            text = body.split("\n", 1)[1] if "\n" in body else body
            text = text.strip()
    if not text.startswith("{"):
        return text
    try:
        payload: object = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(payload, dict):
        team = payload.get("team")
        if isinstance(team, str) and team.strip():
            return team.strip()
    return text


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
