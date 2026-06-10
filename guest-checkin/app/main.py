"""FastAPI application factory with lifespan, CORS, rate limiting, and error handlers."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings
from app.database import Base, engine
from app.state_machine.exceptions import (
    InvalidTransitionError,
    SessionNotFoundError,
)
from app.agent.exceptions import OllamaUnavailableError

logger = logging.getLogger(__name__)


def _get_rate_limit_key(request: Request) -> str:
    """Rate-limit key: API key header if present, else client IP."""
    api_key = request.headers.get(settings.API_KEY_HEADER, "")
    if api_key:
        return f"apikey:{api_key}"
    return get_remote_address(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    # ── Startup ───────────────────────────────────────────────────
    # Create database tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Initialize MCP tool registry
    from app.mcp_tools.registry import tool_registry
    if not tool_registry.get_tool_names():
        tool_registry.register_all()
        logger.info("MCP tool registry initialized on startup")

    yield
    # ── Shutdown ──────────────────────────────────────────────────
    await engine.dispose()


def create_app() -> FastAPI:
    """Application factory."""
    limiter = Limiter(key_func=_get_rate_limit_key)

    app = FastAPI(
        title="Guest Check-In API",
        version="0.1.0",
        description="Conversation-based guest check-in via channel messaging",
        lifespan=lifespan,
    )

    # ── Rate limiting ─────────────────────────────────────────────
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # ── CORS ──────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Exception handlers ────────────────────────────────────────

    @app.exception_handler(InvalidTransitionError)
    async def invalid_transition_handler(
        request: Request, exc: InvalidTransitionError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": str(exc),
                "error_type": "invalid_transition",
            },
        )

    @app.exception_handler(SessionNotFoundError)
    async def session_not_found_handler(
        request: Request, exc: SessionNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "detail": str(exc),
                "error_type": "session_not_found",
            },
        )

    @app.exception_handler(OllamaUnavailableError)
    async def ollama_unavailable_handler(
        request: Request, exc: OllamaUnavailableError
    ) -> JSONResponse:
        # Return 200 with fallback message — guest can still proceed
        return JSONResponse(
            status_code=200,
            content={
                "detail": (
                    "AI assistant is temporarily unavailable. "
                    "You can still proceed with the check-in process."
                ),
                "error_type": "ollama_unavailable",
                "fallback": True,
            },
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception("Unhandled exception: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "An internal error occurred. Please try again.",
                "error_type": "internal_error",
            },
        )

    # ── Routers ──────────────────────────────────────────────────
    from app.api.router import api_router
    app.include_router(api_router)

    # ── Static files ──────────────────────────────────────────────
    from pathlib import Path
    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # ── Health check ──────────────────────────────────────────────
    @app.get("/health", tags=["health"])
    async def health_check():
        return {"status": "ok"}

    return app


app = create_app()
