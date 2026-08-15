from __future__ import annotations

import json
from dataclasses import dataclass

from koalabattle.core.models import EstimatedCost, ProviderUsage


@dataclass(frozen=True)
class ModelPricing:
    input_per_million: float
    output_per_million: float
    cached_input_per_million: float | None = None


class PricingTable:
    def __init__(self, raw_json: str = "{}", version: str = "unconfigured") -> None:
        self.version = version
        decoded = json.loads(raw_json)
        if not isinstance(decoded, dict):
            raise ValueError("pricing table must be a JSON object")
        self._models: dict[str, ModelPricing] = {}
        for key, value in decoded.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                raise ValueError("pricing entries must map model keys to objects")
            self._models[key] = ModelPricing(
                input_per_million=float(value["input_per_million"]),
                output_per_million=float(value["output_per_million"]),
                cached_input_per_million=(
                    float(value["cached_input_per_million"])
                    if value.get("cached_input_per_million") is not None
                    else None
                ),
            )

    def estimate(self, provider: str, model: str, usage: ProviderUsage | None) -> EstimatedCost:
        pricing = self._models.get(f"{provider}:{model}")
        if pricing is None or usage is None:
            return EstimatedCost()
        input_tokens = usage.input_tokens or 0
        cached_tokens = min(usage.cached_tokens or 0, input_tokens)
        regular_input = input_tokens - cached_tokens
        cached_rate = pricing.cached_input_per_million or pricing.input_per_million
        amount = (
            regular_input * pricing.input_per_million
            + cached_tokens * cached_rate
            + (usage.output_tokens or 0) * pricing.output_per_million
        ) / 1_000_000
        return EstimatedCost(
            amount=round(amount, 8),
            currency="USD",
            pricing_version=self.version,
            available=True,
        )
