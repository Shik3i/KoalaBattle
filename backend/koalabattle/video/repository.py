from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from koalabattle.models.orm import VideoExportJobRow
from koalabattle.storage import Database

from .models import ExportStatus, VideoExportJob

_ACTIVE = {
    ExportStatus.PREPARING.value,
    ExportStatus.RENDERING.value,
    ExportStatus.ENCODING.value,
    ExportStatus.FINALIZING.value,
}


class VideoExportRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create(self, job: VideoExportJob) -> VideoExportJob:
        row = self._row(job)
        async with self.database.sessions() as session:
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                if job.idempotency_key:
                    existing = await self.by_idempotency(job.idempotency_key)
                    if existing is not None:
                        return existing
                raise
        return job

    async def save(self, job: VideoExportJob) -> VideoExportJob:
        async with self.database.sessions() as session:
            row = await session.get(VideoExportJobRow, str(job.id))
            if row is None:
                raise KeyError(str(job.id))
            fresh = self._row(job)
            for name in (
                "status",
                "priority",
                "progress",
                "output_relative_path",
                "job_json",
                "started_at",
                "completed_at",
                "updated_at",
            ):
                setattr(row, name, getattr(fresh, name))
            await session.commit()
        return job

    async def get(self, job_id: UUID) -> VideoExportJob | None:
        async with self.database.sessions() as session:
            row = await session.get(VideoExportJobRow, str(job_id))
            return VideoExportJob.model_validate_json(row.job_json) if row else None

    async def by_idempotency(self, key: str) -> VideoExportJob | None:
        async with self.database.sessions() as session:
            row = await session.scalar(
                select(VideoExportJobRow).where(VideoExportJobRow.idempotency_key == key)
            )
            return VideoExportJob.model_validate_json(row.job_json) if row else None

    async def list(self, *, match_id: UUID | None = None) -> tuple[VideoExportJob, ...]:
        query = select(VideoExportJobRow)
        if match_id is not None:
            query = query.where(VideoExportJobRow.match_id == str(match_id))
        query = query.order_by(VideoExportJobRow.created_at.desc()).limit(250)
        async with self.database.sessions() as session:
            rows = (await session.scalars(query)).all()
            return tuple(VideoExportJob.model_validate_json(row.job_json) for row in rows)

    async def next_queued(self) -> VideoExportJob | None:
        async with self.database.sessions() as session:
            row = await session.scalar(
                select(VideoExportJobRow)
                .where(VideoExportJobRow.status == ExportStatus.QUEUED.value)
                .order_by(VideoExportJobRow.priority.desc(), VideoExportJobRow.created_at)
                .limit(1)
            )
            return VideoExportJob.model_validate_json(row.job_json) if row else None

    async def reconcile_interrupted(self) -> int:
        now = datetime.now(UTC)
        changed = 0
        async with self.database.sessions() as session:
            rows = (
                await session.scalars(
                    select(VideoExportJobRow).where(VideoExportJobRow.status.in_(_ACTIVE))
                )
            ).all()
            for row in rows:
                job = VideoExportJob.model_validate_json(row.job_json).model_copy(
                    update={
                        "status": ExportStatus.FAILED,
                        "stage": "Interrupted",
                        "error_category": "interrupted",
                        "error_detail": "Backend or renderer restarted while this job was active.",
                        "updated_at": now,
                    }
                )
                row.status = job.status.value
                row.job_json = job.model_dump_json()
                row.updated_at = now
                changed += 1
            await session.commit()
        return changed

    @staticmethod
    def _row(job: VideoExportJob) -> VideoExportJobRow:
        return VideoExportJobRow(
            id=str(job.id),
            production_id=str(job.production_id),
            match_id=str(job.match_id),
            backend=job.backend.value,
            preset_id=job.preset.id,
            status=job.status.value,
            priority=job.priority,
            progress=job.progress,
            idempotency_key=job.idempotency_key,
            output_relative_path=job.output_relative_path,
            job_json=job.model_dump_json(),
            created_at=job.created_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            updated_at=job.updated_at,
        )
