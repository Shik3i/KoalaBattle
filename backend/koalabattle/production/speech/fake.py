from __future__ import annotations

import io
import math
import struct
import wave

from ..models import SpeechProviderKind, SpeechProviderStatus, SpeechRequest
from .base import SpeechProvider


class FakeSpeechProvider(SpeechProvider):
    """Deterministic WAV tones for zero-network tests and previews."""

    def status(self) -> SpeechProviderStatus:
        return SpeechProviderStatus(
            id=SpeechProviderKind.FAKE,
            configured=True,
            available=True,
            paid=False,
            detail="Deterministic synthetic test audio; not intended as a human voice.",
            voices=("test-a", "test-b"),
        )

    async def synthesize(self, request: SpeechRequest) -> bytes:
        sample_rate = 24_000
        duration_ms = max(240, min(8_000, len(request.text) * 32))
        frames = round(sample_rate * duration_ms / 1000)
        frequency = 360 + (sum(request.voice.encode()) % 220)
        output = io.BytesIO()
        with wave.open(output, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(sample_rate)
            samples = bytearray()
            for index in range(frames):
                envelope = min(1.0, index / 240, (frames - index) / 240)
                phase = 2 * math.pi * frequency * index / sample_rate
                value = int(4000 * envelope * math.sin(phase))
                samples.extend(struct.pack("<h", value))
            audio.writeframes(bytes(samples))
        return output.getvalue()
