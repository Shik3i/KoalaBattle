from __future__ import annotations

from openai import AsyncOpenAI

from ..models import SpeechProviderKind, SpeechProviderStatus, SpeechRequest
from .base import SpeechProvider


class OpenAISpeechProvider(SpeechProvider):
    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str | None = None,
        compatible: bool = False,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.compatible = compatible

    def status(self) -> SpeechProviderStatus:
        kind = (
            SpeechProviderKind.OPENAI_COMPATIBLE if self.compatible else SpeechProviderKind.OPENAI
        )
        return SpeechProviderStatus(
            id=kind,
            configured=bool(self.api_key and (self.base_url or not self.compatible)),
            available=bool(self.api_key and (self.base_url or not self.compatible)),
            paid=True,
            detail=(
                "Configured OpenAI-compatible /v1/audio/speech endpoint."
                if self.compatible
                else "OpenAI speech is optional and may incur provider charges."
            ),
            supports_timestamps=False,
            voices=("alloy", "ash", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer"),
        )

    async def synthesize(self, request: SpeechRequest) -> bytes:
        if not self.status().available:
            raise RuntimeError(f"Speech provider {request.provider.value} is not configured.")
        client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        response = await client.audio.speech.create(
            model=request.model,
            voice=request.voice,
            input=request.text,
            instructions=request.instructions or "",
            response_format="wav",
            speed=request.speed,
        )
        return response.content
