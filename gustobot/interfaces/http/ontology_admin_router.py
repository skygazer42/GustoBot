"""Local admin endpoints for source-bound graph review and publication."""

from contextlib import contextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from langchain_core.language_models.chat_models import BaseChatModel
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from gustobot.application.services.ontology_admin import (
    GraphDraft,
    InvalidGraph,
    OntologyAdminService,
    SourceConflict,
    SourceNotFound,
)
from gustobot.config.domain import get_domain_definition
from gustobot.domain.knowledge import KnowledgeGraph
from gustobot.infrastructure.knowledge.graph_store import (
    FactResult,
    GraphWriteResult,
    Neo4jGraphStore,
)
from gustobot.infrastructure.knowledge.semantic_runtime import SemanticValidationError

router = APIRouter(prefix="/ontology/admin", tags=["Ontology administration"])


class SourceSelection(BaseModel):
    """Identify the source document version used by an ontology operation."""

    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=1, max_length=255)
    version: str = Field(min_length=1, max_length=64)


class GraphReviewRequest(SourceSelection):
    """Pair source provenance with the graph submitted for review or storage."""

    graph: KnowledgeGraph


class SourceFactsQuery(SourceSelection):
    """Bound the number of source-linked facts returned to the administrator."""

    limit: int = Field(default=50, ge=1, le=100)


@contextmanager
def _admin_errors():
    """Map domain failures to HTTP responses and hide unexpected service details."""
    try:
        yield
    except HTTPException:
        raise
    except SourceNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except SourceConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except SemanticValidationError as error:
        raise HTTPException(
            status_code=422,
            detail={
                "errors": [issue.message for issue in error.report.issues],
                "semantic_report": error.report.model_dump(mode="json"),
            },
        ) from error
    except InvalidGraph as error:
        raise HTTPException(status_code=422, detail={"errors": [str(error)]}) from error
    except Exception as error:
        logger.exception("Ontology admin dependency or operation failed")
        raise HTTPException(
            status_code=503, detail="图谱服务暂时不可用，请检查服务日志后重试"
        ) from error


def get_admin_service() -> OntologyAdminService:
    """Create the review service for the active domain configuration."""
    with _admin_errors():
        return OntologyAdminService(get_domain_definition())


def get_admin_model() -> BaseChatModel:
    """Load the configured extraction model or return a service error."""
    from gustobot.application.services.knowledge_runtime import get_model

    with _admin_errors():
        model = get_model()
        if model is None:
            raise HTTPException(status_code=503, detail="事实抽取需要配置 LLM_API_KEY")
        return model


def get_admin_store() -> Neo4jGraphStore:
    """Resolve the graph store used by ontology administration operations."""
    from gustobot.application.services.knowledge_runtime import get_graph_store

    with _admin_errors():
        store: Neo4jGraphStore = get_graph_store()
        return store


AdminService = Annotated[OntologyAdminService, Depends(get_admin_service)]
AdminModel = Annotated[BaseChatModel, Depends(get_admin_model)]
AdminStore = Annotated[Neo4jGraphStore, Depends(get_admin_store)]


def source_facts_query(
    source_id: Annotated[str, Query(min_length=1, max_length=255)],
    version: Annotated[str, Query(min_length=1, max_length=64)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> SourceFactsQuery:
    """Build a validated, bounded query for facts linked to one source version."""
    return SourceFactsQuery(source_id=source_id, version=version, limit=limit)


@router.get("/source-facts", response_model=FactResult)
async def read_source_facts(
    query: Annotated[SourceFactsQuery, Depends(source_facts_query)],
    service: AdminService,
    store: AdminStore,
) -> FactResult:
    """Read facts linked to a selected source version."""
    with _admin_errors():
        return await service.source_facts(query.source_id, query.version, store, limit=query.limit)


@router.post("/extract", response_model=GraphDraft)
async def extract_graph(
    request: SourceSelection, service: AdminService, model: AdminModel
) -> GraphDraft:
    """Extract a reviewable graph draft from one stored source version."""
    with _admin_errors():
        return await service.extract(request.source_id, request.version, model)


@router.post("/validate", response_model=GraphDraft)
async def validate_graph(request: GraphReviewRequest, service: AdminService) -> GraphDraft:
    """Validate the submitted graph against its selected source and domain."""
    with _admin_errors():
        return await service.validate(request.source_id, request.version, request.graph)


@router.post("/facts", response_model=GraphWriteResult)
async def insert_graph(
    request: GraphReviewRequest, service: AdminService, store: AdminStore
) -> GraphWriteResult:
    """Insert a validated graph while retaining its source provenance."""
    with _admin_errors():
        return await service.insert(request.source_id, request.version, request.graph, store)
