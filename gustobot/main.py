"""
GustoBot FastAPI application entry point.
"""

import asyncio
import os
from importlib import import_module
from pathlib import Path

import anyio
import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
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
    admin_session,
    chat_admin_router,
    knowledge_admin_router,
    knowledge_router,
    ontology_admin_router,
    ontology_router,
    recipe_router,
)
from gustobot.interfaces.http.v1 import api_router as api_v1_router

# Configure logging before app creation
configure_logging(debug=settings.DEBUG)

# Per-owner cooperative cleanup budget; blocking third-party code must also
# honor its own I/O timeouts because thread cancellation cannot stop that code.
RESOURCE_CLEANUP_TIMEOUT = 10.0


class APIInfoResponse(BaseModel):
    """Identity and documentation location returned by the API root."""

    name: str
    version: str
    status: str
    docs: str


class HealthResponse(BaseModel):
    """Basic application health state returned by the health endpoint."""

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
application.include_router(recipe_router.router, prefix=settings.API_V1_PREFIX)
# 写入知识和修改本体的接口统一在路由装配处校验管理员身份。
application.include_router(
    knowledge_admin_router.router,
    prefix=settings.API_V1_PREFIX,
    dependencies=[Depends(admin_session.require_admin)],
)
application.include_router(
    ontology_admin_router.router,
    prefix=settings.API_V1_PREFIX,
    dependencies=[Depends(admin_session.require_admin)],
)
application.include_router(admin_session.router, prefix=settings.API_V1_PREFIX)
application.include_router(chat_admin_router.router, prefix=settings.API_V1_PREFIX)
application.include_router(api_v1_router, prefix=settings.API_V1_PREFIX)


@application.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> Response:
    """Avoid echoing invalid login fields while retaining normal API errors."""
    if request.url.path == f"{settings.API_V1_PREFIX}/admin/session":
        return JSONResponse(
            status_code=422,
            content={"detail": "Invalid login request"},
            headers={"Cache-Control": "no-store"},
        )
    return await request_validation_exception_handler(request, exc)


# Static files ---------------------------------------------------------------
# 创建上传目录
project_root = Path(__file__).resolve().parent.parent
uploads_dir = str(project_root / "uploads")
os.makedirs(uploads_dir, exist_ok=True)

# 挂载静态文件
application.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")


async def root_redirect() -> RedirectResponse:
    """Redirect API-only runs to the interactive documentation."""
    return RedirectResponse(url="/docs")


@application.get("/favicon.ico")
async def favicon() -> Response:
    """Return an empty favicon to avoid noisy 404s in dev."""
    return Response(content=b"", media_type="image/x-icon")


@application.get("/api")
async def root() -> APIInfoResponse:
    """Return API identity and the path to its interactive documentation."""
    return APIInfoResponse(
        name=settings.APP_NAME,
        version=settings.APP_VERSION,
        status="running",
        docs="/docs",
    )


@application.get("/health")
async def health_check() -> HealthResponse:
    """Report that the application process is responding."""
    return HealthResponse(status="healthy", version=settings.APP_VERSION)


@application.on_event("startup")
async def startup_event() -> None:
    """Load database models and verify the schema before serving requests."""
    logger.info("Starting {} v{}", settings.APP_NAME, settings.APP_VERSION)
    logger.info("Debug mode: {}", settings.DEBUG)
    logger.info("API docs available at http://{}:{}/docs", settings.HOST, settings.PORT)

    import_module("gustobot.infrastructure.persistence.db.models")
    # 启动只核验迁移版本；结构变更由迁移命令执行，避免多实例启动时同时改表。
    await run_in_threadpool(verify_database_schema)
    logger.info("MySQL schema and domain {} are ready", get_domain_definition().id)


def verify_database_schema() -> None:
    """Check that the configured database has all application migrations."""
    from migrations import check_database_schema

    check_database_schema(engine)


@application.on_event("shutdown")
async def shutdown_event() -> None:
    """Clean up knowledge clients and the database pool before propagating failures."""
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
    """Log unhandled failures and expose details only while debug mode is on."""
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


web_dist = project_root / "web_dist"
if web_dist.is_dir():
    # Mount after the API routes so the bundled frontend shares their origin.
    application.mount("/", StaticFiles(directory=web_dist, html=True), name="web")
else:
    application.add_api_route("/", root_redirect, methods=["GET"])


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
