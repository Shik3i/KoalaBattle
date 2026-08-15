from __future__ import annotations

from typing import Any

from .models import TournamentArchive


def presentation_tournament(archive: TournamentArchive) -> dict[str, Any]:
    payload = archive.model_dump(mode="json")
    payload["match_template"] = {
        "schema_version": archive.match_template.schema_version,
        "engine": archive.match_template.engine,
        "format": archive.match_template.format,
        "generation": archive.match_template.generation,
    }
    payload["participants"] = [
        {
            "id": str(participant.id),
            "display_name": participant.display_name,
            "seed": participant.seed,
            "agent": {
                "agent_type": participant.agent.agent_type.value,
                "provider": participant.agent.provider,
                "model": participant.agent.model,
            },
        }
        for participant in archive.participants
    ]
    payload.pop("error", None)
    return payload
