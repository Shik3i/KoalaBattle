from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from koalabattle import __version__
from koalabattle.agents.context import (
    CONTEXT_PROFILES,
    PROMPT_PROFILES,
    render_prompt_messages,
)
from koalabattle.branding import (
    BrandAsset,
    BrandAssetInUse,
    BrandAssetLibrary,
    BrandingService,
    UnsupportedMedia,
    UploadBrandAsset,
)
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
from koalabattle.formats import FormatCatalog, FormatDescriptor, FormatGroup
from koalabattle.orchestration.models import (
    OrchestratorCapabilities,
    OrchestratorPlan,
    OrchestratorRequest,
    OrchestratorRun,
)
from koalabattle.orchestration.service import OrchestratorService
from koalabattle.production import (
    CreateProduction,
    DirectorCommand,
    DuplicateProduction,
    PrepareSpeechRequest,
    ProductionService,
    ProductionTimeline,
    SaveStylePreset,
    StylePreset,
    UpdateProduction,
    VoicePreset,
)
from koalabattle.production.models import VoicePreviewRequest
from koalabattle.service import BattleService
from koalabattle.storage import BattleRepository, Database
from koalabattle.teams import (
    TEAM_BUILD_PROFILE_VERSION,
    TeamBuildAudit,
    TeamBuildRequest,
    TeamPromptRequest,
    TeamRepository,
    TeamSnapshot,
    render_team_prompt,
)
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
from koalabattle.video import (
    CreateVideoExport,
    ExportBackend,
    ExportPreflight,
    PacingProfile,
    RenderEngine,
    RendererCapabilities,
    VideoExportJob,
    VideoExportPreset,
    VideoExportService,
)

from .schemas import (
    CreateMatchRequest,
    ManualDecisionInput,
    PromptRenderInput,
    ProviderModelsInput,
    StoredPresetInput,
    StoredTemplateInput,
    TeamValidationInput,
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
        app.state.teams = service.teams
        app.state.assets = LocalAssetProvider(resolved.asset_root)
        app.state.branding = BrandingService(database, resolved.branding_root)
        production = ProductionService(database, repository, resolved)
        repository.set_production_hooks(
            event=production.on_event, completion=production.on_match_completed
        )
        app.state.production = production
        video = VideoExportService(database, repository, production, resolved)
        app.state.video = video
        orchestrator = OrchestratorService(service, production, video, resolved)
        app.state.orchestrator = orchestrator
        try:
            await service.start()
            await production.start()
            await video.start()
            yield
        finally:
            await orchestrator.close()
            await video.close()
            await production.close()
            await service.close()
            await database.close()

    app = FastAPI(
        title="KoalaBattle API",
        version=__version__,
        description="Auditable AI battle tournaments, deterministic production and video API",
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
        return {"status": "ok", "version": __version__}

    @app.get("/api/video/presets", response_model=tuple[VideoExportPreset, ...])
    async def video_presets(request: Request) -> tuple[VideoExportPreset, ...]:
        return _video(request).presets()

    @app.get("/api/video/pacing-profiles", response_model=tuple[PacingProfile, ...])
    async def video_pacing_profiles(request: Request) -> tuple[PacingProfile, ...]:
        return _video(request).pacing_profiles()

    @app.get("/api/video/capabilities", response_model=RendererCapabilities)
    async def video_capabilities(request: Request) -> RendererCapabilities:
        return await _video(request).capabilities()

    @app.get("/api/productions/{production_id}/video-preflight", response_model=ExportPreflight)
    async def video_preflight(
        production_id: UUID,
        request: Request,
        backend: ExportBackend = ExportBackend.OFFLINE,
        render_engine: RenderEngine = RenderEngine.NATIVE,
    ) -> ExportPreflight:
        try:
            return await _video(request).preflight(production_id, backend, render_engine)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="production not found") from error

    @app.post("/api/video/jobs", response_model=VideoExportJob, status_code=status.HTTP_201_CREATED)
    async def create_video_job(payload: CreateVideoExport, request: Request) -> VideoExportJob:
        try:
            return await _video(request).create(payload)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="production or match not found") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post(
        "/api/video/jobs/batch",
        response_model=tuple[VideoExportJob, ...],
        status_code=status.HTTP_201_CREATED,
    )
    async def create_video_batch(
        payload: tuple[CreateVideoExport, ...], request: Request
    ) -> tuple[VideoExportJob, ...]:
        if not 1 <= len(payload) <= 100:
            raise HTTPException(status_code=422, detail="batch must contain 1 to 100 jobs")
        try:
            return tuple([await _video(request).create(item) for item in payload])
        except (KeyError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/video/jobs", response_model=tuple[VideoExportJob, ...])
    async def list_video_jobs(
        request: Request, match_id: UUID | None = None
    ) -> tuple[VideoExportJob, ...]:
        return await _video(request).list(match_id)

    @app.get("/api/video/jobs/{job_id}", response_model=VideoExportJob)
    async def get_video_job(job_id: UUID, request: Request) -> VideoExportJob:
        try:
            return await _video(request).require(job_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="video export job not found") from error

    @app.post("/api/video/jobs/{job_id}/cancel", response_model=VideoExportJob)
    async def cancel_video_job(job_id: UUID, request: Request) -> VideoExportJob:
        try:
            return await _video(request).cancel(job_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="video export job not found") from error

    @app.post("/api/video/jobs/{job_id}/retry", response_model=VideoExportJob)
    async def retry_video_job(job_id: UUID, request: Request) -> VideoExportJob:
        try:
            return await _video(request).retry(job_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="video export job not found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/api/video/jobs/{job_id}/download")
    async def download_video_job(job_id: UUID, request: Request) -> FileResponse:
        try:
            path = await _video(request).registered_file(job_id, "video")
        except KeyError as error:
            raise HTTPException(status_code=404, detail="video export job not found") from error
        if path is None:
            raise HTTPException(status_code=404, detail="completed video file not found")
        return FileResponse(path, media_type="video/mp4", filename=path.name)

    @app.get("/api/video/jobs/{job_id}/captions")
    async def download_video_captions(job_id: UUID, request: Request) -> FileResponse:
        try:
            path = await _video(request).registered_file(job_id, "captions")
        except KeyError as error:
            raise HTTPException(status_code=404, detail="video export job not found") from error
        if path is None:
            raise HTTPException(status_code=404, detail="caption sidecar not found")
        return FileResponse(path, media_type="application/x-subrip", filename=path.name)

    @app.get("/api/video/jobs/{job_id}/manifest")
    async def download_video_manifest(job_id: UUID, request: Request) -> FileResponse:
        try:
            path = await _video(request).registered_file(job_id, "manifest")
        except KeyError as error:
            raise HTTPException(status_code=404, detail="video export job not found") from error
        if path is None:
            raise HTTPException(status_code=404, detail="export manifest not found")
        return FileResponse(path, media_type="application/json", filename=path.name)

    @app.get("/api/orchestrator/capabilities", response_model=OrchestratorCapabilities)
    async def orchestrator_capabilities(request: Request) -> OrchestratorCapabilities:
        return _orchestrator(request).capabilities()

    @app.post("/api/orchestrator/plan", response_model=OrchestratorPlan)
    async def orchestrator_plan(payload: OrchestratorRequest, request: Request) -> OrchestratorPlan:
        return _orchestrator(request).plan(payload)

    @app.post(
        "/api/orchestrator/runs",
        response_model=OrchestratorRun,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_orchestrator_run(
        payload: OrchestratorRequest, request: Request
    ) -> OrchestratorRun:
        plan = _orchestrator(request).plan(payload)
        if not plan.ready:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "orchestrator settings require input",
                    "questions": [item.model_dump(mode="json") for item in plan.questions],
                    "plan": plan.model_dump(mode="json"),
                },
            )
        try:
            return await _orchestrator(request).create(payload)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/orchestrator/runs", response_model=tuple[OrchestratorRun, ...])
    async def list_orchestrator_runs(
        request: Request, limit: int = 50
    ) -> tuple[OrchestratorRun, ...]:
        return await _orchestrator(request).list(min(max(limit, 1), 100))

    @app.get("/api/orchestrator/runs/{run_id}", response_model=OrchestratorRun)
    async def get_orchestrator_run(run_id: UUID, request: Request) -> OrchestratorRun:
        try:
            return await _orchestrator(request).get(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="orchestrator run not found") from error

    @app.post("/api/orchestrator/runs/{run_id}/cancel", response_model=OrchestratorRun)
    async def cancel_orchestrator_run(run_id: UUID, request: Request) -> OrchestratorRun:
        try:
            return await _orchestrator(request).cancel(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="orchestrator run not found") from error

    @app.get("/api/production/profiles")
    async def production_profiles(request: Request) -> dict[str, object]:
        return {
            "profiles": [
                profile.model_dump(mode="json") for profile in _production(request).profiles()
            ]
        }

    @app.get("/api/production/providers")
    async def speech_providers(request: Request) -> dict[str, object]:
        return {
            "providers": [
                provider.model_dump(mode="json")
                for provider in _production(request).provider_status()
            ]
        }

    @app.get("/api/production/voices", response_model=tuple[VoicePreset, ...])
    async def production_voices(request: Request) -> tuple[VoicePreset, ...]:
        return await _production(request).repository.list_voices()

    @app.post("/api/production/voices", response_model=VoicePreset)
    async def save_production_voice(payload: VoicePreset, request: Request) -> VoicePreset:
        await _production(request).repository.upsert_voice(payload)
        return payload

    @app.post("/api/production/voices/preview")
    async def preview_production_voice(
        payload: VoicePreviewRequest, request: Request
    ) -> dict[str, object]:
        presets = {
            preset.id: preset for preset in await _production(request).repository.list_voices()
        }
        preset = presets.get(payload.preset_id)
        if preset is None:
            raise HTTPException(status_code=404, detail="VoicePreset not found")
        try:
            artifact = await _production(request).synthesize(
                payload.text, preset, allow_paid=payload.allow_paid
            )
        except PermissionError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except (RuntimeError, ValueError) as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return artifact.model_dump(mode="json")

    @app.get("/api/matches/{match_id}/productions", response_model=tuple[ProductionTimeline, ...])
    async def list_match_productions(
        match_id: UUID, request: Request
    ) -> tuple[ProductionTimeline, ...]:
        return await _production(request).repository.list_for_match(match_id)

    @app.post(
        "/api/matches/{match_id}/productions",
        response_model=ProductionTimeline,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_match_production(
        match_id: UUID, payload: CreateProduction, request: Request
    ) -> ProductionTimeline:
        try:
            return await _production(request).create(match_id, payload)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="match not found") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/productions/{production_id}", response_model=ProductionTimeline)
    async def get_production(production_id: UUID, request: Request) -> ProductionTimeline:
        try:
            return await _production(request).require(production_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="production not found") from error

    @app.post("/api/productions/{production_id}/update", response_model=ProductionTimeline)
    async def update_production(
        production_id: UUID, payload: UpdateProduction, request: Request
    ) -> ProductionTimeline:
        """Save presentation settings. Battle events and results are never modified here."""
        try:
            return await _production(request).update(production_id, payload)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="production not found") from error

    @app.post(
        "/api/productions/{production_id}/duplicate",
        response_model=ProductionTimeline,
        status_code=status.HTTP_201_CREATED,
    )
    async def duplicate_production(
        production_id: UUID, payload: DuplicateProduction, request: Request
    ) -> ProductionTimeline:
        try:
            return await _production(request).duplicate(production_id, payload)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="production not found") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/productions/{production_id}/delete")
    async def delete_production(production_id: UUID, request: Request) -> dict[str, bool]:
        """Delete one production. The match and its history are untouched."""
        return {"deleted": await _production(request).delete(production_id)}

    @app.get("/api/production/styles", response_model=tuple[StylePreset, ...])
    async def production_styles(request: Request) -> tuple[StylePreset, ...]:
        return await _production(request).styles()

    @app.post(
        "/api/production/styles",
        response_model=StylePreset,
        status_code=status.HTTP_201_CREATED,
    )
    async def save_production_style(payload: SaveStylePreset, request: Request) -> StylePreset:
        try:
            return await _production(request).save_style_preset(payload)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/production/styles/{preset_id}/delete")
    async def delete_production_style(preset_id: str, request: Request) -> dict[str, bool]:
        try:
            return {"deleted": await _production(request).delete_style_preset(preset_id)}
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/branding/assets", response_model=BrandAssetLibrary)
    async def branding_library(request: Request) -> BrandAssetLibrary:
        return await _branding(request).library()

    @app.post(
        "/api/branding/assets",
        response_model=BrandAsset,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_branding_asset(payload: UploadBrandAsset, request: Request) -> BrandAsset:
        try:
            return await _branding(request).upload(payload)
        except UnsupportedMedia as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/branding/assets/{asset_id}/media")
    async def branding_media(asset_id: str, request: Request) -> FileResponse:
        service = _branding(request)
        asset = await service.get(asset_id)
        path = await service.media_path(asset_id)
        if asset is None or path is None:
            raise HTTPException(status_code=404, detail="brand asset not found")
        return FileResponse(path, media_type=asset.media_type)

    @app.post("/api/branding/assets/{asset_id}/delete")
    async def delete_branding_asset(
        asset_id: str, request: Request, force: bool = False
    ) -> dict[str, bool]:
        try:
            return {"deleted": await _branding(request).delete(asset_id, force=force)}
        except BrandAssetInUse as error:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{error} — delete or re-point those productions first, "
                    "or repeat with force=true"
                ),
            ) from error

    @app.post("/api/productions/{production_id}/rebuild", response_model=ProductionTimeline)
    async def rebuild_production(production_id: UUID, request: Request) -> ProductionTimeline:
        try:
            return await _production(request).rebuild(production_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="production or match not found") from error

    @app.post("/api/productions/{production_id}/prepare", response_model=ProductionTimeline)
    async def prepare_production(
        production_id: UUID, payload: PrepareSpeechRequest, request: Request
    ) -> ProductionTimeline:
        try:
            return await _production(request).prepare(production_id, payload)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="production not found") from error

    @app.post("/api/productions/{production_id}/director", response_model=ProductionTimeline)
    async def direct_production(
        production_id: UUID, payload: DirectorCommand, request: Request
    ) -> ProductionTimeline:
        try:
            return await _production(request).direct(production_id, payload)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="production not found") from error

    @app.get("/api/production/media/{cache_key}")
    async def production_media(cache_key: str, request: Request) -> FileResponse:
        try:
            path = _production(request).media_path(cache_key)
        except ValueError as error:
            raise HTTPException(status_code=404, detail="audio not found") from error
        if path is None:
            raise HTTPException(status_code=404, detail="audio not found or corrupt")
        return FileResponse(path, media_type="audio/wav", filename=f"{cache_key}.wav")

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

    @app.get("/api/formats", response_model=FormatCatalog)
    async def list_formats(request: Request, supported_only: bool = False) -> FormatCatalog:
        catalog = _service(request).formats.catalog
        if not supported_only:
            return catalog
        supported = tuple(item for item in catalog.formats if item.supported)
        return catalog.model_copy(update={"formats": supported, "format_count": len(supported)})

    @app.get("/api/formats/groups", response_model=tuple[FormatGroup, ...])
    async def grouped_formats(
        request: Request, supported_only: bool = False
    ) -> tuple[FormatGroup, ...]:
        return _service(request).formats.grouped(supported_only=supported_only)

    @app.get("/api/formats/search", response_model=tuple[FormatDescriptor, ...])
    async def search_format_catalog(
        request: Request, q: str = "", limit: int = 40
    ) -> tuple[FormatDescriptor, ...]:
        return _service(request).formats.search(q, limit=min(max(limit, 1), 200))

    @app.post("/api/formats/refresh", response_model=FormatCatalog)
    async def refresh_formats(request: Request) -> FormatCatalog:
        return await _service(request).formats.refresh()

    @app.get("/api/formats/{format_id}", response_model=FormatDescriptor)
    async def get_format(format_id: str, request: Request) -> FormatDescriptor:
        descriptor = _service(request).formats.get(format_id)
        if descriptor is None:
            raise HTTPException(status_code=404, detail="format not found")
        return descriptor

    @app.get("/api/providers")
    async def providers(request: Request) -> dict[str, object]:
        return {"providers": _service(request).provider_status()}

    @app.post("/api/providers/models")
    async def provider_models(payload: ProviderModelsInput, request: Request) -> dict[str, object]:
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

    @app.post("/api/teams/prompt")
    async def render_team_building_prompt(
        payload: TeamPromptRequest, request: Request
    ) -> dict[str, object]:
        """Render the team-building prompt so it can be pasted into any external chat.

        Format facts come from the pinned Showdown catalog rather than the caller, so a
        copied prompt cannot describe a format the battle will not actually run.
        """
        descriptor = _service(request).formats.get(payload.format)
        if descriptor is None:
            raise HTTPException(status_code=404, detail=f"unknown format {payload.format}")
        context = payload.context.model_copy(
            update={
                # `name` carries the generation ("[Gen 1] OU"); `display_name` is just "OU"
                # and would read identically for every generation.
                "format_name": descriptor.name,
                "generation": descriptor.generation,
                "game_type": descriptor.game_type,
                "mechanics": descriptor.mechanics.actionable(),
                "absent_mechanics": descriptor.mechanics.unavailable(),
                "has_items": descriptor.mechanics.items,
                "has_abilities": descriptor.mechanics.abilities,
                "has_natures": descriptor.mechanics.natures,
            }
        )
        return {
            "format": descriptor.id,
            "profile_version": TEAM_BUILD_PROFILE_VERSION,
            "prompt": render_team_prompt(
                descriptor.id, payload.participant, context, response=payload.response
            ),
        }

    @app.post("/api/teams/validate")
    async def validate_team(payload: TeamValidationInput, request: Request) -> dict[str, object]:
        try:
            validation, snapshot = await _service(request).validate_team(
                name=payload.name,
                team_text=payload.team_text,
                format_id=payload.format,
                source=payload.source,
                save=payload.save,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return {
            "validation": validation.model_dump(mode="json"),
            "snapshot": snapshot.model_dump(mode="json") if snapshot else None,
        }

    @app.get("/api/teams", response_model=tuple[TeamSnapshot, ...])
    async def list_teams(
        request: Request, limit: int = 100, offset: int = 0
    ) -> tuple[TeamSnapshot, ...]:
        return await _teams(request).list(min(max(limit, 1), 250), max(offset, 0))

    @app.get("/api/teams/{team_id}", response_model=TeamSnapshot)
    async def get_team(team_id: UUID, request: Request) -> TeamSnapshot:
        snapshot = await _teams(request).get(team_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="team snapshot not found")
        return snapshot

    @app.post("/api/teams/build")
    async def build_team(payload: TeamBuildRequest, request: Request) -> dict[str, object]:
        try:
            audit, snapshot = await _service(request).build_team(payload)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {
            "audit": audit.model_dump(mode="json"),
            "snapshot": snapshot.model_dump(mode="json") if snapshot else None,
        }

    @app.get("/api/team-build-audits/{audit_id}", response_model=TeamBuildAudit)
    async def get_team_build_audit(audit_id: UUID, request: Request) -> TeamBuildAudit:
        audit = await _teams(request).get_build_audit(audit_id)
        if audit is None:
            raise HTTPException(status_code=404, detail="team build audit not found")
        return audit

    @app.get("/api/admin/overview")
    async def admin_overview(request: Request) -> dict[str, object]:
        return await _service(request).admin_overview()

    @app.post("/api/admin/prompts/render")
    async def render_historical_prompt(
        payload: PromptRenderInput, request: Request
    ) -> dict[str, object]:
        archive = await _repository(request).get_match(payload.match_id)
        if archive is None:
            raise HTTPException(status_code=404, detail="match not found")
        record = next((item for item in archive.decisions if item.id == payload.decision_id), None)
        if record is None:
            raise HTTPException(status_code=404, detail="decision not found")
        if record.request.context is None:
            return {
                "available": False,
                "detail": "Context snapshot unavailable for this historical decision.",
            }
        prompt_profile_id = payload.prompt_profile or record.request.context.prompt_profile_id
        context_profile_id = payload.context_profile or record.request.context.context_profile_id
        snapshot = record.request.context.model_copy(
            update={
                "prompt_profile_id": prompt_profile_id,
                "prompt_profile_version": PROMPT_PROFILES[prompt_profile_id].version,
                "context_profile_id": context_profile_id,
                "context_profile_version": CONTEXT_PROFILES[context_profile_id].version,
            }
        )
        rendered, metrics = render_prompt_messages(snapshot)
        return {
            "available": True,
            "snapshot": snapshot.model_dump(mode="json"),
            "prompt": rendered.combined,
            "system_prompt": rendered.system,
            "user_prompt": rendered.user,
            "knowledge": record.request.knowledge.model_dump(mode="json")
            if record.request.knowledge
            else None,
            "raw_response": record.raw_response,
            "parsed_decision": record.parsed_response,
            "metrics": metrics.model_dump(mode="json"),
        }

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
    async def create_tournament(payload: CreateTournament, request: Request) -> TournamentArchive:
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


def _branding(request: Request) -> BrandingService:
    return cast(BrandingService, request.app.state.branding)


def _tournaments(request: Request) -> TournamentRepository:
    return cast(TournamentRepository, request.app.state.tournaments)


def _teams(request: Request) -> TeamRepository:
    return cast(TeamRepository, request.app.state.teams)


def _production(request: Request) -> ProductionService:
    return cast(ProductionService, request.app.state.production)


def _video(request: Request) -> VideoExportService:
    return cast(VideoExportService, request.app.state.video)


def _orchestrator(request: Request) -> OrchestratorService:
    return cast(OrchestratorService, request.app.state.orchestrator)


app = create_app()
