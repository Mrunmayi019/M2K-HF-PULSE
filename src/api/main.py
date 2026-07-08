"""Phase 6: FastAPI app entrypoint.

Run with: uvicorn src.api.main:app --reload
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.database import init_db
from src.api.routes import router

logger = logging.getLogger("m2k_hf_pulse.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="M2K HF-PULSE API",
    description="Digital twin backend: patient intake, wearable sync, Pulse-driven risk assessment.",
    lifespan=lifespan,
)

# Phase 7: the frontend dev server runs on its own origin (Vite, e.g. localhost:5173) --
# without this, every browser fetch() from src/api/client.js fails as a CORS error (curl/server-
# to-server calls are unaffected, which is why this wasn't caught until testing in an actual
# browser). Wide open since this is a local decision-support tool, not a public multi-tenant API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Defensive catch-all -- Pulse failures inside the background pipeline are handled
    explicitly in services.py (recorded on simulation_runs, never raised here); this only
    catches genuinely unexpected errors (DB issues etc.) in the synchronous request path."""
    logger.exception("unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})
