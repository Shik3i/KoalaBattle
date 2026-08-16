from __future__ import annotations

import asyncio
import shutil
import tempfile
import wave
from pathlib import Path

import edge_tts

from ..models import SpeechProviderKind, SpeechProviderStatus, SpeechRequest
from .base import SpeechProvider


class SystemSpeechProvider(SpeechProvider):
    """Free Edge neural speech with an explicit basic offline fallback."""

    def __init__(self, *, edge_enabled: bool = True, edge_voices: tuple[str, ...] = ()) -> None:
        self.edge_enabled = edge_enabled
        self.edge_voices = edge_voices
        self.say = shutil.which("say")
        self.espeak = shutil.which("espeak-ng") or shutil.which("espeak")
        self.ffmpeg = shutil.which("ffmpeg")

    def status(self) -> SpeechProviderStatus:
        local = (
            "macOS say"
            if self.say and self.ffmpeg
            else "espeak-ng"
            if self.espeak
            else "unavailable"
        )
        local_ready = bool((self.say and self.ffmpeg) or self.espeak)
        edge_ready = self.edge_enabled and bool(self.edge_voices) and bool(self.ffmpeg)
        detail = (
            f"Free Edge neural speech (online) is ready; basic offline fallback: {local}."
            if edge_ready
            else f"Edge neural speech is disabled or FFmpeg is missing; offline engine: {local}."
        )
        return SpeechProviderStatus(
            id=SpeechProviderKind.SYSTEM,
            configured=True,
            available=edge_ready or local_ready,
            paid=False,
            detail=detail,
            voices=(*self.edge_voices, "system-default") if edge_ready else ("system-default",),
        )

    async def synthesize(self, request: SpeechRequest) -> bytes:
        if request.voice in self.edge_voices:
            return await self._synthesize_edge(request)
        return await self._synthesize_local(request)

    async def _synthesize_edge(self, request: SpeechRequest) -> bytes:
        if not self.edge_enabled:
            raise RuntimeError("Edge neural speech is disabled by configuration.")
        if not self.ffmpeg:
            raise RuntimeError("Edge neural speech requires FFmpeg to convert its audio stream.")
        with tempfile.TemporaryDirectory(prefix="koalabattle-edge-speech-") as directory:
            compressed = Path(directory) / "speech.mp3"
            output = Path(directory) / "speech.wav"
            rate = max(-50, min(100, round((request.speed - 1) * 100)))
            try:
                async with asyncio.timeout(45):
                    await edge_tts.Communicate(
                        request.text,
                        request.voice,
                        rate=f"{rate:+d}%",
                    ).save(str(compressed))
            except (TimeoutError, edge_tts.exceptions.EdgeTTSException) as error:
                raise RuntimeError(
                    "Edge neural speech is temporarily unavailable; check network access or "
                    "select an Offline System voice."
                ) from error
            await self._convert_to_wav(compressed, output, label="Edge speech")
            return output.read_bytes()

    async def _synthesize_local(self, request: SpeechRequest) -> bytes:
        if not ((self.say and self.ffmpeg) or self.espeak):
            raise RuntimeError("No local speech engine found; install espeak-ng or use macOS say.")
        with tempfile.TemporaryDirectory(prefix="koalabattle-speech-") as directory:
            output = Path(directory) / "speech.wav"
            if self.say and self.ffmpeg:
                system_audio = Path(directory) / "speech.aiff"
                command = [
                    self.say,
                    "-o",
                    str(system_audio),
                    "-r",
                    str(max(80, min(400, round(180 * request.speed)))),
                ]
                if request.voice != "system-default":
                    command.extend(["-v", request.voice])
                command.append(request.text)
            else:
                assert self.espeak is not None
                command = [
                    self.espeak,
                    "-w",
                    str(output),
                    "-s",
                    str(max(80, min(450, round(175 * request.speed)))),
                ]
                if request.voice != "system-default":
                    command.extend(["-v", request.voice])
                command.append(request.text)
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()
            if process.returncode != 0:
                detail = stderr.decode(errors="replace")[:500]
                raise RuntimeError(f"System speech failed ({process.returncode}): {detail}")
            if self.say and self.ffmpeg:
                await self._convert_to_wav(system_audio, output, label="System speech")
                if not self._contains_audio(output):
                    if not self.espeak:
                        raise RuntimeError("macOS say produced an empty audio stream.")
                    fallback = [
                        self.espeak,
                        "-w",
                        str(output),
                        "-s",
                        str(max(80, min(450, round(175 * request.speed)))),
                        request.text,
                    ]
                    process = await asyncio.create_subprocess_exec(
                        *fallback,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    _, stderr = await process.communicate()
                    if process.returncode != 0:
                        detail = stderr.decode(errors="replace")[:500]
                        raise RuntimeError(
                            f"Offline speech fallback failed ({process.returncode}): {detail}"
                        )
            return output.read_bytes()

    @staticmethod
    def _contains_audio(path: Path) -> bool:
        try:
            with wave.open(str(path), "rb") as audio:
                return audio.getframerate() > 0 and audio.getnframes() > 0
        except (EOFError, wave.Error):
            return False

    async def _convert_to_wav(self, source: Path, output: Path, *, label: str) -> None:
        assert self.ffmpeg is not None
        process = await asyncio.create_subprocess_exec(
            self.ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-ac",
            "1",
            "-ar",
            "24000",
            "-c:a",
            "pcm_s16le",
            str(output),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            detail = stderr.decode(errors="replace")[:500]
            raise RuntimeError(f"{label} conversion failed ({process.returncode}): {detail}")
