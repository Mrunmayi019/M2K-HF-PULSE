"""Phase 6: FastAPI app entrypoint.

Run with: uvicorn src.api.main:app --reload
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
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
app.include_router(router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Defensive catch-all -- Pulse failures inside the background pipeline are handled
    explicitly in services.py (recorded on simulation_runs, never raised here); this only
    catches genuinely unexpected errors (DB issues etc.) in the synchronous request path."""
    logger.exception("unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})
