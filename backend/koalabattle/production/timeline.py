from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

from koalabattle.core.models import BattleEvent, MatchArchive, MatchStatus

from .models import (
    CaptionSegment,
    DirectorState,
    NarratorSettings,
    ProductionCue,
    ProductionProfile,
    ProductionStatus,
    ProductionTimeline,
    Track,
)
from .narrator import NarratorCandidate, build_narrator_plan, event_priority_score

_EVENT_DURATIONS = {
    "move_used": 520,
    "move_missed": 420,
    "damage": 420,
    "healing": 460,
    "critical_hit": 520,
    "status_applied": 420,
    "status_removed": 360,
    "super_effective": 420,
    "resisted": 360,
    "immune": 420,
    "weather_changed": 520,
    "terrain_started": 520,
    "terrain_ended": 360,
    "side_condition_started": 420,
    "side_condition_ended": 360,
    "pokemon_switched": 620,
    "pokemon_fainted": 760,
    "agent_decision": 340,
    "turn_started": 240,
    "state_snapshot": 100,
    "battle_finished": 900,
}
_SFX_EVENTS = {
    "move_used": "action",
    "move_missed": "miss",
    "damage": "impact",
    "healing": "heal",
    "critical_hit": "critical",
    "status_applied": "status",
    "super_effective": "impact",
    "immune": "miss",
    "weather_changed": "field",
    "terrain_started": "field",
    "side_condition_started": "field",
    "pokemon_switched": "switch",
    "pokemon_fainted": "faint",
    "battle_finished": "result",
}
_TERMINAL = {
    MatchStatus.COMPLETED,
    MatchStatus.CANCELLED,
    MatchStatus.FAILED,
    MatchStatus.INTERRUPTED,
}
# These events are useful for the live inspector, but they are not viewer-facing beats.
# Keeping them in a production timeline made every internal stream update consume a visual
# duration and an event gap in exported video.
_OMITTED_FROM_PRODUCTION = frozenset({"agent_progress", "agent_state", "showdown_message"})


def public_commentary(text: object, maximum: int) -> str:
    if not isinstance(text, str):
        return ""
    return " ".join(text.split())[:maximum].rstrip()


def segment_caption(text: str, *, maximum: int, duration_ms: int) -> tuple[CaptionSegment, ...]:
    words = text.split()
    if not words:
        return ()
    chunks: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > maximum:
            chunks.append(current)
            current = word
        else:
            current = candidate
        if current.endswith((".", "!", "?")) and len(current) >= maximum // 2:
            chunks.append(current)
            current = ""
    if current:
        chunks.append(current)
    weights = [max(1, len(re.sub(r"\s+", "", chunk))) for chunk in chunks]
    total = sum(weights)
    cursor = 0
    segments: list[CaptionSegment] = []
    for index, (chunk, weight) in enumerate(zip(chunks, weights, strict=True)):
        end = (
            duration_ms
            if index == len(chunks) - 1
            else cursor + round(duration_ms * weight / total)
        )
        end = max(cursor + 1, end)
        segments.append(CaptionSegment(text=chunk, start_ms=cursor, end_ms=end))
        cursor = end
    return tuple(segments)


def cues_for_event(
    event: BattleEvent,
    profile: ProductionProfile,
    *,
    start_ms: int,
    timeline_turn: int | None = None,
    narrator_candidate: NarratorCandidate | None = None,
    narrator_settings: NarratorSettings | None = None,
) -> tuple[tuple[ProductionCue, ...], int]:
    """Create only cues owned by one persisted event; IDs make retries idempotent."""
    cue_turn = event.turn if timeline_turn is None else timeline_turn
    if event.event_type in _OMITTED_FROM_PRODUCTION:
        return (), 0
    # Snapshots are state checkpoints for deterministic replay. They must be applied at the
    # current clock position, but they must not create a visible beat or an inter-event pause.
    if event.event_type == "state_snapshot":
        return (
            ProductionCue(
                id=f"event-{event.sequence}-state",
                track=Track.VISUAL,
                kind=event.event_type,
                start_ms=start_ms,
                duration_ms=0,
                event_sequence=event.sequence,
                turn=cue_turn,
            ),
        ), 0
    duration = _EVENT_DURATIONS.get(event.event_type, 120)
    base = f"event-{event.sequence}"
    cues = [
        ProductionCue(
            id=f"{base}-visual",
            track=Track.VISUAL,
            kind=event.event_type,
            start_ms=start_ms,
            duration_ms=duration,
            event_sequence=event.sequence,
            turn=cue_turn,
            payload={"priority": event_priority_score(event, narrator_candidate)},
        )
    ]
    if profile.sfx_enabled and event.event_type in _SFX_EVENTS:
        cues.append(
            ProductionCue(
                id=f"{base}-sfx",
                track=Track.SFX,
                kind=_SFX_EVENTS[event.event_type],
                start_ms=start_ms,
                duration_ms=min(duration, 500),
                event_sequence=event.sequence,
                turn=cue_turn,
                payload={"sound_pack": "generic-default"},
            )
        )
    if event.event_type == "agent_decision":
        side = event.payload.get("side")
        public_text = event.payload.get("public_text")
        if not isinstance(public_text, str):
            public_text = " ".join(
                item
                for item in (
                    event.payload.get("commentary"),
                    event.payload.get("banter"),
                )
                if isinstance(item, str) and item.strip()
            )
        commentary = public_commentary(
            public_text, profile.commentary_max_characters
        )
        if commentary and side in {"p1", "p2"}:
            estimated = max(650, min(12_000, len(commentary) * 55))
            cues.append(
                ProductionCue(
                    id=f"{base}-commentary",
                    track=Track.COMMENTARY,
                    kind="public-agent-commentary",
                    start_ms=start_ms,
                    duration_ms=estimated,
                    event_sequence=event.sequence,
                    turn=cue_turn,
                    side=side,
                    speaker=side,
                    payload={"text": commentary},
                )
            )
            if profile.captions_enabled:
                cues.append(
                    ProductionCue(
                        id=f"{base}-captions",
                        track=Track.CAPTIONS,
                        kind="agent-commentary",
                        start_ms=start_ms,
                        duration_ms=estimated,
                        event_sequence=event.sequence,
                        turn=cue_turn,
                        side=side,
                        speaker=side,
                        payload={
                            "segments": [
                                segment.model_dump(mode="json")
                                for segment in segment_caption(
                                    commentary,
                                    maximum=profile.caption_max_characters,
                                    duration_ms=estimated,
                                )
                            ]
                        },
                    )
                )
            if profile.wait_for_speech:
                duration = max(duration, estimated)
    if narrator_candidate is not None:
        narrator_duration = narrator_candidate.duration_ms
        cues.append(
            ProductionCue(
                id=f"{base}-narrator-commentary",
                track=Track.COMMENTARY,
                kind="narrator-highlight",
                start_ms=start_ms,
                duration_ms=narrator_duration,
                event_sequence=event.sequence,
                turn=cue_turn,
                speaker="narrator",
                payload={
                    "text": narrator_candidate.text,
                    "rule_id": narrator_candidate.rule_id,
                    "priority": narrator_candidate.priority,
                },
            )
        )
        if profile.captions_enabled and (
            narrator_settings is None or narrator_settings.captions_enabled
        ):
            cues.append(
                ProductionCue(
                    id=f"{base}-narrator-captions",
                    track=Track.CAPTIONS,
                    kind="narrator-commentary",
                    start_ms=start_ms,
                    duration_ms=narrator_duration,
                    event_sequence=event.sequence,
                    turn=cue_turn,
                    speaker="narrator",
                    payload={
                        "segments": [
                            segment.model_dump(mode="json")
                            for segment in segment_caption(
                                narrator_candidate.text,
                                maximum=profile.caption_max_characters,
                                duration_ms=narrator_duration,
                            )
                        ]
                    },
                )
            )
        if profile.wait_for_speech:
            duration = max(duration, narrator_duration)
    return tuple(cues), duration


def final_cues(
    archive: MatchArchive,
    *,
    start_ms: int,
    result_duration_ms: int = 1_800,
    outro_duration_ms: int = 600,
) -> tuple[ProductionCue, ...]:
    return (
        ProductionCue(
            id="director-result",
            track=Track.DIRECTOR,
            kind="result",
            start_ms=start_ms,
            duration_ms=result_duration_ms,
            payload={
                "winner": archive.winner.value if archive.winner else None,
                "turns": archive.turns,
                "status": archive.status.value,
            },
        ),
        ProductionCue(
            id="director-outro",
            track=Track.DIRECTOR,
            kind="outro",
            start_ms=start_ms + result_duration_ms,
            duration_ms=outro_duration_ms,
        ),
    )


def _group_turn(group: list[ProductionCue]) -> int | None:
    turns = {cue.turn for cue in group if cue.turn is not None and cue.turn > 0}
    return min(turns) if turns else None


def _finish_turn(
    cursor: int,
    turn_start: int | None,
    profile: ProductionProfile,
    *,
    priority_score: int,
    gap: bool,
) -> int:
    if turn_start is None:
        return cursor
    if priority_score <= 35:
        target = profile.quiet_turn_target_ms or max(1_000, round(profile.turn_target_ms * 0.42))
    elif priority_score >= 70:
        target = profile.highlight_turn_target_ms or profile.turn_target_ms
    else:
        target = profile.turn_target_ms
    cursor = max(cursor, turn_start + target)
    return cursor + profile.turn_pause_ms if gap else cursor


def _cue_priority(cue: ProductionCue) -> int:
    value = cue.payload.get("priority")
    return round(value) if isinstance(value, int | float) else 0


def retime_for_audio(
    cues: tuple[ProductionCue, ...], profile: ProductionProfile
) -> tuple[tuple[ProductionCue, ...], int]:
    """Normalize the final clock after real cached speech durations are known."""
    result: list[ProductionCue] = []
    intro = next((cue for cue in cues if cue.id == "director-intro"), None)
    cursor = 0
    if intro is not None:
        result.append(intro.model_copy(update={"start_ms": 0}))
        cursor = intro.duration_ms
    sequences = sorted({cue.event_sequence for cue in cues if cue.event_sequence is not None})
    active_turn: int | None = None
    turn_start: int | None = None
    turn_priority = 0
    for sequence in sequences:
        group = [cue for cue in cues if cue.event_sequence == sequence]
        event_turn = _group_turn(group)
        if event_turn is not None and event_turn != active_turn:
            if active_turn is not None:
                cursor = _finish_turn(
                    cursor, turn_start, profile, priority_score=turn_priority, gap=True
                )
            active_turn = event_turn
            turn_start = cursor
            turn_priority = 0
        turn_priority = max(turn_priority, max((_cue_priority(cue) for cue in group), default=0))
        if not any(cue.duration_ms > 0 for cue in group):
            # State checkpoints are instantaneous and must not add a synthetic pause to the
            # clock. They remain at the current cursor so the browser can apply their state.
            result.extend(cue.model_copy(update={"start_ms": cursor}) for cue in group)
            continue
        visual_duration = max(
            (cue.duration_ms for cue in group if cue.track is Track.VISUAL), default=0
        )
        duration = (
            max((cue.duration_ms for cue in group), default=visual_duration)
            if profile.wait_for_speech
            else visual_duration
        )
        result.extend(cue.model_copy(update={"start_ms": cursor}) for cue in group)
        cursor += duration
    if active_turn is not None:
        cursor = _finish_turn(
            cursor, turn_start, profile, priority_score=turn_priority, gap=False
        )
    result_cue = next((cue for cue in cues if cue.id == "director-result"), None)
    outro = next((cue for cue in cues if cue.id == "director-outro"), None)
    if result_cue is not None:
        result.append(result_cue.model_copy(update={"start_ms": cursor}))
        cursor += result_cue.duration_ms
    if outro is not None:
        result.append(outro.model_copy(update={"start_ms": cursor}))
        cursor += outro.duration_ms
    known = {cue.id for cue in result}
    result.extend(cue for cue in cues if cue.id not in known)
    return tuple(sorted(result, key=lambda cue: (cue.start_ms, cue.track.value, cue.id))), cursor


def build_timeline(
    archive: MatchArchive,
    profile: ProductionProfile,
    *,
    production_id: UUID | None = None,
    revision: int = 1,
    voices: dict[str, str] | None = None,
    narrator: NarratorSettings | None = None,
) -> ProductionTimeline:
    now = datetime.now(UTC)
    cues: list[ProductionCue] = []
    cursor = 0
    if profile.intro_enabled:
        cues.append(
            ProductionCue(
                id="director-intro",
                track=Track.DIRECTOR,
                kind="match-intro",
                start_ms=0,
                duration_ms=profile.intro_duration_ms,
                payload={
                    "players": [player.display_name for player in archive.config.players],
                    "format": archive.config.format,
                },
            )
        )
        cursor = profile.intro_duration_ms
    active_turn: int | None = None
    turn_start: int | None = None
    turn_priority = 0
    narrator_settings = narrator or NarratorSettings()
    narrator_plan = build_narrator_plan(archive.events, narrator_settings)
    for event in archive.events:
        # Showdown can persist the next state snapshot before the remaining action events
        # from the current turn. Only `turn_started` is a reliable forward clock boundary;
        # using every event.turn made the timeline jump 1 -> 2 -> 1 and restart turn slots.
        event_turn = (
            event.turn if event.event_type == "turn_started" and event.turn > 0 else active_turn
        )
        if event_turn is not None and event_turn != active_turn:
            if active_turn is not None:
                cursor = _finish_turn(
                    cursor, turn_start, profile, priority_score=turn_priority, gap=True
                )
            active_turn = event_turn
            turn_start = cursor
            turn_priority = 0
        narrator_candidate = narrator_plan.get(event.sequence)
        turn_priority = max(turn_priority, event_priority_score(event, narrator_candidate))
        event_cues, duration = cues_for_event(
            event,
            profile,
            start_ms=cursor,
            timeline_turn=active_turn,
            narrator_candidate=narrator_candidate,
            narrator_settings=narrator_settings,
        )
        if event_cues:
            cues.extend(event_cues)
            cursor += duration
    if active_turn is not None:
        cursor = _finish_turn(
            cursor, turn_start, profile, priority_score=turn_priority, gap=False
        )
    terminal = archive.status in _TERMINAL
    if terminal:
        cues.extend(
            final_cues(
                archive,
                start_ms=cursor,
                result_duration_ms=profile.result_duration_ms,
                outro_duration_ms=profile.outro_duration_ms,
            )
        )
        cursor += profile.result_duration_ms + profile.outro_duration_ms
    final_state = DirectorState.RESULT if archive.winner is not None else DirectorState.ENDED
    voice_assignments = dict(voices or {"p1": "edge-neural-p1", "p2": "edge-neural-p2"})
    if narrator_settings.enabled:
        voice_assignments.setdefault("narrator", narrator_settings.voice_preset_id)
    return ProductionTimeline(
        id=production_id or uuid4(),
        match_id=archive.id,
        profile=profile,
        revision=revision,
        status=ProductionStatus.FINALIZED if terminal else ProductionStatus.LIVE,
        director_state=DirectorState.PRE_SHOW if profile.intro_enabled else final_state,
        cues=tuple(sorted(cues, key=lambda cue: (cue.start_ms, cue.track.value, cue.id))),
        voice_assignments=voice_assignments,
        narrator=narrator_settings,
        duration_ms=cursor,
        finalized_at=now if terminal else None,
        created_at=now,
        updated_at=now,
    )
