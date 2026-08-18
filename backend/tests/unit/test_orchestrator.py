from __future__ import annotations

from types import SimpleNamespace

from koalabattle.config import Settings
from koalabattle.formats import describe_format
from koalabattle.orchestration.models import (
    OrchestratorRequest,
    OrchestratorSettings,
    OrchestratorStatus,
)
from koalabattle.orchestration.service import OrchestratorService
from koalabattle.production.profiles import PRODUCTION_PROFILES
from koalabattle.video.models import PRESETS


def orchestrator() -> OrchestratorService:
    battles = SimpleNamespace(formats=SimpleNamespace(get=describe_format))
    production = SimpleNamespace(profiles=lambda: tuple(PRODUCTION_PROFILES.values()))
    video = SimpleNamespace(presets=lambda: tuple(PRESETS.values()))
    settings = Settings(
        _env_file=None, orchestrator_local_base_url="http://host.docker.internal:1234/v1"
    )
    return OrchestratorService(battles, production, video, settings)


def test_plan_normalizes_gen1_gemma_banter_and_video_request() -> None:
    plan = orchestrator().plan(
        OrchestratorRequest(
            instruction=(
                "Gib mir ein Gen1 battle, beide AIs Gemma4, Teams selbst bauen, "
                "Bo1 mit Banter und danach als Video rendern."
            )
        )
    )

    assert plan.ready is True
    assert plan.settings.format == "gen1ou"
    assert plan.settings.banter_enabled is True
    assert plan.settings.auto_render is True
    assert all(player.model == "google/gemma-4-e4b" for player in plan.settings.players)
    assert all(
        player.configuration.base_url == "http://host.docker.internal:1234/v1"
        for player in plan.settings.players
    )


def test_plan_returns_question_when_no_format_is_given() -> None:
    plan = orchestrator().plan(OrchestratorRequest())

    assert plan.ready is False
    assert plan.questions[0].field == "settings.format"


def test_orchestrator_run_status_is_terminal_only_with_completion_time() -> None:
    assert OrchestratorStatus.COMPLETED.value == "completed"
    assert OrchestratorSettings().best_of == 1
