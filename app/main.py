"""One FastAPI app: toy services at /v1 and /v2, nParity web UI at / (Task 10)."""

from __future__ import annotations

from fastapi import FastAPI

from app.toys import v1, v2

app = FastAPI(title="nParity")
app.mount("/v1", v1.app)
app.mount("/v2", v2.app)
