"""One FastAPI app: toy services at /v1 and /v2, nParity web UI at / (Task 10)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.toys import v1, v2
from app.web.routes import router

app = FastAPI(title="nParity")
app.state.runs_dir = Path("runs")          # tests point these at tmp dirs
app.state.comparisons_dir = Path("comparisons")
app.state.ledger_path = Path("accepted.yaml")
app.mount("/v1", v1.app)
app.mount("/v2", v2.app)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "web" / "static"), name="static")
app.include_router(router)
