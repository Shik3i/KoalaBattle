from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import SpeechProviderStatus, SpeechRequest


class SpeechProvider(ABC):
    @abstractmethod
    def status(self) -> SpeechProviderStatus: ...

    @abstractmethod
    async def synthesize(self, request: SpeechRequest) -> bytes: ...
