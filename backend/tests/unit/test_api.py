from __future__ import annotations

import asyncio
from pathlib import Path
from stat import S_IMODE

from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from koalabattle.agents import RandomAgent
from koalabattle.agents.providers import DeepSeekProvider
from koalabattle.api.main import create_app
from koalabattle.config import Settings
from koalabattle.core.models import (
    AgentRequest,
    BattleEvent,
    MatchConfig,
    PlayerConfig,
    ProviderKind,
    Side,
)
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
        renderer_config = {
            "version": "2.0",
            "layout": "overlay-landscape",
            "theme": "pokemon-route",
            "preset": "live",
            "playbackSpeed": 1,
            "commentaryMode": "latest",
            "showBattleLog": True,
            "showTurn": True,
            "showAgentState": True,
            "transparentBackground": False,
            "animatedSprites": True,
            "effects": "standard",
            "moveEffectSkin": "broadcast",
            "reducedMotion": False,
            "showDamageNumbers": True,
            "nearSide": "p1",
            "showTeamRoster": True,
            "hudScale": 1,
        }
        broadcast = client.post(
            f"/api/matches/{match_id}/renderer-config", json=renderer_config
        )
        assert broadcast.status_code == 202
        invalid_speed = client.post(
            f"/api/matches/{match_id}/renderer-config",
            json={**renderer_config, "playbackSpeed": 1.5},
        )
        assert invalid_speed.status_code == 422
        boolean_speed = client.post(
            f"/api/matches/{match_id}/renderer-config",
            json={**renderer_config, "playbackSpeed": True},
        )
        assert boolean_speed.status_code == 422
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
    audio = assets / "audio"
    audio.mkdir(parents=True)
    (audio / "impact-01.wav").write_bytes(b"RIFF-local-test")
    effects = assets / "effects" / "showdown-cc0"
    effects.mkdir(parents=True)
    (effects / "fireball.png").write_bytes(b"\x89PNG\r\n\x1a\nlocal-test")
    trainers = assets / "trainers"
    trainers.mkdir()
    (trainers / "brockgen1rb.png").write_bytes(b"\x89PNG\r\n\x1a\ntrainer-test")
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
        sfx = client.get("/api/assets/audio/impact-01")
        assert sfx.status_code == 200
        assert sfx.content == b"RIFF-local-test"
        move_effect = client.get("/api/assets/effects/fireball")
        assert move_effect.status_code == 200
        assert move_effect.content.startswith(b"\x89PNG")
        trainer = client.get("/api/assets/trainers/brock-gen1rb")
        assert trainer.status_code == 200
        assert trainer.content.endswith(b"trainer-test")
        assert client.get("/api/assets/trainers/missing").status_code == 404
        assert client.get("/api/assets/effects/not-installed").status_code == 404
        assert client.get("/api/assets/audio/../secret").status_code in {404, 400}


def test_persona_profiles_are_fictional_and_available_for_voice_setup(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'personas.db'}",
    )
    create_test_schema(settings.database_url)
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/production/personas")
        assert response.status_code == 200
        personas = response.json()["personas"]
        assert {persona["id"] for persona in personas} == {
            "fictional-firebrand",
            "measured-statesman",
            "arena-broadcast",
        }
        assert all(
            "Do not imitate any real person" in persona["instructions"] for persona in personas
        )


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


def test_browser_provider_configuration_enables_deepseek_without_leaking_key(
    tmp_path: Path, match_config: MatchConfig
) -> None:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime-provider.db'}",
    )
    create_test_schema(settings.database_url)
    secret = "sk-deepseek-runtime-secret"
    with TestClient(create_app(settings)) as client:
        configured = client.post(
            "/api/providers/configure",
            json={"provider": "deepseek", "api_key": secret},
        )
        assert configured.status_code == 200, configured.text
        assert configured.json() == {
            "provider": "deepseek",
            "configured": True,
            "source": "runtime",
        }
        status_response = client.get("/api/providers")
        assert secret not in status_response.text
        deepseek = next(
            item for item in status_response.json()["providers"] if item["id"] == "deepseek"
        )
        assert deepseek["configured"] is True
        assert deepseek["default_model"] == "deepseek-v4-flash"
        assert deepseek["known_models"] == ["deepseek-v4-flash", "deepseek-v4-pro"]
        service = client.app.state.service
        player = PlayerConfig(
            side=Side.P1,
            display_name="DeepSeek",
            agent_type="api",
            provider=ProviderKind.DEEPSEEK.value,
            model="deepseek-v4-flash",
        )
        assert isinstance(service._provider_for(player), DeepSeekProvider)


def test_provider_configuration_rejects_metadata_and_non_http_base_urls(
    tmp_path: Path, match_config: MatchConfig
) -> None:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime-provider-ssrf.db'}",
    )
    create_test_schema(settings.database_url)
    with TestClient(create_app(settings)) as client:
        # The cloud-metadata link-local range is never a legitimate provider
        # endpoint and is the single most common real-world SSRF target.
        metadata_response = client.post(
            "/api/providers/configure",
            json={
                "provider": "openai-compatible",
                "base_url": "http://169.254.169.254/latest/meta-data/",
            },
        )
        assert metadata_response.status_code == 422, metadata_response.text

        non_http_response = client.post(
            "/api/providers/configure",
            json={"provider": "openai-compatible", "base_url": "file:///etc/passwd"},
        )
        assert non_http_response.status_code == 422, non_http_response.text

        # Loopback/LAN targets are the intentional local-provider use case and
        # must keep working.
        loopback_response = client.post(
            "/api/providers/configure",
            json={"provider": "openai-compatible", "base_url": "http://127.0.0.1:1234/v1"},
        )
        assert loopback_response.status_code == 200, loopback_response.text


def test_provider_key_persists_in_gitignored_env_across_backend_restart(
    tmp_path: Path,
) -> None:
    credentials_file = tmp_path / ".env"
    credentials_file.write_text(
        "# local credentials\nKOALABATTLE_DEEPSEEK_API_KEY=\nKEEP_ME=unchanged\n",
        encoding="utf-8",
    )
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'persistent-provider.db'}"
    create_test_schema(database_url)
    secret = "sk-deepseek-persistent-secret"

    settings = Settings(
        _env_file=None,
        database_url=database_url,
        provider_credentials_file=credentials_file,
    )
    with TestClient(create_app(settings)) as client:
        configured = client.post(
            "/api/providers/configure",
            json={"provider": "deepseek", "api_key": secret},
        )
        assert configured.status_code == 200, configured.text
        assert configured.json()["source"] == "saved-env"
        assert secret not in configured.text

    persisted = credentials_file.read_text(encoding="utf-8")
    assert f"KOALABATTLE_DEEPSEEK_API_KEY={secret}" in persisted
    assert "KEEP_ME=unchanged" in persisted
    assert S_IMODE(credentials_file.stat().st_mode) == 0o600

    restarted = Settings(
        _env_file=None,
        database_url=database_url,
        provider_credentials_file=credentials_file,
    )
    with TestClient(create_app(restarted)) as client:
        response = client.get("/api/providers")
        assert response.status_code == 200
        assert secret not in response.text
        deepseek = next(
            item for item in response.json()["providers"] if item["id"] == "deepseek"
        )
        assert deepseek["configured"] is True
        assert deepseek["source"] == "saved-env"

        cleared = client.post(
            "/api/providers/configure",
            json={"provider": "deepseek", "clear": True},
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["configured"] is False
        assert secret not in cleared.text

    assert "KOALABATTLE_DEEPSEEK_API_KEY=\n" in credentials_file.read_text(encoding="utf-8")


def test_explicit_provider_clear_overrides_container_environment_key(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'clear-provider.db'}",
        deepseek_api_key="container-environment-secret",
    )
    create_test_schema(settings.database_url)
    with TestClient(create_app(settings)) as client:
        cleared = client.post(
            "/api/providers/configure",
            json={"provider": "deepseek", "clear": True},
        )
        assert cleared.status_code == 200
        assert cleared.json()["configured"] is False


def test_provider_model_discovery_redacts_upstream_credentials(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'provider-models.db'}",
    )
    create_test_schema(settings.database_url)
    secret = "sk-upstream-secret-value"

    with TestClient(create_app(settings)) as client:
        async def fail_model_discovery(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError(f"upstream rejected Bearer {secret}")

        client.app.state.service.list_provider_models = fail_model_discovery
        response = client.post(
            "/api/providers/models",
            json={"provider": "openai-compatible", "base_url": "http://127.0.0.1:1234/v1"},
        )

    assert response.status_code == 502
    assert secret not in response.text
    assert "Bearer [REDACTED]" in response.json()["detail"]


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


def test_historical_match_can_receive_cached_free_production(
    tmp_path: Path, match_config: MatchConfig, agent_request: AgentRequest
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'production-api.db'}"

    async def seed() -> None:
        database = Database(database_url)
        await database.create_schema()
        repository = BattleRepository(database)
        await repository.create_match(
            agent_request.match_id,
            match_config,
            engine="test",
            engine_version="1",
            showdown_version="test",
            poke_env_version="0.15.0",
        )
        await repository.append_event(
            BattleEvent(
                match_id=agent_request.match_id,
                sequence=0,
                turn=1,
                event_type="agent_decision",
                payload={"side": "p1", "commentary": "A public production line."},
            )
        )
        await database.close()

    asyncio.run(seed())
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        asset_root=tmp_path / "assets",
        speech_audio_root=tmp_path / "audio",
        speech_openai_api_key="configured-but-never-called",
    )
    with TestClient(create_app(settings)) as client:
        created = client.post(
            f"/api/matches/{agent_request.match_id}/productions",
            json={
                "profile_id": "live-stream",
                "voice_assignments": {"p1": "fake-test-a", "p2": "fake-test-b"},
            },
        )
        assert created.status_code == 201, created.text
        production_id = created.json()["id"]
        prepared = client.post(
            f"/api/productions/{production_id}/prepare",
            json={"force": False, "allow_paid": False},
        )
        assert prepared.status_code == 200, prepared.text
        assert prepared.json()["status"] == "ready"
        voice = next(cue for cue in prepared.json()["cues"] if cue["track"] == "voice")
        media = client.get(voice["payload"]["media_url"])
        assert media.status_code == 200
        assert media.headers["content-type"].startswith("audio/wav")
        assert b"RIFF" == media.content[:4]
        listed = client.get(f"/api/matches/{agent_request.match_id}/productions")
        assert listed.status_code == 200
        assert listed.json()[0]["id"] == production_id

        paid_preset = {
            "id": "paid-preview",
            "display_name": "Paid preview",
            "provider": "openai",
            "voice": "alloy",
            "model": "gpt-4o-mini-tts",
            "speed": 1,
            "enabled": True,
        }
        assert client.post("/api/production/voices", json=paid_preset).status_code == 200
        refused = client.post(
            "/api/production/voices/preview",
            json={"preset_id": "paid-preview", "text": "Do not bill this test."},
        )
        assert refused.status_code == 409
        assert "allow_paid=true" in refused.json()["detail"]


def test_rematch_creates_new_match_with_same_config(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'rematch.db'}"
    settings = Settings(
        _env_file=None,
        database_url=database_url,
    )
    create_test_schema(settings.database_url)
    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/matches",
            json={
                "player1": {"display_name": "P1", "agent_type": "random"},
                "player2": {"display_name": "P2", "agent_type": "random"},
            },
        )
        assert created.status_code == 202
        match_id = created.json()["id"]

        rematched = client.post(f"/api/matches/{match_id}/rematch")
        assert rematched.status_code == 202
        rematch_data = rematched.json()
        assert rematch_data["id"] != match_id
        assert rematch_data["config"]["players"][0]["display_name"] == "P1"
        assert rematch_data["config"]["players"][1]["display_name"] == "P2"

        not_found = client.post("/api/matches/00000000-0000-0000-0000-000000000000/rematch")
        assert not_found.status_code == 404


def test_resume_re_enqueues_interrupted_match(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'resume.db'}"
    settings = Settings(
        _env_file=None,
        database_url=database_url,
    )
    create_test_schema(settings.database_url)
    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/matches",
            json={
                "player1": {"display_name": "P1", "agent_type": "random"},
                "player2": {"display_name": "P2", "agent_type": "random"},
            },
        )
        assert created.status_code == 202
        match_id = created.json()["id"]

        cancel = client.post(f"/api/matches/{match_id}/cancel")
        assert cancel.status_code == 202

        resumed = client.post(f"/api/matches/{match_id}/resume")
        assert resumed.status_code == 202
        resumed_data = resumed.json()
        assert resumed_data["id"] == match_id
        assert resumed_data["status"] in ("queued", "starting", "running")

        not_found = client.post("/api/matches/00000000-0000-0000-0000-000000000000/resume")
        assert not_found.status_code == 404


def test_api_token_gates_mutating_and_sensitive_endpoints(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}"
    create_test_schema(database_url)
    match_payload = {
        "player1": {"display_name": "P1", "agent_type": "random"},
        "player2": {"display_name": "P2", "agent_type": "random"},
    }

    # (a) no KOALABATTLE_API_TOKEN configured: today's local-dev-friendly default is
    # unchanged - unauthenticated requests to mutating and sensitive-read endpoints succeed.
    open_settings = Settings(_env_file=None, database_url=database_url)
    with TestClient(create_app(open_settings)) as client:
        created = client.post("/api/matches", json=match_payload)
        assert created.status_code == 202, created.text
        match_id = created.json()["id"]
        assert client.get(f"/api/matches/{match_id}").status_code == 200

    # (b)/(c) with a token configured, unauthenticated requests are rejected and the
    # correct bearer token succeeds.
    protected_settings = Settings(
        _env_file=None, database_url=database_url, api_token="s3cr3t-token"
    )
    with TestClient(create_app(protected_settings)) as client:
        assert client.get("/healthz").status_code == 200  # public endpoint stays open

        unauth_create = client.post("/api/matches", json=match_payload)
        assert unauth_create.status_code == 401

        wrong_token = client.post(
            "/api/matches", json=match_payload, headers={"Authorization": "Bearer wrong"}
        )
        assert wrong_token.status_code == 401

        authed_create = client.post(
            "/api/matches",
            json=match_payload,
            headers={"Authorization": "Bearer s3cr3t-token"},
        )
        assert authed_create.status_code == 202, authed_create.text
        match_id = authed_create.json()["id"]

        unauth_read = client.get(f"/api/matches/{match_id}")
        assert unauth_read.status_code == 401

        authed_read = client.get(
            f"/api/matches/{match_id}", headers={"Authorization": "Bearer s3cr3t-token"}
        )
        assert authed_read.status_code == 200

        unauth_ws_close_code = None
        try:
            with client.websocket_connect(f"/api/matches/{match_id}/stream"):
                pass
        except WebSocketDisconnect as disconnect:
            unauth_ws_close_code = disconnect.code
        assert unauth_ws_close_code == 4401

        with client.websocket_connect(
            f"/api/matches/{match_id}/stream?token=s3cr3t-token"
        ) as websocket:
            snapshot = websocket.receive_json()
            assert snapshot["kind"] == "snapshot"
