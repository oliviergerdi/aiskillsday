"""One FastAPI app: toy services at /v1 and /v2, nParity web UI at / (Task 10)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.toys import v1, v2
from app.web.routes import router

class NoCacheStatic(StaticFiles):
    """Browsers heuristically cache files that have no Cache-Control, so a CSS change looked stale after a deploy."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"   # revalidate every time; ETag keeps it a cheap 304
        return response


app = FastAPI(title="nParity")
app.state.runs_dir = Path("runs")          # tests point this at a tmp dir
app.mount("/v1", v1.app)
app.mount("/v2", v2.app)
app.mount("/static", NoCacheStatic(directory=Path(__file__).parent / "web" / "static"), name="static")
app.include_router(router)
