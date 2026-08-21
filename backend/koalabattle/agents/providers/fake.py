from __future__ import annotations

import asyncio
import json

from koalabattle.core.models import ProviderErrorCategory, ProviderUsage

from .base import (
    ProviderCapabilities,
    ProviderError,
    ProviderModel,
    ProviderRequest,
    ProviderResponse,
    TextDeltaCallback,
)


class FakeProvider:
    name = "fake"
    capabilities = ProviderCapabilities(
        structured_output=True,
        model_listing=True,
        temperature=True,
        reasoning_control=True,
        usage_reporting=True,
    )

    def __init__(self, scenario: str = "valid") -> None:
        self.scenario = scenario
        self.calls = 0
        self._action: tuple[str, str] | None = None

    async def generate(
        self,
        request: ProviderRequest,
        *,
        on_text_delta: TextDeltaCallback | None = None,
    ) -> ProviderResponse:
        self.calls += 1
        if self.scenario == "timeout":
            await asyncio.sleep(request.timeout_seconds + 1)
        if self.scenario == "provider_error":
            raise ProviderError(
                ProviderErrorCategory.PROVIDER_UNAVAILABLE,
                "deterministic fake provider failure",
                retryable=True,
            )
        if self.scenario == "rate_limit_then_valid" and self.calls == 1:
            raise ProviderError(
                ProviderErrorCategory.RATE_LIMIT,
                "deterministic fake rate limit",
                retryable=True,
            )
        if request.output_schema_name == "koalabattle_team":
            if self.scenario == "malformed_then_valid" and self.calls == 1:
                text = "not-json"
            elif self.scenario == "invalid_then_valid" and self.calls == 1:
                text = json.dumps({"team": "not a legal team"})
            else:
                text = json.dumps({"team": _FAKE_GEN9OU_TEAM})
            return ProviderResponse(
                text=text,
                model=request.model,
                usage=ProviderUsage(input_tokens=400, output_tokens=500, total_tokens=900),
                request_id=f"fake-team-{self.calls}",
                finish_reason="stop",
            )
        if request.output_schema_name == "koalabattle_draft_action":
            legal = request.output_schema.get("properties", {}).get("action", {}).get("enum", [])
            action = next((item for item in legal if str(item).startswith("pick:")), None)
            if not isinstance(action, str):
                raise ValueError("fake draft request has no pick action")
            if self.scenario == "malformed_then_valid" and self.calls == 1:
                text = "not-json"
            elif self.scenario == "invalid_then_valid" and self.calls == 1:
                text = json.dumps({"action": "pick:not-legal"})
            else:
                text = json.dumps({"action": action})
            return ProviderResponse(
                text=text,
                model=request.model,
                usage=ProviderUsage(input_tokens=200, output_tokens=8, total_tokens=208),
                request_id=f"fake-draft-{self.calls}",
                finish_reason="stop",
            )
        if self._action is None:
            self._action = _first_legal_action(request.prompt)
        if self.scenario == "malformed_then_valid" and self.calls == 1:
            text = "not-json"
        elif self.scenario == "invalid_then_valid" and self.calls == 1:
            text = json.dumps({"action": "move:999", "commentary": "Invalid test action."})
        else:
            assert self._action is not None
            text = json.dumps(
                {
                    "action": self._action[0],
                    "commentary": f"Fake API selected {self._action[1]} deterministically.",
                    "banter": (
                        "That last choice was clever; now answer this."
                        if "BANTER MODE\nEnabled" in request.prompt
                        else None
                    ),
                    "strategy_memory": "Preserve healthy switch options for the next turn.",
                }
            )
        return ProviderResponse(
            text=text,
            model=request.model,
            usage=ProviderUsage(input_tokens=120, output_tokens=24, total_tokens=144),
            request_id=f"fake-{self.calls}",
            finish_reason="stop",
        )

    async def list_models(self) -> tuple[ProviderModel, ...]:
        return (ProviderModel(id="fake-battle-v1", display_name="Deterministic Fake"),)


def _first_legal_action(prompt: str) -> tuple[str, str]:
    """Read the first action out of the rendered LEGAL ACTIONS block deterministically."""
    lines = prompt.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != "LEGAL ACTIONS":
            continue
        for offset in range(index + 1, len(lines)):
            candidate = lines[offset].strip()
            if not candidate:
                continue
            if candidate.startswith(("move:", "switch:")):
                detail = lines[offset + 1].strip() if offset + 1 < len(lines) else candidate
                return candidate, detail.split(" · ")[0].removeprefix("Switch to ") or candidate
            break
    raise ValueError("rendered prompt contains no LEGAL ACTIONS block")


_FAKE_GEN9OU_TEAM = """Great Tusk @ Leftovers
Ability: Protosynthesis
Tera Type: Water
EVs: 252 HP / 4 Atk / 252 Def
Impish Nature
- Earthquake
- Rapid Spin
- Stealth Rock
- Knock Off

Gholdengo @ Choice Scarf
Ability: Good as Gold
Tera Type: Steel
EVs: 4 Def / 252 SpA / 252 Spe
Timid Nature
- Make It Rain
- Shadow Ball
- Focus Blast
- Trick

Dragonite @ Heavy-Duty Boots
Ability: Multiscale
Tera Type: Normal
EVs: 252 Atk / 4 SpD / 252 Spe
Adamant Nature
- Dragon Dance
- Extreme Speed
- Earthquake
- Ice Spinner

Kingambit @ Black Glasses
Ability: Supreme Overlord
Tera Type: Dark
EVs: 252 Atk / 4 SpD / 252 Spe
Adamant Nature
- Kowtow Cleave
- Sucker Punch
- Iron Head
- Swords Dance

Rillaboom @ Choice Band
Ability: Grassy Surge
Tera Type: Grass
EVs: 252 Atk / 4 SpD / 252 Spe
Adamant Nature
- Grassy Glide
- Wood Hammer
- U-turn
- Knock Off

Rotom-Wash @ Leftovers
Ability: Levitate
Tera Type: Steel
EVs: 252 HP / 200 Def / 56 Spe
Bold Nature
- Volt Switch
- Hydro Pump
- Will-O-Wisp
- Protect"""
