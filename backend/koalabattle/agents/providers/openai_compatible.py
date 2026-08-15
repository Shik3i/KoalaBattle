from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI, BadRequestError

from koalabattle.core.models import ProviderUsage

from .base import ProviderCapabilities, ProviderModel, ProviderRequest, ProviderResponse
from .openai import DECISION_SCHEMA, _openai_error


class OpenAICompatibleProvider:
    name = "openai-compatible"
    capabilities = ProviderCapabilities(
        structured_output=True,
        model_listing=True,
        temperature=True,
        reasoning_control=False,
        usage_reporting=True,
    )

    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        self._client = AsyncOpenAI(
            base_url=base_url.rstrip("/") + "/",
            api_key=api_key or "koalabattle-local",
            max_retries=0,
        )

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        common: dict[str, Any] = {
            "model": request.model,
            "messages": [{"role": "user", "content": request.prompt}],
            "max_tokens": request.max_output_tokens,
            "timeout": request.timeout_seconds,
        }
        if request.temperature is not None:
            common["temperature"] = request.temperature
        response = None
        formats: tuple[dict[str, Any] | None, ...] = (
            {
                "type": "json_schema",
                "json_schema": {
                    "name": request.output_schema_name,
                    "strict": True,
                    "schema": request.output_schema or DECISION_SCHEMA,
                },
            },
            {"type": "json_object"},
            None,
        )
        for response_format in formats:
            try:
                arguments = dict(common)
                if response_format is not None:
                    arguments["response_format"] = response_format
                response = await self._client.chat.completions.create(**arguments)
                break
            except BadRequestError as error:
                if response_format is None:
                    raise _openai_error(error) from error
            except Exception as error:
                raise _openai_error(error) from error
        if response is None:
            raise RuntimeError("OpenAI-compatible response negotiation failed")
        choice = response.choices[0]
        usage_object = response.usage
        details = getattr(usage_object, "prompt_tokens_details", None)
        usage = ProviderUsage(
            input_tokens=getattr(usage_object, "prompt_tokens", None),
            output_tokens=getattr(usage_object, "completion_tokens", None),
            cached_tokens=getattr(details, "cached_tokens", None),
            total_tokens=getattr(usage_object, "total_tokens", None),
        )
        return ProviderResponse(
            text=choice.message.content or "",
            model=response.model,
            usage=usage,
            request_id=response.id,
            finish_reason=choice.finish_reason,
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

    def __init__(self, api_key: str) -> None:
        super().__init__("https://api.deepseek.com", api_key)
