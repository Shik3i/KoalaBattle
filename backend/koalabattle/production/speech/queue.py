from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


class SpeechGenerationQueue:
    def __init__(self, concurrency: int) -> None:
        self._semaphore = asyncio.Semaphore(concurrency)
        self._inflight: dict[str, asyncio.Task[bytes]] = {}
        self._lock = asyncio.Lock()

    async def generate(self, key: str, work: Callable[[], Awaitable[bytes]]) -> bytes:
        async with self._lock:
            task = self._inflight.get(key)
            if task is None:
                task = asyncio.create_task(self._run(work), name=f"speech:{key[:12]}")
                self._inflight[key] = task
                task.add_done_callback(lambda completed: self._discard(key, completed))
        return await asyncio.shield(task)

    async def cancel(self, key: str) -> bool:
        async with self._lock:
            task = self._inflight.get(key)
            if task is None:
                return False
            task.cancel()
            return True

    async def close(self) -> None:
        async with self._lock:
            tasks = tuple(self._inflight.values())
            for task in tasks:
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(self, work: Callable[[], Awaitable[bytes]]) -> bytes:
        async with self._semaphore:
            return await work()

    def _discard(self, key: str, completed: asyncio.Task[bytes]) -> None:
        if self._inflight.get(key) is completed:
            self._inflight.pop(key, None)
