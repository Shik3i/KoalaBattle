from __future__ import annotations

import os
from pathlib import Path

import pytest

from koalabattle.production.models import SpeechProviderKind, SpeechRequest
from koalabattle.production.speech.cache import SpeechCache, speech_cache_key
from koalabattle.production.speech.system import SystemSpeechProvider


@pytest.mark.integration
@pytest.mark.asyncio
async def test_edge_neural_speech_produces_valid_pcm_wav(tmp_path: Path) -> None:
    if os.getenv("KOALABATTLE_RUN_EDGE_TTS_TEST") != "1":
        pytest.skip("set KOALABATTLE_RUN_EDGE_TTS_TEST=1 to run online Edge neural speech")
    voice = "en-US-EmmaMultilingualNeural"
    provider = SystemSpeechProvider(edge_voices=(voice,))
    request = SpeechRequest(
        text="A precise switch keeps the battle under control.",
        provider=SpeechProviderKind.SYSTEM,
        model="edge-tts-7.2.8",
        voice=voice,
        speed=1.02,
        language="en-US",
    )
    content = await provider.synthesize(request)
    stored = SpeechCache(tmp_path / "edge-audio").store(speech_cache_key(request), content)
    assert stored.duration_ms > 500
    assert content[:4] == b"RIFF"
