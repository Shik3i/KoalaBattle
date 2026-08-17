"""Neutral provider marks.

KoalaBattle bundles **no** third-party logo files. The OpenAI, Google, Anthropic and
DeepSeek word marks and logos are trademarks of their respective owners, and their brand
guidelines govern use; redistributing those files inside an MIT-licensed repository is not
something this project can grant, so it does not.

Instead each provider family gets an original generated badge: a short wordmark drawn by
the compositor in KoalaBattle's own shapes and colours. Nothing here is derived from a
third-party asset, and the branding system is fully functional without any logo file. A
user who has the rights to a specific logo can always upload it locally; those uploads stay
outside Git (see ``docs/ASSETS.md``).
"""

from __future__ import annotations

from typing import NamedTuple


class ProviderMark(NamedTuple):
    id: str
    label: str
    accent: str
    secondary_accent: str


MARKS: dict[str, ProviderMark] = {
    mark.id: mark
    for mark in (
        ProviderMark("gpt", "GPT", "#5fe6b0", "#0f7f5c"),
        ProviderMark("gemini", "GEMINI", "#6fa8ff", "#1f4fb8"),
        ProviderMark("claude", "CLAUDE", "#ff9a62", "#b8532a"),
        ProviderMark("deepseek", "DEEPSEEK", "#7d8dff", "#3a45b5"),
        ProviderMark("local", "LOCAL", "#b9c6cf", "#5c6b76"),
        ProviderMark("manual", "MANUAL", "#ffd76a", "#a8801c"),
        ProviderMark("random", "RANDOM", "#c6a6ff", "#6b45b8"),
        ProviderMark("koala", "KOALA", "#7dffae", "#128a56"),
    )
}

_BY_PROVIDER = {
    "openai": "gpt",
    "gemini": "gemini",
    "anthropic": "claude",
    "deepseek": "deepseek",
    "openai-compatible": "local",
    "fake": "local",
}
_BY_AGENT_TYPE = {"manual": "manual", "random": "random"}


def mark_for(agent_type: str, provider: str | None) -> ProviderMark:
    """The default mark for a player, used when no branding has been chosen.

    Agent type wins over provider so a Manual Web Chat player reads as "MANUAL" rather
    than as whichever provider happens to be configured behind it. Users override this
    per production; the default only has to be honest, not clever.
    """
    key = _BY_AGENT_TYPE.get(agent_type) or _BY_PROVIDER.get(provider or "", "local")
    return MARKS[key]


def mark_ids() -> tuple[str, ...]:
    return tuple(MARKS)
