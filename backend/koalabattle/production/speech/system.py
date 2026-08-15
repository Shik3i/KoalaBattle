from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

from ..models import SpeechProviderKind, SpeechProviderStatus, SpeechRequest
from .base import SpeechProvider


class SystemSpeechProvider(SpeechProvider):
    """Zero-cost local speech through an installed OS command."""

    def __init__(self) -> None:
        self.say = shutil.which("say")
        self.espeak = shutil.which("espeak-ng") or shutil.which("espeak")

    def status(self) -> SpeechProviderStatus:
        engine = "espeak-ng" if self.espeak else "macOS say" if self.say else "unavailable"
        return SpeechProviderStatus(
            id=SpeechProviderKind.SYSTEM,
            configured=True,
            available=bool(self.say or self.espeak),
            paid=False,
            detail=f"Local system speech engine: {engine}.",
            voices=("system-default",),
        )

    async def synthesize(self, request: SpeechRequest) -> bytes:
        if not self.say and not self.espeak:
            raise RuntimeError("No local speech engine found; install espeak-ng or use macOS say.")
        with tempfile.TemporaryDirectory(prefix="koalabattle-speech-") as directory:
            output = Path(directory) / "speech.wav"
            if self.espeak:
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
            else:
                assert self.say is not None
                command = [
                    self.say,
                    "-o",
                    str(output),
                    "--file-format=WAVE",
                    "--data-format=LEI16@24000",
                    "-r",
                    str(max(80, min(400, round(180 * request.speed)))),
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
            return output.read_bytes()
