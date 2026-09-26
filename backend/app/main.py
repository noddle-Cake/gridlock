"""GridMerge FastAPI app factory. Run with: uvicorn app.main:app --reload"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.db import lines as lines_db
from app.db.pool import apply_schema, create_pool
from app.services.briefs import BriefGenerator
from app.services.extraction import ExtractionService
from app.services.geocoding import Geocoder, GeocodingService, default_geocoder
from app.services.llm import LLMClient, default_llm
from app.sources import snapshot as public_sources

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Sample plans served for the local demo so source-page links resolve.
SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_data"


def create_app(
    *,
    pool: asyncpg.Pool | None = None,
    llm: LLMClient | None = None,
    geocoder: Geocoder | None = None,
) -> FastAPI:
    """Build the app. Tests inject a pool, LLM client, and geocoder."""
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        owns_pool = pool is None
        app.state.pool = pool or await create_pool(settings.database_url)
        if owns_pool:
            await apply_schema(app.state.pool)
            if settings.autoload_lines:
                try:
                    await lines_db.load_snapshot_if_empty(app.state.pool)
                except Exception:  # the reference layer is optional; never block startup
                    log.exception("could not load the HIFLD transmission-line snapshot")
            if settings.autoload_public_sources:
                try:
                    await public_sources.load_snapshots_if_missing(app.state.pool)
                except Exception:  # optional data; never block startup
                    log.exception("could not load the EIA-860M / SERTP snapshots")
        try:
            yield
        finally:
            if owns_pool:
                await app.state.pool.close()

    app = FastAPI(title="GridMerge", version="0.1.0", lifespan=lifespan)
    llm_client = llm or default_llm()
    app.state.extraction = ExtractionService(llm_client)
    app.state.brief_generator = BriefGenerator(llm_client)
    app.state.geocoding = GeocodingService(geocoder or default_geocoder())

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [str(e["loc"][-1]) for e in exc.errors() if e.get("loc")]
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "invalid_request", "message": str(exc.errors()),
                               "fields": fields}},
        )

    app.include_router(router)
    if SAMPLE_DIR.is_dir():
        app.mount("/samples", StaticFiles(directory=SAMPLE_DIR), name="samples")
    return app


app = create_app()
