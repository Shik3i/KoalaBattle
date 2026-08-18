"""Small local MLX-Audio bridge for Qwen3-TTS.

The LM Studio model library can contain the MLX checkpoint while the LM Studio inference
runtime still rejects its ``qwen3_tts`` architecture. This bridge loads the same MLX model
through mlx-audio and exposes the narrow endpoint KoalaBattle needs.

Install on Apple Silicon in a dedicated environment::

    python -m pip install mlx-audio fastapi uvicorn soundfile numpy
    python tools/qwen_tts_server.py
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import io
import os
import platform
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

MODEL_ID = os.getenv(
    "KOALABATTLE_QWEN_TTS_MODEL",
    "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
)
HOST = os.getenv("KOALABATTLE_QWEN_TTS_HOST", "127.0.0.1")
PORT = int(os.getenv("KOALABATTLE_QWEN_TTS_PORT", "8890"))

app = FastAPI(title="KoalaBattle Qwen3-TTS bridge", version="1.0")
_model: Any = None
_model_lock = asyncio.Lock()
_generation_lock = asyncio.Lock()


def _mlx_supported() -> bool:
    return platform.system() == "Darwin" and platform.machine().lower() in {
        "arm64",
        "aarch64",
    }


class SpeechRequest(BaseModel):
    model: str = MODEL_ID
    input: str = Field(min_length=1, max_length=4096)
    voice: str = "Chelsie"
    response_format: str = "wav"
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    language: str | None = None
    instructions: str | None = None
    reference_audio: str | None = None
    reference_text: str | None = None
    x_vector_only_mode: bool = False


def _load_model() -> Any:
    global _model
    if not _mlx_supported():
        raise RuntimeError(
            "The Qwen MLX bridge requires macOS on Apple Silicon; configure a Windows-native "
            "or OpenAI-compatible TTS endpoint instead."
        )
    if _model is None:
        try:
            from mlx_audio.tts.utils import load_model
        except ModuleNotFoundError as error:
            raise RuntimeError(
                "mlx-audio is not installed; use tools/requirements-qwen-tts.txt on Apple Silicon."
            ) from error

        _model = load_model(MODEL_ID)
    return _model


def _audio_bytes(result: Any, sample_rate: int) -> bytes:
    import numpy as np
    import soundfile as sf

    samples = np.asarray(result.audio, dtype=np.float32)
    output = io.BytesIO()
    sf.write(output, samples, sample_rate, format="WAV", subtype="PCM_16")
    return output.getvalue()


def _language_code(language: str | None) -> str:
    if not language:
        return "auto"
    normalized = language.strip().lower().replace("_", "-")
    return {
        "en": "English",
        "en-us": "English",
        "en-gb": "English",
        "de": "German",
        "de-de": "German",
        "fr": "French",
        "fr-fr": "French",
        "es": "Spanish",
        "es-es": "Spanish",
        "ja": "Japanese",
        "ko": "Korean",
        "zh": "Chinese",
        "zh-cn": "Chinese",
    }.get(normalized, language)


async def _generate(payload: SpeechRequest) -> bytes:
    reference_path: Path | None = None
    try:
        if payload.reference_audio:
            try:
                reference = base64.b64decode(payload.reference_audio, validate=True)
            except (binascii.Error, ValueError) as error:
                raise HTTPException(status_code=422, detail="invalid reference_audio base64") from error
            descriptor, temporary = tempfile.mkstemp(prefix="koalabattle-qwen-reference-", suffix=".wav")
            os.close(descriptor)
            reference_path = Path(temporary)
            reference_path.write_bytes(reference)
        async with _model_lock:
            model = await asyncio.to_thread(_load_model)
        kwargs: dict[str, object] = {
            "text": payload.input,
            "lang_code": _language_code(payload.language),
            "speed": payload.speed,
        }
        if payload.instructions:
            kwargs["instruct"] = payload.instructions
        if reference_path is not None:
            kwargs.update(
                {
                    "ref_audio": str(reference_path),
                }
            )
            if payload.reference_text is not None:
                kwargs["ref_text"] = payload.reference_text
        else:
            kwargs["voice"] = payload.voice
        async with _generation_lock:
            results = await asyncio.to_thread(lambda: list(model.generate(**kwargs)))
        if not results:
            raise HTTPException(status_code=502, detail="Qwen3-TTS produced no audio")
        return _audio_bytes(results[-1], int(getattr(model, "sample_rate", 24_000)))
    finally:
        if reference_path is not None:
            reference_path.unlink(missing_ok=True)


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    return {
        "ok": True,
        "model": MODEL_ID,
        "loaded": _model is not None,
        "mlx_supported": _mlx_supported(),
    }


@app.get("/v1/models")
async def models() -> dict[str, object]:
    return {"object": "list", "data": [{"id": MODEL_ID, "object": "model", "owned_by": "local"}]}


@app.post("/v1/audio/speech")
async def speech(payload: SpeechRequest) -> Response:
    if payload.model != MODEL_ID:
        raise HTTPException(status_code=404, detail=f"unknown local model: {payload.model}")
    if payload.response_format != "wav":
        raise HTTPException(status_code=422, detail="the local bridge only returns WAV")
    try:
        audio = await _generate(payload)
    except HTTPException:
        raise
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return Response(content=audio, media_type="audio/wav")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
