from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

from ..models import SpeechRequest


@dataclass(frozen=True)
class ValidatedAudio:
    path: Path
    byte_size: int
    duration_ms: int
    content_sha256: str


def speech_cache_key(request: SpeechRequest) -> str:
    canonical = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class SpeechCache:
    def __init__(self, root: Path, *, max_bytes: int = 16 * 1024 * 1024) -> None:
        self.root = root.resolve()
        self.max_bytes = max_bytes

    def path_for(self, cache_key: str) -> Path:
        if len(cache_key) != 64 or any(char not in "0123456789abcdef" for char in cache_key):
            raise ValueError("invalid speech cache key")
        path = (self.root / cache_key[:2] / f"{cache_key}.wav").resolve()
        if self.root not in path.parents:
            raise ValueError("speech cache path escapes configured root")
        return path

    def validate(self, cache_key: str) -> ValidatedAudio | None:
        path = self.path_for(cache_key)
        if not path.is_file():
            return None
        try:
            return self._validate_bytes(path.read_bytes(), path)
        except (OSError, EOFError, wave.Error, ValueError):
            return None

    def store(self, cache_key: str, content: bytes) -> ValidatedAudio:
        path = self.path_for(cache_key)
        validated = self._validate_bytes(content, path)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{cache_key}-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
        return validated

    def _validate_bytes(self, content: bytes, path: Path) -> ValidatedAudio:
        if not content or len(content) > self.max_bytes:
            raise ValueError("speech audio payload is empty or exceeds the 16 MiB limit")
        with wave.open(io.BytesIO(content), "rb") as audio:
            if audio.getnchannels() not in (1, 2) or audio.getsampwidth() not in (1, 2, 3, 4):
                raise ValueError("unsupported WAV channel or sample width")
            rate = audio.getframerate()
            frames = audio.getnframes()
            if rate <= 0 or frames <= 0:
                raise ValueError("invalid WAV timing metadata")
            duration_ms = max(1, round(frames * 1000 / rate))
        return ValidatedAudio(
            path=path,
            byte_size=len(content),
            duration_ms=duration_ms,
            content_sha256=hashlib.sha256(content).hexdigest(),
        )
