from __future__ import annotations

from typing import Any

import openai
from openai import AsyncOpenAI

from koalabattle.core.models import (
    MAX_COMMENTARY_CHARACTERS,
    MAX_STRATEGY_MEMORY_CHARACTERS,
    ProviderErrorCategory,
    ProviderUsage,
)

from .base import (
    ProviderCapabilities,
    ProviderError,
    ProviderModel,
    ProviderRequest,
    ProviderResponse,
)

DECISION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "action": {"type": "string"},
        "commentary": {"type": "string", "maxLength": MAX_COMMENTARY_CHARACTERS},
        "strategy_memory": {
            "type": ["string", "null"],
            "maxLength": MAX_STRATEGY_MEMORY_CHARACTERS,
        },
    },
    "required": ["action", "commentary", "strategy_memory"],
    "additionalProperties": False,
}


class OpenAIProvider:
    name = "openai"
    capabilities = ProviderCapabilities(
        structured_output=True,
        model_listing=True,
        temperature=True,
        reasoning_control=True,
        usage_reporting=True,
    )

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        client = AsyncOpenAI(api_key=self._api_key, timeout=request.timeout_seconds, max_retries=0)
        arguments: dict[str, Any] = {
            "model": request.model,
            "input": request.prompt,
            "max_output_tokens": request.max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": request.output_schema_name,
                    "strict": True,
                    "schema": request.output_schema or DECISION_SCHEMA,
                }
            },
        }
        if request.system_prompt:
            arguments["instructions"] = request.system_prompt
        if request.temperature is not None:
            arguments["temperature"] = request.temperature
        if request.reasoning_effort is not None:
            arguments["reasoning"] = {"effort": request.reasoning_effort}
        try:
            response = await client.responses.create(**arguments)
        except Exception as error:
            raise _openai_error(error) from error
        usage_object = getattr(response, "usage", None)
        input_details = getattr(usage_object, "input_tokens_details", None)
        usage = ProviderUsage(
            input_tokens=getattr(usage_object, "input_tokens", None),
            output_tokens=getattr(usage_object, "output_tokens", None),
            cached_tokens=getattr(input_details, "cached_tokens", None),
            total_tokens=getattr(usage_object, "total_tokens", None),
        )
        return ProviderResponse(
            text=response.output_text,
            model=response.model,
            usage=usage,
            request_id=getattr(response, "_request_id", None),
            finish_reason=getattr(response, "status", None),
        )

    async def list_models(self) -> tuple[ProviderModel, ...]:
        client = AsyncOpenAI(api_key=self._api_key, max_retries=0)
        try:
            models = await client.models.list()
        except Exception as error:
            raise _openai_error(error) from error
        return tuple(
            ProviderModel(id=item.id) for item in sorted(models.data, key=lambda item: item.id)
        )


def _openai_error(error: Exception) -> ProviderError:
    if isinstance(error, openai.AuthenticationError):
        return ProviderError(ProviderErrorCategory.AUTHENTICATION, error, retryable=False)
    if isinstance(error, openai.RateLimitError):
        return ProviderError(ProviderErrorCategory.RATE_LIMIT, error, retryable=True)
    if isinstance(error, openai.APITimeoutError):
        return ProviderError(ProviderErrorCategory.TIMEOUT, error, retryable=True)
    if isinstance(error, openai.APIConnectionError):
        return ProviderError(ProviderErrorCategory.NETWORK, error, retryable=True)
    if isinstance(error, openai.BadRequestError):
        return ProviderError(ProviderErrorCategory.INVALID_REQUEST, error, retryable=False)
    if isinstance(error, openai.InternalServerError):
        return ProviderError(ProviderErrorCategory.PROVIDER_UNAVAILABLE, error, retryable=True)
    return ProviderError(ProviderErrorCategory.UNKNOWN, error, retryable=False)
