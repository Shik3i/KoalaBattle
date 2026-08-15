from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from koalabattle.config import Settings, get_settings
from koalabattle.core.assets import (
    AssetResolution,
    AssetScanReport,
    LocalAssetProvider,
    PokemonAssetKind,
    PokemonPerspective,
)
from koalabattle.core.models import MatchArchive, MatchStatus, MatchSummary
from koalabattle.core.public import presentation_archive
from koalabattle.service import BattleService
from koalabattle.storage import BattleRepository, Database
from koalabattle.tournaments.models import (
    CreateTournament,
    MatchTemplateSnapshot,
    StoredTemplate,
    StoredTournamentPreset,
    TournamentArchive,
    TournamentSummary,
)
from koalabattle.tournaments.public import presentation_tournament
from koalabattle.tournaments.repository import TournamentRepository

from .schemas import (
    CreateMatchRequest,
    ManualDecisionInput,
    ProviderModelsInput,
    StoredPresetInput,
    StoredTemplateInput,
)

LOGGER = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database(resolved.database_url)
        repository = BattleRepository(database)
        tournaments = TournamentRepository(database)
        service = BattleService(repository, resolved, tournaments)
        app.state.database = database
        app.state.repository = repository
        app.state.service = service
        app.state.tournaments = tournaments
        app.state.assets = LocalAssetProvider(resolved.asset_root)
        try:
            await service.start()
            yield
        finally:
            await service.close()
            await database.close()

    app = FastAPI(
        title="KoalaBattle API",
        version="0.4.0",
        description="Concurrent battle orchestration, tournaments, and immutable replay API",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": "0.4.0"}

    @app.post("/api/matches", response_model=MatchArchive, status_code=status.HTTP_202_ACCEPTED)
    async def create_match(payload: CreateMatchRequest, request: Request) -> MatchArchive:
        try:
            return await _service(request).create_match(payload.to_config())
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/matches", response_model=tuple[MatchSummary, ...])
    async def list_matches(
        request: Request,
        limit: int = 100,
        offset: int = 0,
        status: MatchStatus | None = None,
        tournament_id: UUID | None = None,
        standalone: bool | None = None,
        search: str | None = None,
    ) -> tuple[MatchSummary, ...]:
        return await _repository(request).list_matches(
            min(max(limit, 1), 250),
            offset=max(offset, 0),
            status=status,
            tournament_id=tournament_id,
            standalone=standalone,
            search=search,
        )

    @app.get("/api/matches/{match_id}", response_model=MatchArchive)
    async def get_match(match_id: UUID, request: Request) -> MatchArchive:
        archive = await _repository(request).get_match(match_id)
        if archive is None:
            raise HTTPException(status_code=404, detail="match not found")
        return archive

    @app.get("/api/matches/{match_id}/presentation")
    async def get_presentation_match(match_id: UUID, request: Request) -> dict[str, object]:
        archive = await _repository(request).get_match(match_id)
        if archive is None:
            raise HTTPException(status_code=404, detail="match not found")
        return presentation_archive(archive)

    @app.get("/api/watch/{match_id}")
    async def get_spectator_match(match_id: UUID, request: Request) -> dict[str, object]:
        archive = await _repository(request).get_match(match_id)
        if archive is None:
            raise HTTPException(status_code=404, detail="match not found")
        return presentation_archive(archive)

    @app.post("/api/matches/{match_id}/pause", status_code=status.HTTP_202_ACCEPTED)
    async def pause_match(match_id: UUID, request: Request) -> dict[str, str]:
        try:
            await _service(request).pause_match(match_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="match not found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"status": "paused"}

    @app.post("/api/matches/{match_id}/resume", status_code=status.HTTP_202_ACCEPTED)
    async def resume_match(match_id: UUID, request: Request) -> dict[str, str]:
        try:
            await _service(request).resume_match(match_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="match not found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"status": "running"}

    @app.post("/api/matches/{match_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
    async def cancel_match(match_id: UUID, request: Request) -> dict[str, str]:
        try:
            await _service(request).cancel_match(match_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="match not found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"status": "cancelled"}

    @app.get("/api/matches/{match_id}/pending")
    async def get_pending(match_id: UUID, request: Request) -> dict[str, object]:
        pending = await _service(request).pending_for_match(match_id)
        return {"requests": [item.model_dump(mode="json") for item in pending]}

    @app.post("/api/decisions/{request_id}", status_code=status.HTTP_202_ACCEPTED)
    async def submit_decision(
        request_id: UUID, payload: ManualDecisionInput, request: Request
    ) -> dict[str, str]:
        try:
            await _service(request).submit_manual_decision(request_id, payload.raw_response)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="decision request not pending") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"status": "accepted"}

    @app.post("/api/decisions/{request_id}/validate")
    async def validate_decision(
        request_id: UUID, payload: ManualDecisionInput, request: Request
    ) -> dict[str, object]:
        try:
            decision = await _service(request).validate_manual_decision(
                request_id, payload.raw_response
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="decision request not pending") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"status": "valid", "decision": decision.model_dump(mode="json")}

    @app.get("/api/providers")
    async def providers(request: Request) -> dict[str, object]:
        return {"providers": _service(request).provider_status()}

    @app.post("/api/providers/models")
    async def provider_models(
        payload: ProviderModelsInput, request: Request
    ) -> dict[str, object]:
        try:
            models = await _service(request).list_provider_models(
                payload.provider, payload.base_url
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception as error:
            LOGGER.warning("Model discovery failed: %s", error)
            raise HTTPException(status_code=502, detail=str(error)) from error
        return {"models": [model.model_dump(mode="json") for model in models]}

    @app.get("/api/admin/overview")
    async def admin_overview(request: Request) -> dict[str, object]:
        return await _service(request).admin_overview()

    @app.get("/api/tournaments", response_model=tuple[TournamentSummary, ...])
    async def list_tournaments(
        request: Request,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[TournamentSummary, ...]:
        return await _tournaments(request).list(
            limit=min(max(limit, 1), 250), offset=max(offset, 0)
        )

    @app.post(
        "/api/tournaments",
        response_model=TournamentArchive,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_tournament(
        payload: CreateTournament, request: Request
    ) -> TournamentArchive:
        try:
            return await _service(request).create_tournament(payload)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/tournaments/{tournament_id}", response_model=TournamentArchive)
    async def get_tournament(tournament_id: UUID, request: Request) -> TournamentArchive:
        archive = await _tournaments(request).get(tournament_id)
        if archive is None:
            raise HTTPException(status_code=404, detail="tournament not found")
        return archive

    @app.get("/api/tournaments/{tournament_id}/presentation")
    async def get_tournament_presentation(
        tournament_id: UUID, request: Request
    ) -> dict[str, object]:
        archive = await _tournaments(request).get(tournament_id)
        if archive is None:
            raise HTTPException(status_code=404, detail="tournament not found")
        return presentation_tournament(archive)

    @app.post("/api/tournaments/{tournament_id}/start", status_code=status.HTTP_202_ACCEPTED)
    async def start_tournament(tournament_id: UUID, request: Request) -> TournamentArchive:
        try:
            return await _service(request).start_tournament(tournament_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="tournament not found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/tournaments/{tournament_id}/pause", status_code=status.HTTP_202_ACCEPTED)
    async def pause_tournament(tournament_id: UUID, request: Request) -> dict[str, str]:
        try:
            await _service(request).pause_tournament(tournament_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="tournament not found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"status": "paused"}

    @app.post("/api/tournaments/{tournament_id}/resume", status_code=status.HTTP_202_ACCEPTED)
    async def resume_tournament(tournament_id: UUID, request: Request) -> dict[str, str]:
        try:
            await _service(request).resume_tournament(tournament_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="tournament not found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"status": "running"}

    @app.post("/api/tournaments/{tournament_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
    async def cancel_tournament(tournament_id: UUID, request: Request) -> dict[str, str]:
        try:
            await _service(request).cancel_tournament(tournament_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="tournament not found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"status": "cancelled"}

    @app.post("/api/tournament-series/{series_id}/start", status_code=status.HTTP_202_ACCEPTED)
    async def start_series(series_id: UUID, request: Request) -> MatchArchive:
        try:
            return await _service(request).schedule_series(series_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="series not found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/api/match-templates", response_model=tuple[StoredTemplate, ...])
    async def list_match_templates(request: Request) -> tuple[StoredTemplate, ...]:
        return await _tournaments(request).list_templates()

    @app.post(
        "/api/match-templates", response_model=StoredTemplate, status_code=status.HTTP_201_CREATED
    )
    async def create_match_template(
        payload: StoredTemplateInput, request: Request
    ) -> StoredTemplate:
        try:
            snapshot = MatchTemplateSnapshot.model_validate(payload.snapshot)
            return await _tournaments(request).create_template(payload.name, snapshot)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/tournament-presets", response_model=tuple[StoredTournamentPreset, ...])
    async def list_tournament_presets(
        request: Request,
    ) -> tuple[StoredTournamentPreset, ...]:
        return await _tournaments(request).list_presets()

    @app.post(
        "/api/tournament-presets",
        response_model=StoredTournamentPreset,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_tournament_preset(
        payload: StoredPresetInput, request: Request
    ) -> StoredTournamentPreset:
        return await _tournaments(request).create_preset(payload.name, payload.config)

    @app.get("/api/assets/status", response_model=AssetScanReport)
    async def asset_status(request: Request) -> AssetScanReport:
        return _assets(request).scan()

    @app.post("/api/assets/rescan", response_model=AssetScanReport)
    async def rescan_assets(request: Request) -> AssetScanReport:
        return _assets(request).scan()

    @app.get("/api/assets/resolve/pokemon/{species}", response_model=AssetResolution)
    async def resolve_pokemon_asset(
        species: str,
        request: Request,
        perspective: PokemonPerspective = "front",
        animated: bool = False,
        kind: PokemonAssetKind = "sprite",
    ) -> AssetResolution:
        return _assets(request).resolve_pokemon(
            species,
            perspective=perspective,
            animated=animated,
            kind=kind,
        )

    @app.get("/api/assets/pokemon/{species}")
    async def pokemon_asset(
        species: str,
        request: Request,
        perspective: PokemonPerspective = "front",
        animated: bool = False,
        kind: PokemonAssetKind = "sprite",
    ) -> FileResponse:
        path = _assets(request).pokemon(
            species,
            perspective=perspective,
            animated=animated,
            kind=kind,
        )
        if path is None:
            raise HTTPException(status_code=404, detail="local asset not installed")
        return FileResponse(path)

    @app.websocket("/api/matches/{match_id}/stream")
    async def stream_match(websocket: WebSocket, match_id: UUID) -> None:
        service: BattleService = websocket.app.state.service
        repository: BattleRepository = websocket.app.state.repository
        archive = await repository.get_match(match_id)
        if archive is None:
            await websocket.close(code=4404, reason="match not found")
            return
        await websocket.accept()
        await websocket.send_json({"kind": "snapshot", "match": presentation_archive(archive)})
        for pending in await service.pending_for_match(match_id):
            await websocket.send_json(
                {"kind": "agent_waiting", "request": pending.model_dump(mode="json")}
            )
        queue = service.hub.subscribe(match_id)
        try:
            while True:
                await websocket.send_json(await queue.get())
        except WebSocketDisconnect:
            pass
        finally:
            service.hub.unsubscribe(match_id, queue)

    @app.websocket("/api/admin/stream")
    async def stream_admin(websocket: WebSocket) -> None:
        service: BattleService = websocket.app.state.service
        await websocket.accept()
        await websocket.send_json(
            {"kind": "overview_snapshot", "overview": await service.admin_overview()}
        )
        queue = service.hub.subscribe_overview()
        try:
            while True:
                await websocket.send_json(await queue.get())
        except WebSocketDisconnect:
            pass
        finally:
            service.hub.unsubscribe_overview(queue)

    @app.websocket("/api/tournaments/{tournament_id}/stream")
    async def stream_tournament(websocket: WebSocket, tournament_id: UUID) -> None:
        service: BattleService = websocket.app.state.service
        tournaments: TournamentRepository = websocket.app.state.tournaments
        archive = await tournaments.get(tournament_id)
        if archive is None:
            await websocket.close(code=4404, reason="tournament not found")
            return
        await websocket.accept()
        await websocket.send_json(
            {"kind": "tournament_snapshot", "tournament": presentation_tournament(archive)}
        )
        queue = service.hub.subscribe_overview()
        try:
            while True:
                message = await queue.get()
                if message.get("tournament_id") == str(tournament_id):
                    current = await tournaments.get(tournament_id)
                    if current is not None:
                        await websocket.send_json(
                            {
                                "kind": "tournament_snapshot",
                                "tournament": presentation_tournament(current),
                            }
                        )
        except WebSocketDisconnect:
            pass
        finally:
            service.hub.unsubscribe_overview(queue)

    return app


def _service(request: Request) -> BattleService:
    return cast(BattleService, request.app.state.service)


def _repository(request: Request) -> BattleRepository:
    return cast(BattleRepository, request.app.state.repository)


def _assets(request: Request) -> LocalAssetProvider:
    return cast(LocalAssetProvider, request.app.state.assets)


def _tournaments(request: Request) -> TournamentRepository:
    return cast(TournamentRepository, request.app.state.tournaments)


app = create_app()
