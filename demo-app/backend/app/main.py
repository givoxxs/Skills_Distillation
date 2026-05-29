"""Skill Distillation Lab — FastAPI backend.

Endpoints split into two groups:

* ``/api/skills/*`` — read-only data loader over
  ``distillation_v2/results/stable/<skill>/``. Returns the real
  ``summary.json`` + ``SKILL_round_*.md`` from disk.
* ``/api/run`` + ``/api/run/{id}/stream`` — SSE replay of real run logs
  for the live demo on the /run page (no LLM calls).

CORS origins come from the ``ALLOWED_ORIGINS`` env var (comma-separated).
Defaults to localhost:3000 for local development.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.models import HealthResponse
from app.routes import compare as compare_route
from app.routes import run as run_route
from app.routes import skills as skills_route


def _allowed_origins() -> list[str]:
    raw = os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    )
    return [o.strip() for o in raw.split(",") if o.strip()]


app = FastAPI(
    title="Skill Distillation Lab — Backend",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(skills_route.router)
app.include_router(run_route.router)
app.include_router(compare_route.router)


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")
