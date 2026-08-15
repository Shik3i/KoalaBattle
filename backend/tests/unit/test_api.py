from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from koalabattle.agents import RandomAgent
from koalabattle.api.main import create_app
from koalabattle.config import Settings
from koalabattle.core.models import AgentRequest, BattleEvent, MatchConfig
from koalabattle.storage import BattleRepository, Database


def create_test_schema(database_url: str) -> None:
    async def create() -> None:
        database = Database(database_url)
        await database.create_schema()
        await database.close()

    asyncio.run(create())


def test_overlay_clients_can_restore_historical_match_and_stream_snapshot(
    tmp_path: Path, match_config: MatchConfig, agent_request: AgentRequest
) -> None:
    database_path = tmp_path / "overlay.db"
    database_url = f"sqlite+aiosqlite:///{database_path}"
    match_id = agent_request.match_id

    async def seed() -> None:
        database = Database(database_url)
        await database.create_schema()
        repository = BattleRepository(database)
        await repository.create_match(
            match_id,
            match_config,
            engine="test-engine",
            engine_version="1",
            showdown_version="test-sha",
            poke_env_version="0.15.0",
        )
        await repository.append_event(
            BattleEvent(match_id=match_id, sequence=0, turn=1, event_type="turn_started")
        )
        decision = (await RandomAgent(1).decide(agent_request)).model_copy(
            update={
                "raw_response": "sk-secret-in-raw-audit",
                "provider_metadata": {"authorization": "Bearer secret-metadata"},
            }
        )
        await repository.record_decision(agent_request, decision)
        await database.close()

    asyncio.run(seed())
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        asset_root=tmp_path / "assets",
    )
    with TestClient(create_app(settings)) as client:
        response = client.get(f"/api/matches/{match_id}")
        assert response.status_code == 200
        assert response.json()["events"][0]["event_type"] == "turn_started"
        assert "sk-secret-in-raw-audit" in response.text
        presentation = client.get(f"/api/matches/{match_id}/presentation")
        assert presentation.status_code == 200
        assert "sk-secret-in-raw-audit" not in presentation.text
        assert "secret-metadata" not in presentation.text
        with client.websocket_connect(f"/api/matches/{match_id}/stream") as websocket:
            snapshot = websocket.receive_json()
            assert snapshot["kind"] == "snapshot"
            assert snapshot["match"]["id"] == str(match_id)
            assert "sk-secret-in-raw-audit" not in str(snapshot)


def test_asset_status_and_resolution_api(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    front = assets / "pokemon" / "front"
    front.mkdir(parents=True)
    (front / "mrmime.png").write_bytes(b"png")
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'assets.db'}",
        asset_root=assets,
    )
    create_test_schema(settings.database_url)
    with TestClient(create_app(settings)) as client:
        status = client.get("/api/assets/status")
        assert status.status_code == 200
        assert status.json()["pokemon_species"] == 1
        resolution = client.get("/api/assets/resolve/pokemon/Mr.%20Mime")
        assert resolution.status_code == 200
        assert resolution.json()["relative_path"] == "pokemon/front/mrmime.png"


def test_provider_status_never_returns_credentials_and_missing_key_is_actionable(
    tmp_path: Path,
) -> None:
    secret = "sk-secret-value-that-must-not-leak"
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'providers.db'}",
        openai_api_key=secret,
    )
    create_test_schema(settings.database_url)
    with TestClient(create_app(settings)) as client:
        status_response = client.get("/api/providers")
        assert status_response.status_code == 200
        serialized = status_response.text
        assert secret not in serialized
        openai_status = next(
            item for item in status_response.json()["providers"] if item["id"] == "openai"
        )
        assert openai_status["configured"] is True

        missing = client.post(
            "/api/matches",
            json={
                "player1": {
                    "display_name": "Missing key",
                    "agent_type": "api",
                    "provider": "anthropic",
                    "model": "claude-test",
                },
                "player2": {"display_name": "Local", "agent_type": "random"},
            },
        )
        assert missing.status_code == 422
        assert "KOALABATTLE_ANTHROPIC_API_KEY" in missing.json()["detail"]


def test_tournament_crud_uses_summaries_and_sanitized_presentation(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'tournaments.db'}",
        enable_fake_provider=True,
    )
    create_test_schema(settings.database_url)
    payload = {
        "name": "API genericity",
        "format": "single_elimination",
        "best_of": 1,
        "max_concurrent_matches": 2,
        "match_template": {
            "engine": "pokemon-showdown",
            "format": "gen9randombattle",
            "presentation": {"private_note": "must-not-leak"},
        },
        "participants": [
            {
                "display_name": f"Participant {index}",
                "seed": index,
                "agent": {
                    "agent_type": "api",
                    "provider": "fake",
                    "model": "safe-model-name",
                },
            }
            for index in range(1, 5)
        ],
    }
    with TestClient(create_app(settings)) as client:
        created = client.post("/api/tournaments", json=payload)
        assert created.status_code == 201, created.text
        tournament_id = created.json()["id"]
        summaries = client.get("/api/tournaments?limit=1&offset=0")
        assert summaries.status_code == 200
        assert summaries.json() == [
            {
                "id": tournament_id,
                "name": "API genericity",
                "format": "single_elimination",
                "status": "draft",
                "participant_count": 4,
                "series_count": 0,
                "completed_series": 0,
                "current_round": 0,
                "created_at": created.json()["created_at"],
                "updated_at": created.json()["updated_at"],
            }
        ]
        presentation = client.get(f"/api/tournaments/{tournament_id}/presentation")
        assert presentation.status_code == 200
        assert "must-not-leak" not in presentation.text
        assert "safe-model-name" in presentation.text
