from __future__ import annotations

from dataclasses import dataclass

from koalabattle.core.models import (
    AgentContextSnapshot,
    ContextMetrics,
    ContextProfileId,
    PromptProfileId,
)

from .prompt_renderer import PROMPT_RENDERER_VERSION, RenderedPrompt, render

PROMPT_SCHEMA_VERSION = "7.0"
PROMPT_TEMPLATE_VERSION = PROMPT_RENDERER_VERSION
OUTPUT_SCHEMA_VERSION = "battle-decision-v3"


@dataclass(frozen=True)
class PromptProfile:
    id: PromptProfileId
    name: str
    version: str
    system_policy: str


@dataclass(frozen=True)
class ContextProfile:
    id: ContextProfileId
    version: str
    estimated_token_budget: int
    maximum_history_events: int


#: Both profiles state semantically identical rules so a benchmark stays fair; only the
#: context budget below differs, and it differs identically for both players.
_SHARED_POLICY = (
    "Act as the assigned player and try to win. Treat the supplied snapshot as the only "
    "source of current match facts, and use general Pokemon knowledge freely. You may "
    "predict what the opponent is likely to do, but never state unrevealed information as "
    "fact. Choose exactly one supplied legal action ID and return short public commentary."
)

PROMPT_PROFILES = {
    PromptProfileId.STANDARD_COMPETITIVE: PromptProfile(
        id=PromptProfileId.STANDARD_COMPETITIVE,
        name="Standard Competitive",
        version="3.0",
        system_policy=_SHARED_POLICY,
    ),
    PromptProfileId.BENCHMARK_FAIR: PromptProfile(
        id=PromptProfileId.BENCHMARK_FAIR,
        name="Benchmark Fair",
        version="3.0",
        system_policy=_SHARED_POLICY,
    ),
}

CONTEXT_PROFILES = {
    ContextProfileId.STANDARD: ContextProfile(
        id=ContextProfileId.STANDARD,
        version="2.0",
        estimated_token_budget=4_000,
        maximum_history_events=10,
    ),
    ContextProfileId.COMPACT: ContextProfile(
        id=ContextProfileId.COMPACT,
        version="2.0",
        estimated_token_budget=2_400,
        maximum_history_events=5,
    ),
}


def render_prompt_messages(snapshot: AgentContextSnapshot) -> tuple[RenderedPrompt, ContextMetrics]:
    """Render the system/user pair plus deterministic size metrics for one decision.

    History is trimmed first because it is the least valuable context; own-team and move
    information is never dropped, since an agent that cannot see its bench cannot switch well.
    """
    context_profile = CONTEXT_PROFILES[snapshot.context_profile_id]
    history = list(snapshot.recent_events[-context_profile.maximum_history_events :])
    prompt = render(snapshot, tuple(history))
    while history and estimate_tokens(prompt.combined) > context_profile.estimated_token_budget:
        history.pop(0)
        prompt = render(snapshot, tuple(history))
    metrics = ContextMetrics(
        rendered_characters=len(prompt.combined),
        estimated_tokens=estimate_tokens(prompt.combined),
        history_event_count=len(history),
        knowledge_entries=len(snapshot.knowledge.known_opponent),
        context_profile_version=snapshot.context_profile_version,
        history_policy_version=snapshot.history_policy_version,
    )
    return prompt, metrics


def render_agent_prompt(snapshot: AgentContextSnapshot) -> tuple[str, ContextMetrics]:
    """Render one provider-independent, self-contained prompt suitable for a fresh web chat."""
    prompt, metrics = render_prompt_messages(snapshot)
    return prompt.combined, metrics


def estimate_tokens(value: str) -> int:
    return (len(value) + 3) // 4
