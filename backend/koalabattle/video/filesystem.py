from __future__ import annotations

import os
import re
import shutil
import unicodedata
from hashlib import sha256
from pathlib import Path
from uuid import UUID

_SAFE = re.compile(r"[^a-z0-9._-]+")


def safe_stem(value: str, *, fallback: str = "koalabattle-export") -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    stem = _SAFE.sub("-", normalized.replace("/", "-").replace("\\", "-"))
    stem = re.sub(r"-+", "-", stem).strip(".-_")
    return (stem or fallback)[:100]


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class VideoStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.exports = self.root / "exports"
        self.jobs = self.root / "jobs"
        self.temp = self.root / "temp"

    def prepare(self) -> None:
        for path in (self.exports, self.jobs, self.temp):
            path.mkdir(parents=True, exist_ok=True)

    def temporary(self, job_id: UUID, suffix: str = ".mp4.part") -> Path:
        path = (self.temp / f"{job_id}{suffix}").resolve()
        self._ensure(path, self.temp)
        return path

    def final(self, job_id: UUID, stem: str) -> Path:
        path = (self.exports / f"{safe_stem(stem)}-{str(job_id)[:8]}.mp4").resolve()
        self._ensure(path, self.exports)
        return path

    def sidecar(self, job_id: UUID, suffix: str) -> Path:
        if suffix not in {".json", ".srt", ".log"}:
            raise ValueError("unsupported sidecar suffix")
        path = (self.jobs / f"{job_id}{suffix}").resolve()
        self._ensure(path, self.jobs)
        return path

    def relative(self, path: Path) -> str:
        resolved = path.resolve()
        self._ensure(resolved, self.root)
        return resolved.relative_to(self.root).as_posix()

    def registered(self, relative: str) -> Path | None:
        path = (self.root / relative).resolve()
        if self.root not in path.parents or not path.is_file():
            return None
        if self.exports not in path.parents and self.jobs not in path.parents:
            return None
        return path

    def atomic_complete(self, temporary: Path, final: Path) -> None:
        self._ensure(temporary.resolve(), self.temp)
        self._ensure(final.resolve(), self.exports)
        if not temporary.is_file() or temporary.stat().st_size <= 0:
            raise ValueError("encoder did not produce a non-empty temporary output")
        os.replace(temporary, final)

    def cleanup_job(self, job_id: UUID) -> None:
        prefix = str(job_id)
        for path in self.temp.iterdir() if self.temp.exists() else ():
            if path.name.startswith(prefix) and path.is_file():
                path.unlink(missing_ok=True)

    def disk(self) -> tuple[int, int]:
        usage = shutil.disk_usage(self.root)
        storage = (
            sum(path.stat().st_size for path in self.exports.rglob("*") if path.is_file())
            if self.exports.exists()
            else 0
        )
        return usage.free, storage

    @staticmethod
    def _ensure(path: Path, root: Path) -> None:
        if path == root or root not in path.parents:
            raise ValueError("video path escapes configured root")
