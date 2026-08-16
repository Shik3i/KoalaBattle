from __future__ import annotations

from google import genai
from google.genai import errors, types

from koalabattle.core.models import ProviderErrorCategory, ProviderUsage

from .base import (
    ProviderCapabilities,
    ProviderError,
    ProviderModel,
    ProviderRequest,
    ProviderResponse,
)
from .openai import DECISION_SCHEMA


class GeminiProvider:
    name = "gemini"
    capabilities = ProviderCapabilities(
        structured_output=True,
        model_listing=True,
        temperature=True,
        reasoning_control=False,
        usage_reporting=True,
    )

    def __init__(self, api_key: str) -> None:
        self._client = genai.Client(api_key=api_key)

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=request.output_schema or DECISION_SCHEMA,
            max_output_tokens=request.max_output_tokens,
            temperature=request.temperature,
            http_options=types.HttpOptions(timeout=int(request.timeout_seconds * 1000)),
            system_instruction=request.system_prompt or None,
        )
        try:
            response = await self._client.aio.models.generate_content(
                model=request.model,
                contents=request.prompt,
                config=config,
            )
        except Exception as error:
            raise _gemini_error(error) from error
        usage_object = response.usage_metadata
        usage = ProviderUsage(
            input_tokens=getattr(usage_object, "prompt_token_count", None),
            output_tokens=getattr(usage_object, "candidates_token_count", None),
            cached_tokens=getattr(usage_object, "cached_content_token_count", None),
            total_tokens=getattr(usage_object, "total_token_count", None),
        )
        candidate = response.candidates[0] if response.candidates else None
        return ProviderResponse(
            text=response.text or "",
            model=request.model,
            usage=usage,
            finish_reason=str(getattr(candidate, "finish_reason", "")) or None,
        )

    async def list_models(self) -> tuple[ProviderModel, ...]:
        try:
            pager = await self._client.aio.models.list()
            models = [item async for item in pager]
        except Exception as error:
            raise _gemini_error(error) from error
        return tuple(
            ProviderModel(
                id=(item.name or "").removeprefix("models/"),
                display_name=item.display_name,
            )
            for item in sorted(models, key=lambda item: item.name or "")
            if item.name
        )


def _gemini_error(error: Exception) -> ProviderError:
    if isinstance(error, errors.APIError):
        code = getattr(error, "code", 0)
        if code in {401, 403}:
            category, retryable = ProviderErrorCategory.AUTHENTICATION, False
        elif code == 429:
            category, retryable = ProviderErrorCategory.RATE_LIMIT, True
        elif code in {408, 504}:
            category, retryable = ProviderErrorCategory.TIMEOUT, True
        elif code in {500, 502, 503}:
            category, retryable = ProviderErrorCategory.PROVIDER_UNAVAILABLE, True
        elif code in {400, 404, 422}:
            category, retryable = ProviderErrorCategory.INVALID_REQUEST, False
        else:
            category, retryable = ProviderErrorCategory.UNKNOWN, False
        return ProviderError(category, error, retryable=retryable)
    if isinstance(error, TimeoutError):
        return ProviderError(ProviderErrorCategory.TIMEOUT, error, retryable=True)
    return ProviderError(ProviderErrorCategory.NETWORK, error, retryable=True)
