"""Windows/CUDA bridge for Qwen3-TTS, exposing the same narrow endpoint as
``qwen_tts_server.py`` (the Apple-Silicon MLX bridge) so KoalaBattle's ``qwen-local``
speech provider needs no changes to point at either one.

The MLX bridge cannot run on Windows: LM Studio can show the ``qwen3_tts`` architecture
in its library while refusing to load it, and mlx-audio itself only supports Apple
Silicon. This bridge instead loads the official ``Qwen/Qwen3-TTS-12Hz-1.7B-Base``
checkpoint through the ``qwen-tts`` package on an NVIDIA GPU.

Install in a dedicated environment (see tools/requirements-qwen-tts-windows.txt)::

    python -m venv tools/.venv-qwen-tts
    tools/.venv-qwen-tts/Scripts/python.exe -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
    tools/.venv-qwen-tts/Scripts/python.exe -m pip install -r tools/requirements-qwen-tts-windows.txt
    tools/.venv-qwen-tts/Scripts/python.exe tools/qwen_tts_server_windows.py

The Base model only does voice cloning (a reference WAV plus its transcript); it has no
built-in preset voices, so requests without ``reference_audio`` are rejected with 422.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import io
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

MODEL_ID = os.getenv("KOALABATTLE_QWEN_TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-Base")
DEVICE = os.getenv("KOALABATTLE_QWEN_TTS_DEVICE", "cuda:0")
ATTN_IMPLEMENTATION = os.getenv("KOALABATTLE_QWEN_TTS_ATTN", "sdpa")
HOST = os.getenv("KOALABATTLE_QWEN_TTS_HOST", "127.0.0.1")
PORT = int(os.getenv("KOALABATTLE_QWEN_TTS_PORT", "8890"))

app = FastAPI(title="KoalaBattle Qwen3-TTS Windows bridge", version="1.0")
_model: Any = None
_model_lock = asyncio.Lock()
_generation_lock = asyncio.Lock()


def _cuda_supported() -> bool:
    try:
        import torch

        return torch.cuda.is_available()
    except ModuleNotFoundError:
        return False


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
    if not _cuda_supported():
        raise RuntimeError(
            "No CUDA GPU is visible to PyTorch; install the CUDA build of torch "
            "(see tools/requirements-qwen-tts-windows.txt) or configure a different "
            "TTS endpoint."
        )
    if _model is None:
        import torch

        try:
            from qwen_tts import Qwen3TTSModel
        except ModuleNotFoundError as error:
            raise RuntimeError(
                "qwen-tts is not installed; run "
                "tools/.venv-qwen-tts/Scripts/python.exe -m pip install -r "
                "tools/requirements-qwen-tts-windows.txt"
            ) from error

        _model = Qwen3TTSModel.from_pretrained(
            MODEL_ID,
            device_map=DEVICE,
            dtype=torch.bfloat16,
            attn_implementation=ATTN_IMPLEMENTATION,
        )
    return _model


def _audio_bytes(samples: Any, sample_rate: int) -> bytes:
    import numpy as np
    import soundfile as sf

    output = io.BytesIO()
    sf.write(output, np.asarray(samples, dtype=np.float32), sample_rate, format="WAV", subtype="PCM_16")
    return output.getvalue()


def _language_code(language: str | None) -> str:
    if not language:
        return "Auto"
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
    if not payload.reference_audio:
        raise HTTPException(
            status_code=422,
            detail="Qwen3-TTS-12Hz-1.7B-Base only clones from reference audio; no built-in "
            "preset voices are available.",
        )
    try:
        reference = base64.b64decode(payload.reference_audio, validate=True)
    except (binascii.Error, ValueError) as error:
        raise HTTPException(status_code=422, detail="invalid reference_audio base64") from error
    descriptor, temporary = tempfile.mkstemp(prefix="koalabattle-qwen-reference-", suffix=".wav")
    os.close(descriptor)
    reference_path = Path(temporary)
    reference_path.write_bytes(reference)
    try:
        async with _model_lock:
            model = await asyncio.to_thread(_load_model)
        async with _generation_lock:
            wavs, sample_rate = await asyncio.to_thread(
                lambda: model.generate_voice_clone(
                    text=payload.input,
                    language=_language_code(payload.language),
                    ref_audio=str(reference_path),
                    ref_text=payload.reference_text or "",
                )
            )
        if not wavs:
            raise HTTPException(status_code=502, detail="Qwen3-TTS produced no audio")
        return _audio_bytes(wavs[0], sample_rate)
    finally:
        reference_path.unlink(missing_ok=True)


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    return {
        "ok": True,
        "model": MODEL_ID,
        "loaded": _model is not None,
        "cuda_supported": _cuda_supported(),
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
