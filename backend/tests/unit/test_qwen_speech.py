from __future__ import annotations

import base64
import importlib.util
import io
import wave
from pathlib import Path
from types import ModuleType

import pytest

from koalabattle.production.models import SpeechProviderKind, SpeechRequest
from koalabattle.production.speech.qwen import QwenLocalSpeechProvider


def _wav() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(b"\x00\x00" * 16_000)
    return output.getvalue()


def _qwen_bridge() -> ModuleType:
    path = Path(__file__).resolve().parents[3] / "tools" / "qwen_tts_server.py"
    spec = importlib.util.spec_from_file_location("koalabattle_qwen_bridge", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_qwen_mlx_bridge_rejects_non_apple_silicon(monkeypatch: pytest.MonkeyPatch) -> None:
    qwen_bridge = _qwen_bridge()
    monkeypatch.setattr(qwen_bridge.platform, "system", lambda: "Windows")
    monkeypatch.setattr(qwen_bridge.platform, "machine", lambda: "AMD64")
    assert qwen_bridge._mlx_supported() is False
    with pytest.raises(RuntimeError, match="requires macOS on Apple Silicon"):
        qwen_bridge._load_model()


@pytest.mark.asyncio
async def test_qwen_payload_contains_reference_audio_and_stays_below_root(tmp_path: Path) -> None:
    root = tmp_path / "voices"
    root.mkdir()
    reference = root / "reference.wav"
    reference.write_bytes(_wav())
    provider = QwenLocalSpeechProvider(
        base_url="http://127.0.0.1:1234/v1",
        endpoint="/audio/speech",
        model="Qwen/Qwen3-TTS-12Hz-1.7B-Base",
        api_key=None,
        reference_root=root,
        timeout_seconds=300,
        max_retries=1,
        max_concurrency=1,
    )
    request = SpeechRequest(
        text="A local voice preview.",
        provider=SpeechProviderKind.QWEN_LOCAL,
        model="Qwen/Qwen3-TTS-12Hz-1.7B-Base",
        voice="qwen-clone",
        reference_audio_path="reference.wav",
        reference_text="A local voice preview.",
    )
    payload = provider._payload(request)
    assert payload["model"] == "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
    assert base64.b64decode(payload["reference_audio"]) == reference.read_bytes()
    with pytest.raises(RuntimeError, match="escapes"):
        provider._payload(request.model_copy(update={"reference_audio_path": "../outside.wav"}))
