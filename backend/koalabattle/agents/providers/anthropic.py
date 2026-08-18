from __future__ import annotations

from typing import Any

import anthropic
from anthropic import AsyncAnthropic

from koalabattle.core.models import ProviderErrorCategory, ProviderUsage

from .base import (
    ProviderCapabilities,
    ProviderError,
    ProviderModel,
    ProviderRequest,
    ProviderResponse,
    TextDeltaCallback,
)
from .openai import DECISION_SCHEMA


class AnthropicProvider:
    name = "anthropic"
    capabilities = ProviderCapabilities(
        structured_output=True,
        model_listing=True,
        temperature=True,
        reasoning_control=False,
        usage_reporting=True,
    )

    def __init__(self, api_key: str) -> None:
        self._client = AsyncAnthropic(
            api_key=api_key,
            max_retries=0,
        )

    async def generate(
        self,
        request: ProviderRequest,
        *,
        on_text_delta: TextDeltaCallback | None = None,
    ) -> ProviderResponse:
        arguments: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_output_tokens,
            "messages": [{"role": "user", "content": request.prompt}],
            "timeout": request.timeout_seconds,
            "output_config": {
                "format": {
                    "type": "json_schema",
                    "schema": request.output_schema or DECISION_SCHEMA,
                }
            },
        }
        if request.system_prompt:
            arguments["system"] = request.system_prompt
        if request.temperature is not None:
            arguments["temperature"] = request.temperature
        try:
            response = await self._client.messages.create(**arguments)
        except Exception as error:
            raise _anthropic_error(error) from error
        text = "".join(getattr(block, "text", "") for block in response.content)
        usage = ProviderUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cached_tokens=getattr(response.usage, "cache_read_input_tokens", None),
            total_tokens=response.usage.input_tokens + response.usage.output_tokens,
        )
        return ProviderResponse(
            text=text,
            model=response.model,
            usage=usage,
            request_id=getattr(response, "_request_id", None),
            finish_reason=response.stop_reason,
        )

    async def list_models(self) -> tuple[ProviderModel, ...]:
        try:
            page = await self._client.models.list(limit=100)
        except Exception as error:
            raise _anthropic_error(error) from error
        return tuple(
            ProviderModel(id=item.id, display_name=item.display_name)
            for item in sorted(page.data, key=lambda item: item.id)
        )


def _anthropic_error(error: Exception) -> ProviderError:
    if isinstance(error, anthropic.AuthenticationError):
        return ProviderError(ProviderErrorCategory.AUTHENTICATION, error, retryable=False)
    if isinstance(error, anthropic.RateLimitError):
        return ProviderError(ProviderErrorCategory.RATE_LIMIT, error, retryable=True)
    if isinstance(error, anthropic.APITimeoutError):
        return ProviderError(ProviderErrorCategory.TIMEOUT, error, retryable=True)
    if isinstance(error, anthropic.APIConnectionError):
        return ProviderError(ProviderErrorCategory.NETWORK, error, retryable=True)
    if isinstance(error, anthropic.BadRequestError):
        return ProviderError(ProviderErrorCategory.INVALID_REQUEST, error, retryable=False)
    if isinstance(error, anthropic.InternalServerError):
        return ProviderError(ProviderErrorCategory.PROVIDER_UNAVAILABLE, error, retryable=True)
    return ProviderError(ProviderErrorCategory.UNKNOWN, error, retryable=False)
