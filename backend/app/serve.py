"""Production entrypoint: the API under /api plus the built frontend at /.

Run with: uvicorn app.serve:app  (FRONTEND_DIST points at the Vite build output)
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.main import app as api

FRONTEND_DIST = Path(os.environ.get("FRONTEND_DIST", "/srv/frontend/dist"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Starlette does not run a mounted app's lifespan, so drive the API's (DB pool) here.
    async with api.router.lifespan_context(api):
        yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/api", api)
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="web")
