from __future__ import annotations

import json

from .models import BattleAction, BattleState, Side

PROMPT_SCHEMA_VERSION = "3.0"
PROMPT_TEMPLATE_VERSION = "battle-standard-v1"
INFORMATION_PROFILE = "standard"
MAX_PUBLIC_HISTORY = 12


def build_agent_prompt(
    state: BattleState, legal_actions: tuple[BattleAction, ...], side: Side
) -> str:
    """Build a bounded prompt from one player's normalized Showdown perspective."""
    bounded_state = state.model_copy(
        update={"public_history": state.public_history[-MAX_PUBLIC_HISTORY:]}
    )
    payload = {
        "prompt_schema_version": PROMPT_SCHEMA_VERSION,
        "prompt_template_version": PROMPT_TEMPLATE_VERSION,
        "information_profile": INFORMATION_PROFILE,
        "role": side.value,
        "objective": "Choose the best legal action for this Pokemon battle turn.",
        "turn": state.turn,
        "battle": bounded_state.model_dump(mode="json"),
        "legal_actions": [action.model_dump(mode="json") for action in legal_actions],
        "response_schema": {
            "action": "one exact id from legal_actions",
            "commentary": "short public explanation, maximum 1000 characters",
        },
        "rules": [
            "Use only information in this prompt.",
            "Return one JSON object and no markdown.",
            "Never construct a Pokemon Showdown command.",
            "Do not reveal hidden reasoning; commentary states only the action and a brief reason.",
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True)
