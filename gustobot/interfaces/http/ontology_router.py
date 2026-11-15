"""Validate domain facts and query the shared LightRAG knowledge index."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from gustobot.application.services.lightrag_service import (
    LightRAGInsertResponse,
    LightRAGQueryResponse,
    SearchMode,
    get_lightrag_service,
)
from gustobot.application.services.ontology_service import OntologyService
from gustobot.config import settings
from gustobot.config.domain import get_domain_definition
from gustobot.domain.knowledge import (
    DomainDefinition,
    KnowledgeGraph,
    SourceDocument,
    validate_graph,
)

router = APIRouter(prefix="/ontology", tags=["Domain knowledge"])


class ExtractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sources: list[SourceDocument] = Field(min_length=1, max_length=100)


class GraphQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1)
    mode: SearchMode = "mix"
    top_k: int | None = Field(default=None, ge=1)


class FactCounts(BaseModel):
    entities: int
    relations: int
    sources: int


def get_fact_model() -> BaseChatModel:
    if not settings.LLM_API_KEY:
        raise HTTPException(status_code=503, detail="事实抽取需要配置 LLM_API_KEY")
    return ChatOpenAI(
        api_key=SecretStr(settings.LLM_API_KEY),
        base_url=settings.LLM_BASE_URL,
        model=settings.LLM_MODEL,
        temperature=0,
    )


async def get_fact_service() -> OntologyService:
    return OntologyService(get_domain_definition(), lightrag=get_lightrag_service())


@router.get("/domain")
def read_domain() -> DomainDefinition:
    return get_domain_definition()


@router.post("/extract")
async def extract_facts(
    request: ExtractionRequest, model: Annotated[BaseChatModel, Depends(get_fact_model)]
) -> KnowledgeGraph:
    service = OntologyService(get_domain_definition(), model=model)
    try:
        return await service.extract(request.sources)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/validate")
def validate_facts(graph: KnowledgeGraph) -> FactCounts:
    try:
        validate_graph(get_domain_definition(), graph)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FactCounts(
        entities=len(graph.entities), relations=len(graph.relations), sources=len(graph.sources)
    )


@router.post("/facts")
async def insert_facts(
    graph: KnowledgeGraph, service: Annotated[OntologyService, Depends(get_fact_service)]
) -> LightRAGInsertResponse:
    try:
        return await service.insert(graph)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/query")
async def query_facts(
    request: GraphQueryRequest,
    service: Annotated[OntologyService, Depends(get_fact_service)],
) -> LightRAGQueryResponse:
    return await service.query(request.question, mode=request.mode, top_k=request.top_k)
