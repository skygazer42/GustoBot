"""
GustoBot FastAPI application entry point.
"""

import asyncio
import os
from importlib import import_module
from pathlib import Path

import anyio
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from gustobot.application.services.knowledge_runtime import cleanup_runtime
from gustobot.config import settings
from gustobot.config.domain import get_domain_definition
from gustobot.infrastructure.core import configure_logging
from gustobot.infrastructure.core.database import engine
from gustobot.interfaces.http import (
    knowledge_admin_router,
    knowledge_router,
    ontology_admin_router,
    ontology_router,
)
from gustobot.interfaces.http.v1 import api_router as api_v1_router

# Configure logging before app creation
configure_logging(debug=settings.DEBUG)

# Per-owner cooperative cleanup budget; blocking third-party code must also
# honor its own I/O timeouts because thread cancellation cannot stop that code.
RESOURCE_CLEANUP_TIMEOUT = 10.0


class APIInfoResponse(BaseModel):
    name: str
    version: str
    status: str
    docs: str


class HealthResponse(BaseModel):
    status: str
    version: str


# Application instance --------------------------------------------------------
application = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Domain-configurable knowledge assistant with document and graph retrieval",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Global middleware -----------------------------------------------------------
application.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源，方便开发和测试
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers --------------------------------------------------------------------
application.include_router(knowledge_router.router, prefix=settings.API_V1_PREFIX)
application.include_router(ontology_router.router, prefix=settings.API_V1_PREFIX)
application.include_router(knowledge_admin_router.router, prefix=settings.API_V1_PREFIX)
application.include_router(ontology_admin_router.router, prefix=settings.API_V1_PREFIX)
application.include_router(api_v1_router, prefix=settings.API_V1_PREFIX)

# Static files ---------------------------------------------------------------
# 创建上传目录
uploads_dir = str(Path(__file__).resolve().parent.parent / "uploads")
os.makedirs(uploads_dir, exist_ok=True)

# 挂载静态文件
application.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")


@application.get("/")
async def root_redirect() -> RedirectResponse:
    """Redirect to API docs.

    The web UI is a separate Vite app under `web/` and is typically run via `npm run dev`.
    """
    return RedirectResponse(url="/docs")


@application.get("/favicon.ico")
async def favicon() -> Response:
    """Return an empty favicon to avoid noisy 404s in dev."""
    return Response(content=b"", media_type="image/x-icon")


@application.get("/api")
async def root() -> APIInfoResponse:
    return APIInfoResponse(
        name=settings.APP_NAME,
        version=settings.APP_VERSION,
        status="running",
        docs="/docs",
    )


@application.get("/health")
async def health_check() -> HealthResponse:
    return HealthResponse(status="healthy", version=settings.APP_VERSION)


@application.on_event("startup")
async def startup_event() -> None:
    logger.info("Starting {} v{}", settings.APP_NAME, settings.APP_VERSION)
    logger.info("Debug mode: {}", settings.DEBUG)
    logger.info("API docs available at http://{}:{}/docs", settings.HOST, settings.PORT)

    import_module("gustobot.infrastructure.persistence.db.models")
    await run_in_threadpool(verify_database_schema)
    logger.info("MySQL schema and domain {} are ready", get_domain_definition().id)


def verify_database_schema() -> None:
    from migrations import check_database_schema

    check_database_schema(engine)


@application.on_event("shutdown")
async def shutdown_event() -> None:
    logger.info("Shutting down {}", settings.APP_NAME)
    failures: list[Exception | asyncio.CancelledError] = []

    try:
        with anyio.fail_after(RESOURCE_CLEANUP_TIMEOUT, shield=True):
            await cleanup_runtime()
    # Shutdown attempts every cleanup and then propagates the collected failure.
    except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001
        failures.append(exc)
        logger.exception("Failed to clean up knowledge clients")

    try:
        with anyio.fail_after(RESOURCE_CLEANUP_TIMEOUT, shield=True):
            await run_in_threadpool(engine.dispose)
    # Shutdown attempts every cleanup and then propagates the collected failure.
    except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001
        failures.append(exc)
        logger.exception("Failed to dispose the database pool")

    if failures:
        for failure in failures:
            if isinstance(failure, asyncio.CancelledError):
                raise failure
        raise RuntimeError("Application resource cleanup failed") from failures[0]


@application.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.opt(exception=exc).error(
        "Unhandled exception on {} {}", request.method, request.url.path
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "message": str(exc) if settings.DEBUG else "An unexpected error occurred",
        },
    )


if __name__ == "__main__":
    uvicorn.run(
        "gustobot.main:application",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info",
    )

# Backwards-compatible alias for tooling expecting `app` symbol
app = application
