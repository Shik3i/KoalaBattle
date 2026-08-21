from __future__ import annotations

import logging
from typing import Any

from openai import AsyncOpenAI

from koalabattle.core.models import ProviderUsage

from .base import (
    ProviderCapabilities,
    ProviderModel,
    ProviderRequest,
    ProviderResponse,
    TextDeltaCallback,
)
from .openai import DECISION_SCHEMA, _openai_error

LOGGER = logging.getLogger(__name__)


class OpenAICompatibleProvider:
    name = "openai-compatible"
    capabilities = ProviderCapabilities(
        structured_output=True,
        model_listing=True,
        temperature=True,
        reasoning_control=False,
        usage_reporting=True,
        streaming=False,
    )

    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        self._client = AsyncOpenAI(
            base_url=base_url.rstrip("/") + "/",
            api_key=api_key or "koalabattle-local",
            max_retries=0,
        )

    def _request_arguments(
        self, request: ProviderRequest, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        return arguments

    def _preferred_response_format(self, request: ProviderRequest) -> dict[str, Any] | None:
        return None

    def _fallback_response_formats(
        self, request: ProviderRequest
    ) -> tuple[dict[str, Any] | None, ...]:
        return (
            {
                "type": "json_schema",
                "json_schema": {
                    "name": request.output_schema_name,
                    "strict": True,
                    "schema": request.output_schema or DECISION_SCHEMA,
                },
            },
            None,
        )

    async def generate(
        self,
        request: ProviderRequest,
        *,
        on_text_delta: TextDeltaCallback | None = None,
    ) -> ProviderResponse:
        messages: list[dict[str, str]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})
        common: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_output_tokens,
            "timeout": request.timeout_seconds,
        }
        if request.temperature is not None:
            common["temperature"] = request.temperature
        common = self._request_arguments(request, common)
        preferred_format = self._preferred_response_format(request)
        if preferred_format is not None:
            common["response_format"] = preferred_format

        # 1. Provider-preferred completion. Generic endpoints use no response format;
        # specialized adapters can opt into their documented JSON mode.
        try:
            response = await self._client.chat.completions.create(**common)
            choice = response.choices[0]
            text = choice.message.content or ""
            if text.strip():
                return ProviderResponse(
                    text=text,
                    model=response.model,
                    usage=_provider_usage(response.usage),
                    request_id=response.id,
                    finish_reason=choice.finish_reason,
                )
        except Exception as error:
            LOGGER.warning(
                "OpenAI-compatible standard completion failed; model=%s error_type=%s",
                request.model,
                type(error).__name__,
                exc_info=True,
            )
        else:
            LOGGER.warning(
                "OpenAI-compatible standard completion returned empty text; model=%s; "
                "trying structured response negotiation",
                request.model,
            )
            # Structured negotiation is intentional: an empty standard response
            # cannot yield a legal action.

        # 2. Compatibility fallbacks after an error or empty response.
        for response_format in self._fallback_response_formats(request):
            try:
                arguments = dict(common)
                if response_format is not None:
                    arguments["response_format"] = response_format
                else:
                    arguments.pop("response_format", None)
                response = await self._client.chat.completions.create(**arguments)
                choice = response.choices[0]
                text = choice.message.content or ""
                if text.strip():
                    return ProviderResponse(
                        text=text,
                        model=response.model,
                        usage=_provider_usage(response.usage),
                        request_id=response.id,
                        finish_reason=choice.finish_reason,
                    )
                LOGGER.warning(
                    "OpenAI-compatible completion returned empty text; model=%s response_format=%s",
                    request.model,
                    "json_schema" if response_format is not None else "none",
                )
            except Exception as error:
                if response_format is None:
                    raise _openai_error(error) from error
        raise RuntimeError("OpenAI-compatible response negotiation failed")

    async def _stream_completion(
        self,
        arguments: dict[str, Any],
        on_text_delta: TextDeltaCallback,
    ) -> ProviderResponse:
        stream = await self._client.chat.completions.create(**{**arguments, "stream": True})
        chunks: list[str] = []
        model = str(arguments["model"])
        request_id: str | None = None
        finish_reason: str | None = None
        usage_object: Any = None
        async for chunk in stream:
            model = getattr(chunk, "model", None) or model
            request_id = getattr(chunk, "id", None) or request_id
            usage_object = getattr(chunk, "usage", None) or usage_object
            choices = getattr(chunk, "choices", ())
            if not choices:
                continue
            choice = choices[0]
            finish_reason = getattr(choice, "finish_reason", None) or finish_reason
            delta = getattr(choice, "delta", None)
            text = getattr(delta, "content", None) or ""
            if text:
                chunks.append(text)
                await on_text_delta(text)
        return ProviderResponse(
            text="".join(chunks),
            model=model,
            usage=_provider_usage(usage_object),
            request_id=request_id,
            finish_reason=finish_reason,
        )

    async def list_models(self) -> tuple[ProviderModel, ...]:
        try:
            models = await self._client.models.list()
        except Exception as error:
            raise _openai_error(error) from error
        return tuple(
            ProviderModel(id=item.id) for item in sorted(models.data, key=lambda item: item.id)
        )


class DeepSeekProvider(OpenAICompatibleProvider):
    name = "deepseek"
    capabilities = ProviderCapabilities(
        structured_output=True,
        model_listing=True,
        temperature=False,
        reasoning_control=True,
        usage_reporting=True,
        streaming=False,
    )

    def __init__(self, api_key: str) -> None:
        super().__init__("https://api.deepseek.com", api_key)

    def _request_arguments(
        self, request: ProviderRequest, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        prepared = dict(arguments)
        # DeepSeek V4 enables thinking by default. It ignores temperature in thinking mode,
        # so omit that misleading control and map KoalaBattle's portable effort levels to the
        # two values the current OpenAI-compatible DeepSeek API accepts.
        prepared.pop("temperature", None)
        prepared["extra_body"] = {"thinking": {"type": "enabled"}}
        if request.reasoning_effort is not None:
            prepared["reasoning_effort"] = (
                "max" if request.reasoning_effort == "max" else "high"
            )
        return prepared

    def _preferred_response_format(self, request: ProviderRequest) -> dict[str, Any]:
        # DeepSeek documents json_object rather than OpenAI's json_schema format.
        return {"type": "json_object"}

    def _fallback_response_formats(
        self, request: ProviderRequest
    ) -> tuple[dict[str, Any] | None, ...]:
        return (None,)


def _provider_usage(usage_object: Any) -> ProviderUsage | None:
    if usage_object is None:
        return None
    details = getattr(usage_object, "prompt_tokens_details", None)
    return ProviderUsage(
        input_tokens=getattr(usage_object, "prompt_tokens", None),
        output_tokens=getattr(usage_object, "completion_tokens", None),
        cached_tokens=getattr(details, "cached_tokens", None),
        total_tokens=getattr(usage_object, "total_tokens", None),
    )
