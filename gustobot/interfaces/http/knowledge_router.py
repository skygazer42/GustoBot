"""Explicit document indexing, deterministic recipe imports and knowledge questions."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from gustobot.application.services.knowledge_ingestion import (
    DocumentIngestionRequest,
    IngestionFailed,
    IngestionJobStatus,
    IngestionReceipt,
    KnowledgeIngestionService,
)
from gustobot.application.services.knowledge_query import (
    KnowledgeAnswer,
    KnowledgeQueryService,
)
from gustobot.application.services.knowledge_runtime import (
    get_document_service,
    get_graph_store,
    get_query_service,
)
from gustobot.config.domain import get_domain_definition
from gustobot.infrastructure.knowledge.semantic_runtime import SemanticValidationError
from gustobot.interfaces.http.admin_session import require_admin

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class RecipeIngestionRequest(BaseModel):
    """Recipe identifier and source record accepted for ingestion."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    record: dict[str, Any]


class KnowledgeQueryRequest(BaseModel):
    """Natural-language question submitted to the knowledge service."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=5000)


class SourceWithdrawalResponse(BaseModel):
    """Receipt describing the source versions withdrawn from retrieval."""

    domain_id: str
    source_id: str
    status: str
    versions: int


def get_ingestion_service() -> KnowledgeIngestionService:
    """Build the ingestion service with the active domain and data stores."""
    return KnowledgeIngestionService(
        get_domain_definition(),
        documents=get_document_service,
        graph_store=get_graph_store,
    )


def _failure(error: IngestionFailed, completed=None):
    """Build a service-unavailable response that preserves completed receipts."""
    detail = {
        "message": str(error),
        "receipt": error.receipt.model_dump(mode="json"),
    }
    if completed is not None:
        detail["completed"] = [receipt.model_dump(mode="json") for receipt in completed]
    return HTTPException(status_code=503, detail=detail)


@router.post(
    "/documents",
    response_model=IngestionReceipt,
    status_code=201,
    dependencies=[Depends(require_admin)],
)
async def ingest_document(
    request: DocumentIngestionRequest,
    service: Annotated[KnowledgeIngestionService, Depends(get_ingestion_service)],
):
    """Submit a document source for ingestion and return its receipt."""
    try:
        return await service.ingest_document(request)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except IngestionFailed as error:
        raise _failure(error) from error


@router.post(
    "/recipes",
    response_model=IngestionReceipt,
    status_code=201,
    dependencies=[Depends(require_admin)],
)
async def ingest_recipe(
    request: RecipeIngestionRequest,
    service: Annotated[KnowledgeIngestionService, Depends(get_ingestion_service)],
):
    """Ingest one recipe record and return its receipt."""
    try:
        return await service.ingest_recipe(request.name, request.record)
    except SemanticValidationError as error:
        raise HTTPException(
            status_code=422,
            detail={
                "message": str(error),
                "semantic_report": error.report.model_dump(mode="json"),
            },
        ) from error
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except IngestionFailed as error:
        raise _failure(error) from error


@router.post(
    "/recipes/batch",
    response_model=list[IngestionReceipt],
    status_code=201,
    dependencies=[Depends(require_admin)],
)
async def ingest_recipes_batch(
    requests: list[RecipeIngestionRequest],
    service: Annotated[KnowledgeIngestionService, Depends(get_ingestion_service)],
):
    """Ingest recipes in order and report earlier receipts if one fails."""
    completed = []
    for request in requests:
        try:
            completed.append(await service.ingest_recipe(request.name, request.record))
        except SemanticValidationError as error:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": str(error),
                    "semantic_report": error.report.model_dump(mode="json"),
                    "completed": [receipt.model_dump(mode="json") for receipt in completed],
                },
            ) from error
        except (ValueError, TypeError) as error:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": str(error),
                    "completed": [receipt.model_dump(mode="json") for receipt in completed],
                },
            ) from error
        except IngestionFailed as error:
            raise _failure(error, completed) from error
    return completed


@router.post("/query", response_model=KnowledgeAnswer)
async def query_knowledge(
    request: KnowledgeQueryRequest,
    service: Annotated[KnowledgeQueryService, Depends(get_query_service)],
):
    """Answer a knowledge question using the configured retrieval services."""
    try:
        return await service.answer(request.question)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get(
    "/jobs/{job_id}", response_model=IngestionJobStatus, dependencies=[Depends(require_admin)]
)
async def read_job(
    job_id: str,
    service: Annotated[KnowledgeIngestionService, Depends(get_ingestion_service)],
):
    """Return ingestion progress, or 404 when the job identifier is unknown."""
    job = await service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Ingestion job not found")
    return job


@router.delete(
    "/sources/{source_id:path}",
    response_model=SourceWithdrawalResponse,
    dependencies=[Depends(require_admin)],
)
async def withdraw_source(
    source_id: str,
    service: Annotated[KnowledgeIngestionService, Depends(get_ingestion_service)],
):
    """Withdraw a source from the knowledge index and return its receipt."""
    try:
        return await service.withdraw_source(source_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
