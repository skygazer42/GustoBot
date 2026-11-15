import logging

from fastapi import FastAPI
from pydantic import BaseModel

from kb_service.api.routes import router as api_router

logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: str


def create_app() -> FastAPI:
    app = FastAPI(
        title="Knowledge Ingestion Service",
        version="0.1.0",
        description=(
            "Rewrite tabular data with LLMs, embed via pgvector, " "and expose retrieval APIs."
        ),
    )
    # expose both legacy /api and the expected /api/v1/knowledge paths
    app.include_router(api_router, prefix="/api")
    app.include_router(api_router, prefix="/api/v1/knowledge")

    @app.get("/health", tags=["system"], response_model=HealthResponse)
    def health_check():
        return {"status": "ok"}

    logger.info("FastAPI application initialised")
    return app


app = create_app()
