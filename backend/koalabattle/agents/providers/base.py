from __future__ import annotations

import re
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from koalabattle.core.models import ProviderErrorCategory, ProviderUsage


class ProviderCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    structured_output: bool = False
    model_listing: bool = False
    temperature: bool = False
    reasoning_control: bool = False
    usage_reporting: bool = False


class ProviderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt: str
    model: str
    timeout_seconds: float = Field(ge=1, le=600)
    max_output_tokens: int = Field(ge=32, le=8192)
    temperature: float | None = Field(default=None, ge=0, le=2)
    reasoning_effort: str | None = None
    output_schema_name: str = Field(default="koalabattle_decision", pattern=r"^[a-z0-9_]+$")
    output_schema: dict[str, Any] = Field(default_factory=dict)


class ProviderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(max_length=50_000)
    model: str
    usage: ProviderUsage | None = None
    request_id: str | None = None
    finish_reason: str | None = None


class ProviderModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    display_name: str | None = None


class ProviderError(Exception):
    def __init__(self, category: ProviderErrorCategory, detail: object, *, retryable: bool) -> None:
        self.category = category
        self.detail = safe_error_detail(detail)
        self.retryable = retryable
        super().__init__(self.detail)


class LLMProvider(Protocol):
    name: str
    capabilities: ProviderCapabilities

    async def generate(self, request: ProviderRequest) -> ProviderResponse: ...

    async def list_models(self) -> tuple[ProviderModel, ...]: ...


_BEARER = re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]+")
_KEY = re.compile(r"(?i)\b(?:sk|key|token)[-_][a-z0-9_-]{8,}\b")


def safe_error_detail(value: object) -> str:
    detail = str(value).replace("\r", " ").replace("\n", " ")[:500]
    detail = _BEARER.sub("Bearer [REDACTED]", detail)
    return _KEY.sub("[REDACTED]", detail)
