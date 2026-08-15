from __future__ import annotations

from typing import Any

from koalabattle.core.models import DecisionRecord, MatchArchive


def public_decision(record: DecisionRecord) -> dict[str, Any]:
    decision = record.decision
    return {
        "id": record.id,
        "decision": decision.model_dump(
            mode="json",
            exclude={"raw_response", "provider_metadata", "error_detail"},
        ),
    }


def presentation_archive(archive: MatchArchive) -> dict[str, Any]:
    payload = archive.model_dump(
        mode="json",
        exclude={"raw_showdown_log", "decisions"},
    )
    payload["decisions"] = [public_decision(record) for record in archive.decisions]
    return payload
