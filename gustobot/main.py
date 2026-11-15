"""
GustoBot FastAPI application entry point.
"""

import asyncio
import os
from importlib import import_module
from typing import Union

import anyio
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from gustobot.application.services.lightrag_service import cleanup_lightrag_service
from gustobot.config import settings
from gustobot.config.domain import get_domain_definition
from gustobot.infrastructure.core import configure_logging
from gustobot.infrastructure.core.database import Base, engine
from gustobot.interfaces.http import lightrag_router, ontology_router
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
for router_module in get_domain_definition().http_router_modules:
    application.include_router(import_module(router_module).router, prefix=settings.API_V1_PREFIX)
application.include_router(lightrag_router.router, prefix=settings.API_V1_PREFIX)
application.include_router(ontology_router.router, prefix=settings.API_V1_PREFIX)
application.include_router(api_v1_router, prefix=settings.API_V1_PREFIX)

# Static files ---------------------------------------------------------------
# 创建上传目录
uploads_dir = os.path.join(os.path.dirname(__file__), "..", "..", "uploads")
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

    # Auto-create database tables on startup
    import_module("gustobot.infrastructure.persistence.db.models")

    logger.info("Creating database tables if not exist...")
    await run_in_threadpool(Base.metadata.create_all, bind=engine)
    logger.info("Database tables ready")


@application.on_event("shutdown")
async def shutdown_event() -> None:
    logger.info("Shutting down {}", settings.APP_NAME)
    failures: list[Union[Exception, asyncio.CancelledError]] = []

    try:
        with anyio.fail_after(RESOURCE_CLEANUP_TIMEOUT, shield=True):
            await cleanup_lightrag_service()
    except (Exception, asyncio.CancelledError) as exc:
        failures.append(exc)
        logger.exception("Failed to clean up LightRAG service")

    try:
        with anyio.fail_after(RESOURCE_CLEANUP_TIMEOUT, shield=True):
            await run_in_threadpool(engine.dispose)
    except (Exception, asyncio.CancelledError) as exc:
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
