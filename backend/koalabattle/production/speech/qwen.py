from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..models import SpeechProviderKind, SpeechProviderStatus, SpeechRequest
from .base import SpeechProvider


class QwenLocalSpeechProvider(SpeechProvider):
    """Local Qwen3-TTS adapter with an OpenAI-shaped HTTP boundary.

    LM Studio versions and Qwen TTS bridges expose slightly different payloads. The adapter
    keeps the endpoint configurable and accepts either raw audio bytes or a JSON base64 audio
    response. Reference audio is read only below the configured local voice root.
    """

    def __init__(
        self,
        *,
        base_url: str,
        endpoint: str,
        model: str,
        api_key: str | None,
        reference_root: Path,
        timeout_seconds: float,
        max_retries: int,
        max_concurrency: int,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        self.model = model
        self.api_key = api_key
        self.reference_root = reference_root.resolve()
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))

    def status(self) -> SpeechProviderStatus:
        configured = bool(self.base_url and self.endpoint and self.model)
        return SpeechProviderStatus(
            id=SpeechProviderKind.QWEN_LOCAL,
            configured=configured,
            available=configured,
            paid=False,
            detail=(
                "Local Qwen3-TTS endpoint configured; capability is checked on synthesis."
                if configured
                else "Configure a local Qwen3-TTS endpoint and model."
            ),
            supports_timestamps=False,
            voices=("qwen-clone",),
        )

    async def synthesize(self, request: SpeechRequest) -> bytes:
        if not self.status().available:
            raise RuntimeError("Local Qwen3-TTS is not configured.")
        payload = await asyncio.to_thread(self._payload, request)
        last_error: Exception | None = None
        async with self._semaphore:
            for attempt in range(self.max_retries + 1):
                try:
                    return await asyncio.wait_for(
                        asyncio.to_thread(self._request, payload), timeout=self.timeout_seconds
                    )
                except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as error:
                    last_error = error
                    if attempt >= self.max_retries:
                        break
                    await asyncio.sleep(min(2.0 * (attempt + 1), 5.0))
        raise RuntimeError(f"Local Qwen3-TTS failed after retry: {last_error}") from last_error

    def _payload(self, request: SpeechRequest) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": request.model or self.model,
            "input": request.text,
            "voice": request.voice,
            "response_format": request.format,
            "speed": request.speed,
        }
        if request.language:
            payload["language"] = request.language
        if request.instructions:
            payload["instructions"] = request.instructions
        if request.reference_audio_path:
            path = self._reference_path(request.reference_audio_path)
            if not path.is_file():
                raise RuntimeError(f"Qwen reference audio does not exist: {path}")
            content = path.read_bytes()
            if not content or len(content) > 16 * 1024 * 1024:
                raise RuntimeError("Qwen reference audio is empty or exceeds 16 MiB.")
            payload["reference_audio"] = base64.b64encode(content).decode("ascii")
        if request.reference_text:
            payload["reference_text"] = request.reference_text
        if request.x_vector_only_mode:
            payload["x_vector_only_mode"] = True
        return payload

    def _reference_path(self, relative_path: str) -> Path:
        candidate = (self.reference_root / relative_path).resolve()
        if self.reference_root not in candidate.parents:
            raise RuntimeError("Qwen reference audio path escapes the configured voice root.")
        return candidate

    def _request(self, payload: dict[str, object]) -> bytes:
        headers = {"Content-Type": "application/json", "Accept": "audio/wav, application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(
            f"{self.base_url}{self.endpoint}",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                body = bytes(response.read())
                content_type = response.headers.get_content_type()
        except HTTPError as error:
            detail = error.read().decode(errors="replace")[:800]
            raise RuntimeError(f"Qwen TTS HTTP {error.code}: {detail}") from error
        if content_type == "application/json" or body[:1] in {b"{", b"["}:
            try:
                document = json.loads(body)
                encoded = document.get("audio") or document.get("data")
                if not isinstance(encoded, str):
                    raise ValueError("JSON response has no audio/data base64 field")
                return base64.b64decode(encoded)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                raise RuntimeError("Qwen TTS returned invalid JSON audio data.") from error
        return body
