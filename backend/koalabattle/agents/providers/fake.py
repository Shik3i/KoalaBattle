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

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.calls += 1
        if self._action is None:
            prompt = json.loads(request.prompt)
            action = prompt["legal_actions"][0]
            self._action = (action["id"], action["name"])
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
