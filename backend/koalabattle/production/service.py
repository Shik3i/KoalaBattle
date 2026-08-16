from __future__ import annotations

import asyncio
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from koalabattle.config import Settings
from koalabattle.core.models import BattleEvent, MatchStatus
from koalabattle.storage import BattleRepository, Database

from .models import (
    CreateProduction,
    DirectorCommand,
    DirectorState,
    PrepareSpeechRequest,
    ProductionCue,
    ProductionProfile,
    ProductionStatus,
    ProductionTimeline,
    SpeechArtifact,
    SpeechProviderKind,
    SpeechProviderStatus,
    SpeechRequest,
    Track,
    VoicePreset,
)
from .profiles import PRODUCTION_PROFILES
from .repository import ProductionRepository
from .speech import (
    FakeSpeechProvider,
    OpenAISpeechProvider,
    SpeechCache,
    SpeechGenerationQueue,
    SpeechProvider,
    SystemSpeechProvider,
)
from .speech.cache import ValidatedAudio, speech_cache_key
from .timeline import build_timeline, cues_for_event, final_cues, retime_for_audio, segment_caption


class ProductionService:
    def __init__(
        self,
        database: Database,
        battles: BattleRepository,
        settings: Settings,
    ) -> None:
        self.repository = ProductionRepository(database)
        self.battles = battles
        self.settings = settings
        self.cache = SpeechCache(settings.speech_audio_root)
        self.queue = SpeechGenerationQueue(settings.speech_max_concurrency)
        self._timeline_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._finalization_tasks: set[asyncio.Task[None]] = set()
        edge_voices = (settings.speech_edge_voice_p1, settings.speech_edge_voice_p2)
        self.providers: dict[SpeechProviderKind, SpeechProvider] = {
            SpeechProviderKind.SYSTEM: SystemSpeechProvider(
                edge_enabled=settings.speech_edge_enabled,
                edge_voices=edge_voices,
            ),
            SpeechProviderKind.FAKE: FakeSpeechProvider(),
            SpeechProviderKind.OPENAI: OpenAISpeechProvider(api_key=settings.speech_openai_api_key),
            SpeechProviderKind.OPENAI_COMPATIBLE: OpenAISpeechProvider(
                api_key=settings.speech_openai_api_key,
                base_url=settings.speech_openai_base_url,
                compatible=True,
            ),
        }
        self.default_voice_assignments = (
            {"p1": "edge-neural-p1", "p2": "edge-neural-p2"}
            if settings.speech_edge_enabled
            else {"p1": "system-p1", "p2": "system-p2"}
        )

    async def start(self) -> None:
        defaults = (
            VoicePreset(
                id="edge-neural-p1",
                display_name="Edge Neural · Ava (online, free)",
                provider=SpeechProviderKind.SYSTEM,
                voice=self.settings.speech_edge_voice_p1,
                model="edge-tts-7.2.8",
                language="en-US",
                speed=1.02,
                enabled=self.settings.speech_edge_enabled,
            ),
            VoicePreset(
                id="edge-neural-p2",
                display_name="Edge Neural · Andrew (online, free)",
                provider=SpeechProviderKind.SYSTEM,
                voice=self.settings.speech_edge_voice_p2,
                model="edge-tts-7.2.8",
                language="en-US",
                speed=1.02,
                enabled=self.settings.speech_edge_enabled,
            ),
            VoicePreset(
                id="system-p1",
                display_name="Offline System A (basic)",
                provider=SpeechProviderKind.SYSTEM,
                voice="system-default",
                model="system",
            ),
            VoicePreset(
                id="system-p2",
                display_name="Offline System B (basic)",
                provider=SpeechProviderKind.SYSTEM,
                voice="system-default",
                model="system",
            ),
            VoicePreset(
                id="fake-test-a",
                display_name="Fake Test A",
                provider=SpeechProviderKind.FAKE,
                voice="test-a",
                model="fake-v1",
            ),
            VoicePreset(
                id="fake-test-b",
                display_name="Fake Test B",
                provider=SpeechProviderKind.FAKE,
                voice="test-b",
                model="fake-v1",
            ),
        )
        for preset in defaults:
            await self.repository.upsert_voice(preset)

    async def close(self) -> None:
        if self._finalization_tasks:
            await asyncio.gather(*tuple(self._finalization_tasks), return_exceptions=True)
        await self.queue.close()

    def profiles(self) -> tuple[ProductionProfile, ...]:
        return tuple(PRODUCTION_PROFILES.values())

    def provider_status(self) -> tuple[SpeechProviderStatus, ...]:
        return tuple(provider.status() for provider in self.providers.values())

    async def create(self, match_id: UUID, request: CreateProduction) -> ProductionTimeline:
        archive = await self.battles.get_match(match_id)
        if archive is None:
            raise KeyError(str(match_id))
        try:
            profile = PRODUCTION_PROFILES[request.profile_id]
        except KeyError as error:
            raise ValueError(f"Unknown production profile: {request.profile_id}") from error
        voices = {**self.default_voice_assignments, **request.voice_assignments}
        available = {preset.id for preset in await self.repository.list_voices() if preset.enabled}
        if not set(voices.values()).issubset(available):
            raise ValueError("voice assignment references an unknown or disabled VoicePreset")
        production = build_timeline(archive, profile, voices=voices)
        if production.status is ProductionStatus.FINALIZED:
            production = self._seal(production)
        return await self.repository.save(production)

    async def rebuild(self, production_id: UUID) -> ProductionTimeline:
        previous = await self.require(production_id)
        archive = await self.battles.get_match(previous.match_id)
        if archive is None:
            raise KeyError(str(previous.match_id))
        rebuilt = build_timeline(
            archive,
            previous.profile,
            revision=previous.revision + 1,
            voices=previous.voice_assignments,
        ).model_copy(update={"overrides": previous.overrides})
        if rebuilt.status is ProductionStatus.FINALIZED:
            rebuilt = self._seal(rebuilt)
        return await self.repository.save(rebuilt)

    async def on_event(self, event: BattleEvent) -> None:
        """Incrementally extend every live production after the event transaction commits."""
        async with self._timeline_locks[str(event.match_id)]:
            productions = await self.repository.list_live_for_match(event.match_id)
            if not productions and event.event_type == "battle_started":
                archive = await self.battles.get_match(event.match_id)
                if archive is None:
                    return
                production = build_timeline(
                    archive,
                    PRODUCTION_PROFILES["live-stream"],
                    voices=self.default_voice_assignments,
                )
                await self.repository.save(production)
                return
            for production in productions:
                if any(cue.event_sequence == event.sequence for cue in production.cues):
                    continue
                added, event_duration = cues_for_event(
                    event, production.profile, start_ms=production.duration_ms
                )
                updated = production.model_copy(
                    update={
                        "status": ProductionStatus.LIVE,
                        "cues": tuple(
                            sorted(
                                (*production.cues, *added),
                                key=lambda cue: (cue.start_ms, cue.track.value, cue.id),
                            )
                        ),
                        "duration_ms": (
                            production.duration_ms
                            + event_duration
                            + production.profile.event_gap_ms
                        ),
                        "revision": production.revision + 1,
                        "updated_at": datetime.now(UTC),
                    }
                )
                await self.repository.save(updated)

    async def on_match_completed(self, match_id: UUID) -> None:
        """Persist final cues immediately, then prepare local audio outside battle execution."""
        async with self._timeline_locks[str(match_id)]:
            archive = await self.battles.get_match(match_id)
            if archive is None:
                return
            productions = await self.repository.list_live_for_match(match_id)
            if not productions:
                production = self._seal(
                    build_timeline(
                        archive,
                        PRODUCTION_PROFILES["live-stream"],
                        voices=self.default_voice_assignments,
                    )
                )
                await self.repository.save(production)
                return
            for production in productions:
                cues = production.cues
                duration = production.duration_ms
                if not any(cue.id == "director-result" for cue in cues):
                    cues = (*cues, *final_cues(archive, start_ms=duration))
                    duration += 2400
                finalizing = production.model_copy(
                    update={
                        "status": ProductionStatus.FINALIZING,
                        "director_state": (
                            DirectorState.RESULT
                            if archive.status is MatchStatus.COMPLETED
                            else DirectorState.ENDED
                        ),
                        "cues": tuple(
                            sorted(cues, key=lambda cue: (cue.start_ms, cue.track.value, cue.id))
                        ),
                        "duration_ms": duration,
                        "revision": production.revision + 1,
                        "updated_at": datetime.now(UTC),
                    }
                )
                await self.repository.save(finalizing)
                task = asyncio.create_task(
                    self._finalize(finalizing.id), name=f"production-finalize-{finalizing.id}"
                )
                self._finalization_tasks.add(task)
                task.add_done_callback(self._finalization_tasks.discard)

    async def _finalize(self, production_id: UUID) -> None:
        try:
            production = await self.prepare(
                production_id, PrepareSpeechRequest(force=False, allow_paid=False)
            )
            cues, duration = retime_for_audio(production.cues, production.profile)
            await self.repository.save(
                self._seal(
                    production.model_copy(
                        update={
                            "cues": cues,
                            "duration_ms": duration,
                            "revision": production.revision + 1,
                        }
                    )
                )
            )
        except Exception as error:
            production = await self.require(production_id)
            failed = production.model_copy(
                update={
                    "status": ProductionStatus.FAILED,
                    "overrides": {
                        **production.overrides,
                        "finalization_error": f"{type(error).__name__}: {error}",
                    },
                    "updated_at": datetime.now(UTC),
                }
            )
            await self.repository.save(failed)

    @staticmethod
    def _seal(production: ProductionTimeline) -> ProductionTimeline:
        now = datetime.now(UTC)
        payload = production.model_dump(
            mode="json",
            exclude={"content_sha256", "created_at", "updated_at", "finalized_at", "status"},
        )
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return production.model_copy(
            update={
                "status": ProductionStatus.FINALIZED,
                "finalized_at": now,
                "updated_at": now,
                "content_sha256": digest,
            }
        )

    async def require(self, production_id: UUID) -> ProductionTimeline:
        production = await self.repository.get(production_id)
        if production is None:
            raise KeyError(str(production_id))
        return production

    async def prepare(
        self, production_id: UUID, request: PrepareSpeechRequest
    ) -> ProductionTimeline:
        production = await self.require(production_id)
        if not production.profile.speech_enabled:
            ready = production.model_copy(
                update={"status": ProductionStatus.READY, "updated_at": datetime.now(UTC)}
            )
            return await self.repository.save(ready)
        voices = {preset.id: preset for preset in await self.repository.list_voices()}
        preparing = production.model_copy(
            update={"status": ProductionStatus.PREPARING, "updated_at": datetime.now(UTC)}
        )
        await self.repository.save(preparing)
        generated: dict[str, SpeechArtifact] = {}
        failures: list[str] = []
        for cue in production.cues:
            if cue.track is not Track.COMMENTARY or not cue.side:
                continue
            preset = voices.get(production.voice_assignments.get(cue.side, ""))
            if preset is None:
                failures.append(f"{cue.id}: missing VoicePreset")
                continue
            try:
                generated[cue.id] = await self.synthesize(
                    str(cue.payload["text"]),
                    preset,
                    allow_paid=request.allow_paid,
                    force=request.force,
                )
            except Exception as error:
                failures.append(f"{cue.id}: {error}")
        cues = self._with_speech(production.cues, generated, production)
        # Speech is optional presentation media. Keep captions and the production
        # exportable when an online provider is unavailable, even if every cue failed.
        status = ProductionStatus.PARTIAL if failures else ProductionStatus.READY
        overrides = {**production.overrides, "speech_failures": failures}
        updated = production.model_copy(
            update={
                "cues": cues,
                "status": status,
                "overrides": overrides,
                "updated_at": datetime.now(UTC),
            }
        )
        return await self.repository.save(updated)

    async def synthesize(
        self,
        text: str,
        preset: VoicePreset,
        *,
        allow_paid: bool,
        force: bool = False,
    ) -> SpeechArtifact:
        if len(text) > self.settings.speech_max_text_characters:
            raise ValueError("speech text exceeds configured character limit")
        provider = self.providers[preset.provider]
        provider_status = provider.status()
        if not provider_status.available:
            raise RuntimeError(provider_status.detail)
        if provider_status.paid and not allow_paid:
            raise PermissionError("paid speech generation requires allow_paid=true")
        speech = SpeechRequest(
            text=text,
            provider=preset.provider,
            model=preset.model or self.settings.speech_openai_model,
            voice=preset.voice,
            speed=preset.speed,
            language=preset.language,
            instructions=preset.instructions,
        )
        key = speech_cache_key(speech)
        cached = None if force else self.cache.validate(key)
        if cached is not None:
            return self._artifact(key, cached, True)
        content = await self.queue.generate(key, lambda: provider.synthesize(speech))
        validated = self.cache.store(key, content)
        artifact = self._artifact(key, validated, False)
        await self.repository.record_cache(
            artifact=artifact,
            provider=preset.provider.value,
            model=speech.model,
            voice=speech.voice,
            text_sha256=hashlib.sha256(speech.text.encode()).hexdigest(),
            relative_path=str(validated.path.relative_to(self.cache.root)),
        )
        return artifact

    def media_path(self, cache_key: str) -> Path | None:
        valid = self.cache.validate(cache_key)
        return valid.path if valid is not None else None

    async def direct(self, production_id: UUID, command: DirectorCommand) -> ProductionTimeline:
        production = await self.require(production_id)
        state = production.director_state
        transitions = {
            "start": (
                DirectorState.MATCH_INTRO
                if production.profile.intro_enabled
                else DirectorState.BATTLE
            ),
            "pause": DirectorState.PAUSED,
            "resume": DirectorState.BATTLE,
            "show-intro": DirectorState.MATCH_INTRO,
            "show-team-reveal": DirectorState.TEAM_REVEAL,
            "show-result": DirectorState.RESULT,
            "show-champion": DirectorState.CHAMPION,
            "end": DirectorState.ENDED,
        }
        if command.command == "next":
            order = [
                DirectorState.PRE_SHOW,
                DirectorState.MATCH_INTRO,
                DirectorState.TEAM_REVEAL,
                DirectorState.BATTLE,
                DirectorState.BETWEEN_GAMES,
                DirectorState.RESULT,
                DirectorState.CHAMPION,
                DirectorState.ENDED,
            ]
            state = (
                order[min(len(order) - 1, order.index(state) + 1)]
                if state in order
                else DirectorState.BATTLE
            )
        else:
            state = transitions[command.command]
        updated = production.model_copy(
            update={
                "director_state": state,
                "authoritative_client_id": command.client_id or production.authoritative_client_id,
                "updated_at": datetime.now(UTC),
            }
        )
        return await self.repository.save(updated)

    @staticmethod
    def _artifact(key: str, valid: ValidatedAudio, hit: bool) -> SpeechArtifact:
        return SpeechArtifact(
            cache_key=key,
            media_url=f"/api/production/media/{key}",
            duration_ms=valid.duration_ms,
            byte_size=valid.byte_size,
            content_sha256=valid.content_sha256,
            cache_hit=hit,
        )

    @staticmethod
    def _with_speech(
        cues: tuple[ProductionCue, ...],
        generated: dict[str, SpeechArtifact],
        production: ProductionTimeline,
    ) -> tuple[ProductionCue, ...]:
        result: list[ProductionCue] = []
        by_event: dict[int, SpeechArtifact] = {}
        for cue in cues:
            artifact = generated.get(cue.id)
            if artifact and cue.event_sequence:
                by_event[cue.event_sequence] = artifact
                result.append(cue.model_copy(update={"duration_ms": artifact.duration_ms}))
                result.append(
                    ProductionCue(
                        id=f"{cue.id}-voice",
                        track=Track.VOICE,
                        kind="cached-speech",
                        start_ms=cue.start_ms,
                        duration_ms=artifact.duration_ms,
                        event_sequence=cue.event_sequence,
                        turn=cue.turn,
                        side=cue.side,
                        payload=artifact.model_dump(mode="json"),
                    )
                )
            elif cue.track is not Track.VOICE:
                result.append(cue)
        normalized: list[ProductionCue] = []
        for cue in result:
            artifact = by_event.get(cue.event_sequence or -1)
            if cue.track is Track.CAPTIONS and artifact:
                commentary = next(
                    (
                        str(item.payload["text"])
                        for item in result
                        if item.track is Track.COMMENTARY
                        and item.event_sequence == cue.event_sequence
                    ),
                    "",
                )
                normalized.append(
                    cue.model_copy(
                        update={
                            "duration_ms": artifact.duration_ms,
                            "payload": {
                                "segments": [
                                    segment.model_dump(mode="json")
                                    for segment in segment_caption(
                                        commentary,
                                        maximum=production.profile.caption_max_characters,
                                        duration_ms=artifact.duration_ms,
                                    )
                                ]
                            },
                        }
                    )
                )
            else:
                normalized.append(cue)
        return tuple(sorted(normalized, key=lambda cue: (cue.start_ms, cue.track.value, cue.id)))
