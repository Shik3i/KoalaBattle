from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import io
import json
import os
import random
import re
import tempfile
import wave
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from koalabattle.branding.marks import mark_for
from koalabattle.config import Settings
from koalabattle.core.models import BattleEvent, MatchArchive, MatchStatus
from koalabattle.storage import BattleRepository, Database

from .models import (
    CreateProduction,
    DirectorCommand,
    DirectorState,
    DuplicateProduction,
    NarratorSettings,
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
    UpdateProduction,
    VoicePool,
    VoicePreset,
    VoiceReferenceUpload,
    VoiceSelectionMode,
)
from .narrator import build_narrator_plan
from .profiles import PRODUCTION_PROFILES
from .repository import ProductionRepository
from .speech import (
    FakeSpeechProvider,
    OpenAISpeechProvider,
    QwenLocalSpeechProvider,
    SpeechCache,
    SpeechGenerationQueue,
    SpeechProvider,
    SystemSpeechProvider,
)
from .speech.cache import ValidatedAudio, speech_cache_key
from .style import ParticipantBranding, ProductionStyle, SaveStylePreset, StylePreset
from .style_presets import BUILTIN_STYLES, builtin_presets, suggest_style
from .timeline import build_timeline, cues_for_event, final_cues, retime_for_audio, segment_caption


def _generation(format_id: str) -> int:
    match = re.match(r"^gen(\d)", format_id.lower())
    return int(match.group(1)) if match else 9


def _preset_id(display_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", display_name.lower()).strip("-")[:58]
    if len(slug) < 3:
        raise ValueError("style preset name must contain at least three usable characters")
    return slug


def apply_default_branding(style: ProductionStyle, archive: MatchArchive) -> ProductionStyle:
    """Fill in each player's identity from the match, without overwriting user choices.

    A brand-new production should already show sensible names, marks and accents. Anything
    the user has explicitly set on the style survives, because a preset carried between
    matches must not silently rename this match's players.
    """
    players = dict(style.players)
    for player in archive.config.players:
        side = player.side.value
        existing = players.get(side, ParticipantBranding())
        mark = mark_for(player.agent_type.value, player.provider)
        players[side] = existing.model_copy(
            update={
                "display_name": existing.display_name or player.display_name,
                "logo_mark": existing.logo_mark or mark.id,
                "accent": existing.accent or mark.accent,
                "secondary_accent": existing.secondary_accent or mark.secondary_accent,
            }
        )
    return style.model_copy(update={"players": players})


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
        edge_voices = (
            settings.speech_edge_voice_p1,
            settings.speech_edge_voice_p2,
            settings.speech_edge_voice_narrator,
        )
        self.providers: dict[SpeechProviderKind, SpeechProvider] = {
            SpeechProviderKind.SYSTEM: SystemSpeechProvider(
                edge_enabled=settings.speech_edge_enabled,
                edge_voices=edge_voices,
            ),
            SpeechProviderKind.QWEN_LOCAL: QwenLocalSpeechProvider(
                base_url=settings.speech_qwen_base_url,
                endpoint=settings.speech_qwen_endpoint,
                model=settings.speech_qwen_model,
                api_key=settings.speech_qwen_api_key,
                reference_root=settings.speech_qwen_reference_root,
                timeout_seconds=settings.speech_qwen_timeout_seconds,
                max_retries=settings.speech_qwen_max_retries,
                max_concurrency=settings.speech_qwen_max_concurrency,
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
        self.default_narrator_assignment = (
            {"narrator": "edge-neural-narrator"} if settings.speech_edge_enabled else {}
        )

    async def start(self) -> None:
        defaults = (
            VoicePreset(
                id="edge-neural-p1",
                display_name="Edge Neural · Emma (natural, online, free)",
                provider=SpeechProviderKind.SYSTEM,
                voice=self.settings.speech_edge_voice_p1,
                model="edge-tts-7.2.8",
                language="en-US",
                speed=0.96,
                enabled=self.settings.speech_edge_enabled,
            ),
            VoicePreset(
                id="edge-neural-p2",
                display_name="Edge Neural · Brian (natural, online, free)",
                provider=SpeechProviderKind.SYSTEM,
                voice=self.settings.speech_edge_voice_p2,
                model="edge-tts-7.2.8",
                language="en-US",
                speed=0.96,
                enabled=self.settings.speech_edge_enabled,
            ),
            VoicePreset(
                id="edge-neural-narrator",
                display_name="Edge Neural · Guy (stadium narrator, online, free)",
                provider=SpeechProviderKind.SYSTEM,
                voice=self.settings.speech_edge_voice_narrator,
                model="edge-tts-7.2.8",
                language="en-US",
                speed=1.02,
                instructions=(
                    "Energetic sports commentator. Clear, concise, and never conversational."
                ),
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
                id="qwen-local-clone",
                display_name="Qwen3-TTS · Local reference clone",
                provider=SpeechProviderKind.QWEN_LOCAL,
                voice="qwen-clone",
                model=self.settings.speech_qwen_model,
                language="en-US",
                speed=1.0,
                tags=("local", "clone"),
                enabled=False,
            ),
            VoicePreset(
                id="qwen-local-chelsie",
                display_name="Qwen3-TTS · Chelsie (local)",
                provider=SpeechProviderKind.QWEN_LOCAL,
                voice="Chelsie",
                model=self.settings.speech_qwen_model,
                language="en-US",
                speed=1.0,
                tags=("local", "bright", "clear"),
            ),
            VoicePreset(
                id="qwen-local-ethan",
                display_name="Qwen3-TTS · Ethan (local)",
                provider=SpeechProviderKind.QWEN_LOCAL,
                voice="Ethan",
                model=self.settings.speech_qwen_model,
                language="en-US",
                speed=1.0,
                tags=("local", "warm", "dynamic"),
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

    async def voice_pools(self) -> tuple[VoicePool, ...]:
        return await self.repository.list_voice_pools()

    async def save_voice_pool(self, pool: VoicePool) -> VoicePool:
        voices = {voice.id for voice in await self.repository.list_voices()}
        missing = sorted(set(pool.voice_ids) - voices)
        if missing:
            raise ValueError(f"voice pool references unknown voices: {', '.join(missing)}")
        await self.repository.upsert_voice_pool(pool)
        return pool

    async def save_voice_reference(self, upload: VoiceReferenceUpload) -> VoicePreset:
        if upload.preset.provider is not SpeechProviderKind.QWEN_LOCAL:
            raise ValueError("reference audio is only supported for qwen-local voice presets")
        try:
            content = base64.b64decode(upload.audio_base64, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("reference audio must be valid base64") from error
        if len(content) > 16 * 1024 * 1024:
            raise ValueError("reference audio exceeds 16 MiB")
        try:
            with wave.open(io.BytesIO(content)) as audio:
                if audio.getnchannels() not in (1, 2) or audio.getframerate() <= 0:
                    raise ValueError("reference audio must be a valid mono or stereo WAV")
                duration_ms = round(audio.getnframes() * 1000 / audio.getframerate())
        except (EOFError, wave.Error) as error:
            raise ValueError("reference audio must be a valid WAV file") from error
        if duration_ms < 1_000 or duration_ms > 30_000:
            raise ValueError("reference audio duration must be between 1 and 30 seconds")
        root = self.settings.speech_qwen_reference_root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        relative_path = f"{upload.preset.id}.wav"
        destination = (root / relative_path).resolve()
        if root not in destination.parents:
            raise ValueError("reference audio path escapes the configured voice root")
        descriptor, temporary = tempfile.mkstemp(prefix=f".{upload.preset.id}-", dir=root)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
        saved = upload.preset.model_copy(update={"reference_audio_path": relative_path})
        await self.repository.upsert_voice(saved)
        return saved

    async def create(self, match_id: UUID, request: CreateProduction) -> ProductionTimeline:
        archive = await self.battles.get_match(match_id)
        if archive is None:
            raise KeyError(str(match_id))
        try:
            profile = PRODUCTION_PROFILES[request.profile_id]
        except KeyError as error:
            raise ValueError(f"Unknown production profile: {request.profile_id}") from error
        narrator = request.narrator or NarratorSettings()
        voices = await self._resolve_voice_assignments(match_id, request, narrator)
        if narrator.enabled:
            voices = {**self.default_narrator_assignment, **voices}
            if "narrator" in request.voice_assignments:
                voices["narrator"] = request.voice_assignments["narrator"]
        available = {preset.id for preset in await self.repository.list_voices() if preset.enabled}
        if not set(voices.values()).issubset(available):
            raise ValueError("voice assignment references an unknown or disabled VoicePreset")
        style = request.style or await self.style_for(
            request.style_id
            or suggest_style(
                generation=_generation(archive.config.format),
                vertical=profile.aspect_ratio == "9:16",
            )
        )
        production = build_timeline(archive, profile, voices=voices, narrator=narrator).model_copy(
            update={
                "style": apply_default_branding(style, archive),
                "title": request.title,
                "voice_pool_id": request.voice_pool_id,
                "voice_selection_mode": request.voice_selection_mode,
                "voice_selection_seed": request.voice_selection_seed,
            }
        )
        if production.status is ProductionStatus.FINALIZED:
            production = self._seal(production)
        saved = await self.repository.save(production)
        if saved.status is ProductionStatus.FINALIZED:
            # Archived replays are already complete. Prepare their public media before the
            # caller opens the Studio, so the first export cannot discover an empty speech
            # cache later. The default assignments are Edge Neural; no system voice is used
            # by this automatic path.
            return await self.ensure_prepared(saved.id)
        return saved

    async def _resolve_voice_assignments(
        self, match_id: UUID, request: CreateProduction, narrator: NarratorSettings
    ) -> dict[str, str]:
        explicit = dict(request.voice_assignments)
        if request.voice_selection_mode is VoiceSelectionMode.EXPLICIT:
            return {**self.default_voice_assignments, **explicit}
        if not request.voice_pool_id:
            raise ValueError("voice selection requires a voice_pool_id")
        pool = await self.repository.get_voice_pool(request.voice_pool_id)
        if pool is None or not pool.enabled:
            raise ValueError(f"voice pool not found or disabled: {request.voice_pool_id}")
        available = {
            voice.id: voice
            for voice in await self.repository.list_voices()
            if voice.enabled and voice.id in pool.voice_ids
        }
        roles = ["p1", "p2"] + (["narrator"] if narrator.enabled else [])
        if len(available) < len(roles):
            raise ValueError(
                f"voice pool {pool.id} needs at least {len(roles)} enabled distinct voices"
            )
        seed = request.voice_selection_seed
        if seed is None:
            seed = int.from_bytes(hashlib.sha256(f"{match_id}:{pool.id}".encode()).digest()[:8])
        chooser = random.Random(seed)
        candidates = list(available)
        chooser.shuffle(candidates)
        selected: dict[str, str] = {}
        for role in roles:
            if role in explicit:
                selected[role] = explicit[role]
                if selected[role] not in available:
                    raise ValueError(f"voice {selected[role]} is not enabled in pool {pool.id}")
                continue
            selected[role] = next(
                voice_id for voice_id in candidates if voice_id not in selected.values()
            )
        return selected

    async def ensure_prepared(self, production_id: UUID) -> ProductionTimeline:
        """Materialize missing public production media for an archived replay.

        Preparation is deliberately idempotent: valid cached speech is reused, while a
        missing or corrupt artifact is regenerated through the production's assigned voice.
        Live productions remain untouched until match completion finalizes them.
        """
        production = await self.require(production_id)
        if production.status not in {
            ProductionStatus.FINALIZED,
            ProductionStatus.READY,
            ProductionStatus.PARTIAL,
        } or not production.profile.speech_enabled:
            return production
        if self._needs_timeline_compaction(production):
            production = await self._compact_archived_timeline(production)
        if not self._needs_speech_preparation(production):
            return production
        return await self.prepare(
            production.id,
            PrepareSpeechRequest(force=False, allow_paid=False),
        )

    def _needs_speech_preparation(self, production: ProductionTimeline) -> bool:
        voice_cues = tuple(cue for cue in production.cues if cue.track is Track.VOICE)
        for commentary in production.cues:
            if commentary.track is not Track.COMMENTARY or commentary.event_sequence is None:
                continue
            speaker = commentary.speaker or commentary.side
            voice = next(
                (
                    cue
                    for cue in voice_cues
                    if cue.event_sequence == commentary.event_sequence
                    and (cue.speaker or cue.side) == speaker
                ),
                None,
            )
            cache_key = voice.payload.get("cache_key") if voice else None
            if not isinstance(cache_key, str) or self.cache.validate(cache_key) is None:
                return True
        return False

    @staticmethod
    def _needs_timeline_compaction(production: ProductionTimeline) -> bool:
        return production.profile.turn_gap_ms is None or any(
            cue.track is Track.VISUAL
            and cue.kind in {"agent_progress", "agent_state", "showdown_message"}
            for cue in production.cues
        )

    async def _compact_archived_timeline(
        self, production: ProductionTimeline
    ) -> ProductionTimeline:
        archive = await self.battles.get_match(production.match_id)
        if archive is None:
            raise KeyError(str(production.match_id))
        profile = PRODUCTION_PROFILES.get(production.profile.id, production.profile)
        compacted = build_timeline(
            archive,
            profile,
            production_id=production.id,
            revision=production.revision + 1,
            voices=production.voice_assignments,
            narrator=production.narrator,
        ).model_copy(
            update={
                "style": production.style,
                "title": production.title,
                "overrides": production.overrides,
                "created_at": production.created_at,
            }
        )
        return await self.repository.save(compacted)

    async def rebuild(self, production_id: UUID) -> ProductionTimeline:
        previous = await self.require(production_id)
        archive = await self.battles.get_match(previous.match_id)
        if archive is None:
            raise KeyError(str(previous.match_id))
        profile = PRODUCTION_PROFILES.get(previous.profile.id, previous.profile)
        rebuilt = build_timeline(
            archive,
            profile,
            production_id=previous.id,
            revision=previous.revision + 1,
            voices=previous.voice_assignments,
            narrator=previous.narrator,
        ).model_copy(
            update={
                "overrides": previous.overrides,
                # Rebuilding regenerates timing from the archive; it must not silently
                # reset the presentation the user configured.
                "style": previous.style,
                "title": previous.title,
            }
        )
        if rebuilt.status is ProductionStatus.FINALIZED:
            rebuilt = self._seal(rebuilt)
        return await self.repository.save(rebuilt)

    # ----------------------------------------------------------------- styles

    async def styles(self) -> tuple[StylePreset, ...]:
        """Built-in presets first, then the user's saved ones."""
        return (*builtin_presets(), *await self.repository.list_style_presets())

    async def style_for(self, style_id: str) -> ProductionStyle:
        builtin = BUILTIN_STYLES.get(style_id)
        if builtin is not None:
            return builtin
        saved = next(
            (
                preset
                for preset in await self.repository.list_style_presets()
                if preset.id == style_id
            ),
            None,
        )
        if saved is None:
            raise ValueError(f"Unknown production style: {style_id}")
        return saved.style

    async def save_style_preset(self, request: SaveStylePreset) -> StylePreset:
        preset_id = _preset_id(request.display_name)
        if preset_id in BUILTIN_STYLES:
            # Built-ins are the escape route users come back to after experimenting.
            raise ValueError("built-in style presets cannot be overwritten; choose another name")
        return await self.repository.save_style_preset(
            StylePreset(
                id=preset_id,
                display_name=request.display_name,
                description=request.description,
                builtin=False,
                style=request.style.model_copy(
                    update={
                        "id": preset_id,
                        "display_name": request.display_name,
                        "builtin": False,
                    }
                ),
            )
        )

    async def delete_style_preset(self, preset_id: str) -> bool:
        if preset_id in BUILTIN_STYLES:
            raise ValueError("built-in style presets cannot be deleted")
        return await self.repository.delete_style_preset(preset_id)

    # ------------------------------------------------------------ productions

    async def update(self, production_id: UUID, request: UpdateProduction) -> ProductionTimeline:
        """Apply a presentation edit. Cues, events and results are left exactly as they are."""
        production = await self.require(production_id)
        if request.narrator is not None:
            archive = await self.battles.get_match(production.match_id)
            if archive is None:
                raise KeyError(str(production.match_id))
            voices = dict(production.voice_assignments)
            if request.narrator.enabled:
                voices["narrator"] = request.narrator.voice_preset_id
            else:
                voices.pop("narrator", None)
            available = {
                preset.id
                for preset in await self.repository.list_voices()
                if preset.enabled
            }
            if not set(voices.values()).issubset(available):
                raise ValueError(
                    "narrator voice assignment references an unknown or disabled VoicePreset"
                )
            profile = PRODUCTION_PROFILES.get(production.profile.id, production.profile)
            rebuilt = build_timeline(
                archive,
                profile,
                production_id=production.id,
                revision=production.revision + 1,
                voices=voices,
                narrator=request.narrator,
            ).model_copy(update={"style": production.style, "title": production.title})
            if rebuilt.status is ProductionStatus.FINALIZED:
                rebuilt = self._seal(rebuilt)
                return await self.ensure_prepared((await self.repository.save(rebuilt)).id)
            return await self.repository.save(rebuilt)
        update: dict[str, object] = {"updated_at": datetime.now(UTC)}
        if request.style is not None:
            update["style"] = request.style
        if request.clear_title:
            update["title"] = None
        elif request.title is not None:
            update["title"] = request.title
        updated = production.model_copy(update=update)
        if updated.status is ProductionStatus.FINALIZED:
            updated = self._seal(updated)
        return await self.repository.save(updated)

    async def duplicate(
        self, production_id: UUID, request: DuplicateProduction
    ) -> ProductionTimeline:
        """Copy a production's presentation onto a fresh id sharing the same match."""
        source = await self.require(production_id)
        style = await self.style_for(request.style_id) if request.style_id else source.style
        now = datetime.now(UTC)
        copy = source.model_copy(
            update={
                "id": uuid4(),
                "style": style,
                "title": request.title or source.title,
                "revision": 1,
                "created_at": now,
                "updated_at": now,
            }
        )
        if copy.status is ProductionStatus.FINALIZED:
            copy = self._seal(copy)
        return await self.repository.save(copy)

    async def delete(self, production_id: UUID) -> bool:
        return await self.repository.delete(production_id)

    async def on_event(self, event: BattleEvent) -> None:
        """Incrementally extend every live production after the event transaction commits."""
        async with self._timeline_locks[str(event.match_id)]:
            productions = await self.repository.list_live_for_match(event.match_id)
            archive = await self.battles.get_match(event.match_id)
            if not productions and event.event_type == "battle_started":
                archive = await self.battles.get_match(event.match_id)
                if archive is None:
                    return
                production = build_timeline(
                    archive,
                    PRODUCTION_PROFILES["live-stream"],
                    voices=self.default_voice_assignments,
                    narrator=NarratorSettings(),
                )
                await self.repository.save(production)
                return
            for production in productions:
                if any(cue.event_sequence == event.sequence for cue in production.cues):
                    continue
                last_turn = max(
                    (cue.turn or 0 for cue in production.cues if cue.event_sequence is not None),
                    default=0,
                )
                event_turn = (
                    event.turn
                    if event.event_type == "turn_started" and event.turn > 0
                    else last_turn or None
                )
                added, event_duration = cues_for_event(
                    event,
                    production.profile,
                    start_ms=production.duration_ms,
                    timeline_turn=event_turn,
                    narrator_candidate=(
                        build_narrator_plan(archive.events, production.narrator).get(event.sequence)
                        if archive is not None
                        else None
                    ),
                    narrator_settings=production.narrator,
                )
                turn_gap = (
                    production.profile.turn_pause_ms
                    if added
                    and event_turn is not None
                    and event.event_type == "turn_started"
                    and last_turn > 0
                    and event_turn != last_turn
                    else 0
                )
                if turn_gap:
                    added = tuple(
                        cue.model_copy(update={"start_ms": cue.start_ms + turn_gap})
                        for cue in added
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
                        "duration_ms": production.duration_ms + event_duration + turn_gap,
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
                    cues = (
                        *cues,
                        *final_cues(
                            archive,
                            start_ms=duration,
                            result_duration_ms=production.profile.result_duration_ms,
                            outro_duration_ms=production.profile.outro_duration_ms,
                        ),
                    )
                    duration += (
                        production.profile.result_duration_ms
                        + production.profile.outro_duration_ms
                    )
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
        pending: list[tuple[ProductionCue, VoicePreset]] = []
        for cue in production.cues:
            if cue.track is not Track.COMMENTARY:
                continue
            speaker = cue.speaker or cue.side
            if not speaker:
                failures.append(f"{cue.id}: missing speaker")
                continue
            preset = voices.get(production.voice_assignments.get(speaker, ""))
            if preset is None:
                failures.append(f"{cue.id}: missing VoicePreset")
                continue
            pending.append((cue, preset))

        async def generate(
            cue: ProductionCue, preset: VoicePreset
        ) -> tuple[str, SpeechArtifact | None, str | None]:
            try:
                artifact = await self.synthesize(
                    str(cue.payload["text"]),
                    preset,
                    allow_paid=request.allow_paid,
                    force=request.force,
                )
                return cue.id, artifact, None
            except Exception as error:
                return cue.id, None, f"{cue.id}: {error}"

        # Schedule every cue immediately. SpeechGenerationQueue remains the bounded safety
        # valve for Edge/network pressure, while one slow request no longer serializes the
        # entire replay preparation.
        results = await asyncio.gather(*(generate(cue, preset) for cue, preset in pending))
        for cue_id, artifact, failure in results:
            if artifact is not None:
                generated[cue_id] = artifact
            if failure is not None:
                failures.append(failure)
        cues = self._with_speech(production.cues, generated, production)
        # Real speech is longer or shorter than the estimate the timeline was built from, so
        # the clock has to be normalized against it. Live matches got this through
        # `_finalize`; a production created in the Video Studio from an archived match never
        # ran that path, which left its cue starts and `duration_ms` describing estimated
        # durations while the cues themselves carried real audio. Windows computed from that
        # production then pointed at the wrong moment — that is how the result card ended up
        # outside a "victory" export range.
        cues, duration = retime_for_audio(cues, production.profile)
        # Speech is optional presentation media. Keep captions and the production
        # exportable when an online provider is unavailable, even if every cue failed.
        status = ProductionStatus.PARTIAL if failures else ProductionStatus.READY
        overrides = {**production.overrides, "speech_failures": failures}
        updated = production.model_copy(
            update={
                "cues": cues,
                "duration_ms": duration,
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
        reference_hash = self._reference_audio_hash(preset.reference_audio_path)
        openai_kinds = (SpeechProviderKind.OPENAI, SpeechProviderKind.OPENAI_COMPATIBLE)
        default_model = self.settings.speech_openai_model if preset.provider in openai_kinds else ""
        speech = SpeechRequest(
            text=text,
            provider=preset.provider,
            model=preset.model or default_model,
            voice=preset.voice,
            speed=preset.speed,
            language=preset.language,
            instructions=preset.instructions,
            reference_audio_path=preset.reference_audio_path,
            reference_audio_sha256=reference_hash,
            reference_text=preset.reference_text,
            x_vector_only_mode=preset.x_vector_only_mode,
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

    def _reference_audio_hash(self, relative_path: str | None) -> str | None:
        if not relative_path:
            return None
        root = self.settings.speech_qwen_reference_root.resolve()
        path = (root / relative_path).resolve()
        if root not in path.parents:
            raise ValueError("voice reference path escapes the configured voice root")
        if not path.is_file():
            raise ValueError(f"voice reference audio does not exist: {relative_path}")
        return hashlib.sha256(path.read_bytes()).hexdigest()

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
        artifacts_by_commentary: dict[str, SpeechArtifact] = {}
        for cue in cues:
            artifact = generated.get(cue.id)
            if artifact and cue.track is Track.COMMENTARY:
                artifacts_by_commentary[cue.id] = artifact
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
                        speaker=cue.speaker,
                        payload=artifact.model_dump(mode="json"),
                    )
                )
            elif cue.track is not Track.VOICE:
                result.append(cue)
        normalized: list[ProductionCue] = []
        for cue in result:
            if cue.track is Track.CAPTIONS:
                commentary = next(
                    (
                        item
                        for item in result
                        if item.track is Track.COMMENTARY
                        and item.event_sequence == cue.event_sequence
                        and (item.speaker or item.side) == (cue.speaker or cue.side)
                    ),
                    None,
                )
                artifact = artifacts_by_commentary.get(commentary.id) if commentary else None
                if artifact and commentary:
                    normalized.append(
                        cue.model_copy(
                            update={
                                "duration_ms": artifact.duration_ms,
                                "payload": {
                                    "segments": [
                                        segment.model_dump(mode="json")
                                        for segment in segment_caption(
                                            str(commentary.payload["text"]),
                                            maximum=production.profile.caption_max_characters,
                                            duration_ms=artifact.duration_ms,
                                        )
                                    ]
                                },
                            }
                        )
                    )
                    continue
            normalized.append(cue)
        return tuple(sorted(normalized, key=lambda cue: (cue.start_ms, cue.track.value, cue.id)))
