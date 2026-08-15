from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from koalabattle.models.orm import ProductionRow, SpeechCacheRow, VoicePresetRow
from koalabattle.storage.database import Database

from .models import ProductionTimeline, SpeechArtifact, SpeechProviderKind, VoicePreset


class ProductionRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def save(self, production: ProductionTimeline) -> ProductionTimeline:
        async with self.database.sessions() as session:
            row = await session.get(ProductionRow, str(production.id))
            values = {
                "match_id": str(production.match_id),
                "profile_id": production.profile.id,
                "profile_version": production.profile.version,
                "timeline_version": production.timeline_version,
                "revision": production.revision,
                "status": production.status.value,
                "director_state": production.director_state.value,
                "timeline_json": production.model_dump_json(),
                "voice_assignments_json": json.dumps(production.voice_assignments, sort_keys=True),
                "overrides_json": json.dumps(production.overrides, sort_keys=True),
                "authoritative_client_id": production.authoritative_client_id,
                "created_at": production.created_at,
                "updated_at": production.updated_at,
            }
            if row is None:
                session.add(ProductionRow(id=str(production.id), **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            await session.commit()
        return production

    async def get(self, production_id: UUID) -> ProductionTimeline | None:
        async with self.database.sessions() as session:
            row = await session.get(ProductionRow, str(production_id))
            return ProductionTimeline.model_validate_json(row.timeline_json) if row else None

    async def list_for_match(self, match_id: UUID) -> tuple[ProductionTimeline, ...]:
        async with self.database.sessions() as session:
            rows = (
                await session.scalars(
                    select(ProductionRow)
                    .where(ProductionRow.match_id == str(match_id))
                    .order_by(ProductionRow.created_at.desc())
                )
            ).all()
            return tuple(ProductionTimeline.model_validate_json(row.timeline_json) for row in rows)

    async def list_live_for_match(self, match_id: UUID) -> tuple[ProductionTimeline, ...]:
        return tuple(
            production
            for production in await self.list_for_match(match_id)
            if production.status.value in {"draft", "live", "finalizing"}
        )

    async def upsert_voice(self, preset: VoicePreset) -> None:
        now = datetime.now(UTC)
        async with self.database.sessions() as session:
            row = await session.get(VoicePresetRow, preset.id)
            if row is None:
                row = VoicePresetRow(id=preset.id, created_at=now, schema_version="1.0")
                session.add(row)
            row.display_name = preset.display_name
            row.provider = preset.provider.value
            row.voice = preset.voice
            row.model = preset.model
            row.language = preset.language
            row.speed = preset.speed
            row.instructions = preset.instructions
            row.enabled = preset.enabled
            row.updated_at = now
            await session.commit()

    async def list_voices(self) -> tuple[VoicePreset, ...]:
        async with self.database.sessions() as session:
            rows = (await session.scalars(select(VoicePresetRow).order_by(VoicePresetRow.id))).all()
            return tuple(
                VoicePreset(
                    id=row.id,
                    display_name=row.display_name,
                    provider=SpeechProviderKind(row.provider),
                    voice=row.voice,
                    model=row.model,
                    language=row.language,
                    speed=row.speed,
                    instructions=row.instructions,
                    enabled=row.enabled,
                )
                for row in rows
            )

    async def record_cache(
        self,
        *,
        artifact: SpeechArtifact,
        provider: str,
        model: str,
        voice: str,
        text_sha256: str,
        relative_path: str,
    ) -> None:
        now = datetime.now(UTC)
        async with self.database.sessions() as session:
            row = await session.get(SpeechCacheRow, artifact.cache_key)
            if row is None:
                row = SpeechCacheRow(
                    cache_key=artifact.cache_key,
                    provider=provider,
                    model=model,
                    voice=voice,
                    text_sha256=text_sha256,
                    relative_path=relative_path,
                    media_type=artifact.media_type,
                    byte_size=artifact.byte_size,
                    duration_ms=artifact.duration_ms,
                    content_sha256=artifact.content_sha256,
                    created_at=now,
                    last_accessed_at=now,
                )
                session.add(row)
            else:
                row.last_accessed_at = now
            await session.commit()
