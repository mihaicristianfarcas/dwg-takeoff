"""The web app (FastAPI): upload or pick a drawing, ask for quantities, inspect the evidence on
the plan. The API is under /api (docs/web-api.md); the UI is the static page in `static/`.

    uvicorn dwg_takeoff.web:app      (or: dwg-takeoff serve)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__, config
from ..store import STORE
from .routes import analysis, catalogue, projects, runs, viewer

STATIC = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app):
    STORE.use_processes = not config.in_process()
    projects.load_saved_drawings()
    yield


app = FastAPI(title="DWG Takeoff", version=__version__, lifespan=lifespan)


@app.middleware("http")
async def same_origin_only(request, call_next):
    """The server listens on localhost: refuse state-changing requests sent by other web sites
    open in the same browser (a plain form POST needs no CORS preflight)."""
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Cross-origin request refused"}, status_code=403)
    return await call_next(request)


for module in (projects, viewer, catalogue, analysis, runs):
    app.include_router(module.router)
app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
