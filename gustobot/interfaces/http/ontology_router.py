"""Extract, validate, write and query evidence-backed ontology facts."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, ConfigDict, Field

from gustobot.application.services.ontology_service import OntologyService
from gustobot.config.domain import get_domain_definition
from gustobot.domain.knowledge import (
    DomainDefinition,
    KnowledgeGraph,
    SourceDocument,
    validate_graph,
)
from gustobot.infrastructure.knowledge.graph_store import (
    FactQuery,
    FactResult,
    GraphWriteResult,
)
from gustobot.infrastructure.knowledge.semantic_runtime import (
    SemanticValidationError,
    get_semantic_runtime,
)
from gustobot.interfaces.http.admin_session import require_admin

router = APIRouter(prefix="/ontology", tags=["Domain knowledge"])


class ExtractionRequest(BaseModel):
    """Source documents supplied to the ontology fact extractor."""

    model_config = ConfigDict(extra="forbid")
    sources: list[SourceDocument] = Field(min_length=1, max_length=100)


class FactCounts(BaseModel):
    """Counts of entities, relations, and sources in a validated graph."""

    entities: int
    relations: int
    sources: int


def get_fact_model() -> BaseChatModel:
    """Return the configured extraction model or report missing configuration."""
    from gustobot.application.services.knowledge_runtime import get_model

    model = get_model()
    if model is None:
        raise HTTPException(status_code=503, detail="事实抽取需要配置 LLM_API_KEY")
    return model


async def get_fact_service() -> OntologyService:
    """Build the ontology service for the active domain and graph store."""
    from gustobot.application.services.knowledge_runtime import get_graph_store

    return OntologyService(get_domain_definition(), graph_store=get_graph_store())


@router.get("/domain")
def read_domain() -> DomainDefinition:
    """Return the active domain definition used to validate ontology facts."""
    return get_domain_definition()


@router.post("/extract", dependencies=[Depends(require_admin)])
async def extract_facts(
    request: ExtractionRequest, model: Annotated[BaseChatModel, Depends(get_fact_model)]
) -> KnowledgeGraph:
    """Extract candidate ontology facts from the submitted source documents."""
    service = OntologyService(get_domain_definition(), model=model)
    try:
        return await service.extract(request.sources)
    except SemanticValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": str(exc), "semantic_report": exc.report.model_dump(mode="json")},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/validate")
def validate_facts(graph: KnowledgeGraph) -> FactCounts:
    """Validate a fact graph against the active domain and report its counts."""
    try:
        domain = get_domain_definition()
        semantic = get_semantic_runtime(domain)
        if semantic is None:
            validate_graph(domain, graph)
        else:
            semantic.validate_input(graph)
    except SemanticValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": str(exc), "semantic_report": exc.report.model_dump(mode="json")},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FactCounts(
        entities=len(graph.entities), relations=len(graph.relations), sources=len(graph.sources)
    )


@router.post("/facts", dependencies=[Depends(require_admin)])
async def insert_facts(
    graph: KnowledgeGraph, service: Annotated[OntologyService, Depends(get_fact_service)]
) -> GraphWriteResult:
    """Validate and write the submitted facts to the graph store."""
    try:
        return await service.insert(graph)
    except SemanticValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": str(exc), "semantic_report": exc.report.model_dump(mode="json")},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/query")
async def query_facts(
    request: FactQuery,
    service: Annotated[OntologyService, Depends(get_fact_service)],
) -> FactResult:
    """Query domain facts using the supplied graph-query constraints."""
    try:
        return await service.query(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
