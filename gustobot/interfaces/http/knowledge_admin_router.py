"""Configured-domain source administration without internal provider details."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.exc import SQLAlchemyError

from gustobot.application.services.knowledge_admin import (
    MAX_DOCUMENT_EDIT_CHARS,
    ChunkUnavailable,
    DocumentContent,
    DocumentTooLarge,
    KnowledgeAdminService,
    SourceCatalog,
    SourceChunk,
    SourceConflict,
    SourceDeletion,
    SourceDeletionUnavailable,
    SourceDetail,
    SourceListQuery,
    SourceListState,
    public_receipt,
)
from gustobot.application.services.knowledge_ingestion import (
    DocumentRevisionConflict,
    IngestionFailed,
    IngestionReceipt,
)
from gustobot.application.services.knowledge_runtime import get_document_service
from gustobot.config.domain import get_domain_definition
from gustobot.interfaces.http.knowledge_router import get_ingestion_service

router = APIRouter(prefix="/knowledge/admin", tags=["Knowledge administration"])


class SourceQuery(BaseModel):
    """Select a knowledge source and optionally one of its versions."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=255)
    version: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("source_id", "version")
    @classmethod
    def _nonblank_identity(cls, value: str | None) -> str | None:
        """Reject whitespace-only source identifiers and version labels."""
        if value is not None and not value.strip():
            raise ValueError("Source identities must not be blank")
        return value


class SourceVersionRequest(SourceQuery):
    """Identify the exact source version confirmed for an administrative operation."""

    version: str = Field(min_length=1, max_length=64)


class ChunkQuery(SourceQuery):
    """Identify one stored chunk within a source version."""

    version: str = Field(min_length=1, max_length=64)
    number: int = Field(default=1, ge=1)


class DocumentUpdateRequest(SourceVersionRequest):
    """An exact editor reference and the complete replacement title and body."""

    revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    title: str = Field(min_length=1, max_length=512)
    text: str = Field(min_length=1, max_length=MAX_DOCUMENT_EDIT_CHARS)

    @field_validator("title", "text")
    @classmethod
    def _nonblank_content(cls, value: str) -> str:
        """Reject empty content without trimming or changing the source version hash."""
        if not value.strip():
            raise ValueError("Document title and text must not be blank")
        return value


def get_admin_service() -> KnowledgeAdminService:
    """Create the source administration service for the configured domain."""
    return KnowledgeAdminService(
        get_domain_definition(), ingestion=get_ingestion_service(), documents=get_document_service
    )


def source_list_query(
    request: Request,
    q: Annotated[str, Query(max_length=200)] = "",
    state: Annotated[SourceListState, Query()] = "all",
    kind: Annotated[Literal["all", "document", "recipe"], Query()] = "all",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SourceListQuery:
    """Validate all source-list query fields and reject unknown parameters."""
    # FastAPI 0.109 cannot bind query models; validate the full map to reject extras.
    try:
        return SourceListQuery.model_validate(dict(request.query_params))
    except ValidationError as error:
        raise RequestValidationError(
            [{**item, "loc": ("query", *item["loc"])} for item in error.errors()]
        ) from error


def source_query(
    request: Request,
    source_id: Annotated[str, Query(min_length=1, max_length=255)],
    version: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
) -> SourceQuery:
    """Validate the source selector from the complete query parameter map."""
    try:
        return SourceQuery.model_validate(dict(request.query_params))
    except ValidationError as error:
        raise RequestValidationError(
            [{**item, "loc": ("query", *item["loc"])} for item in error.errors()]
        ) from error


def chunk_query(
    request: Request,
    source_id: Annotated[str, Query(min_length=1, max_length=255)],
    version: Annotated[str, Query(min_length=1, max_length=64)],
    number: Annotated[int, Query(ge=1)] = 1,
) -> ChunkQuery:
    """Validate a chunk selector from the complete query parameter map."""
    try:
        return ChunkQuery.model_validate(dict(request.query_params))
    except ValidationError as error:
        raise RequestValidationError(
            [{**item, "loc": ("query", *item["loc"])} for item in error.errors()]
        ) from error


def source_version_query(
    request: Request,
    source_id: Annotated[str, Query(min_length=1, max_length=255)],
    version: Annotated[str, Query(min_length=1, max_length=64)],
) -> SourceVersionRequest:
    """Require the confirmed version and reject additional source selectors."""
    try:
        return SourceVersionRequest.model_validate(dict(request.query_params))
    except ValidationError as error:
        raise RequestValidationError(
            [{**item, "loc": ("query", *item["loc"])} for item in error.errors()]
        ) from error


@router.get("/sources", response_model=SourceCatalog)
def list_sources(
    query: Annotated[SourceListQuery, Depends(source_list_query)],
    service: Annotated[KnowledgeAdminService, Depends(get_admin_service)],
):
    """List source records using the requested domain, kind, and state filters."""
    try:
        return service.list_sources(query)
    except SQLAlchemyError as error:
        logger.exception("Could not read the configured knowledge source catalog")
        raise HTTPException(
            status_code=503, detail="Knowledge source storage is unavailable"
        ) from error


@router.get("/source", response_model=SourceDetail)
def read_source(
    query: Annotated[SourceQuery, Depends(source_query)],
    service: Annotated[KnowledgeAdminService, Depends(get_admin_service)],
):
    """Return source metadata and processing status for the selected version."""
    try:
        return service.read_source(query.source_id, query.version)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except SQLAlchemyError as error:
        logger.exception("Could not read the configured knowledge source version")
        raise HTTPException(
            status_code=503, detail="Knowledge source storage is unavailable"
        ) from error


@router.get("/chunk", response_model=SourceChunk)
def read_chunk(
    query: Annotated[ChunkQuery, Depends(chunk_query)],
    service: Annotated[KnowledgeAdminService, Depends(get_admin_service)],
) -> SourceChunk:
    """Return one stored source chunk when it is available for inspection."""
    try:
        return service.read_chunk(query.source_id, query.version, query.number)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except SourceConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (ChunkUnavailable, SQLAlchemyError) as error:
        logger.warning("Could not read a stored knowledge chunk ({})", type(error).__name__)
        raise HTTPException(status_code=503, detail="切片暂时无法读取，请稍后重试。") from error


@router.post("/retry", response_model=IngestionReceipt, status_code=201)
async def retry_source(
    request: SourceVersionRequest,
    service: Annotated[KnowledgeAdminService, Depends(get_admin_service)],
):
    """Retry ingestion for one source version and return its public receipt."""
    try:
        return public_receipt(await service.retry(request.source_id, request.version))
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except SourceConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail="Stored document cannot be ingested") from error
    except IngestionFailed as error:
        raise HTTPException(
            status_code=503,
            detail={
                "message": str(error),
                "receipt": public_receipt(error.receipt).model_dump(mode="json"),
            },
        ) from error
    except SQLAlchemyError as error:
        logger.exception("Could not retry the configured knowledge source version")
        raise HTTPException(
            status_code=503, detail="Knowledge source storage is unavailable"
        ) from error


@router.get("/document", response_model=DocumentContent)
def read_document(
    query: Annotated[SourceVersionRequest, Depends(source_version_query)],
    service: Annotated[KnowledgeAdminService, Depends(get_admin_service)],
) -> DocumentContent:
    """Return an entire selected document for editing, with an explicit size limit."""
    try:
        return service.read_document(query.source_id, query.version)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except SourceConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except DocumentTooLarge as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except SQLAlchemyError as error:
        logger.exception("Could not read an editable document")
        raise HTTPException(status_code=503, detail="文档原文暂时无法读取，请稍后重试。") from error


@router.put("/document", response_model=IngestionReceipt)
async def update_document(
    request: DocumentUpdateRequest,
    service: Annotated[KnowledgeAdminService, Depends(get_admin_service)],
) -> IngestionReceipt:
    """Publish a guarded text revision while retaining prior text and graph evidence."""
    try:
        return public_receipt(
            await service.update_document(
                request.source_id,
                request.version,
                revision=request.revision,
                title=request.title,
                text=request.text,
            )
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except DocumentRevisionConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail="Stored document cannot be revised") from error
    except IngestionFailed as error:
        raise HTTPException(
            status_code=503,
            detail={
                "message": str(error),
                "receipt": public_receipt(error.receipt).model_dump(mode="json"),
            },
        ) from error
    except SQLAlchemyError as error:
        logger.exception("Could not revise a document source")
        raise HTTPException(status_code=503, detail="文档保存未完成，请刷新核对后重试。") from error


@router.delete("/source", response_model=SourceDeletion)
def delete_source(
    query: Annotated[SourceVersionRequest, Depends(source_version_query)],
    service: Annotated[KnowledgeAdminService, Depends(get_admin_service)],
) -> SourceDeletion:
    """Permanently remove confirmed document versions, jobs, and vector chunks."""
    try:
        return service.delete_source(query.source_id, query.version)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except SourceConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (SourceDeletionUnavailable, SQLAlchemyError) as error:
        logger.warning("Could not delete document source records ({})", type(error).__name__)
        raise HTTPException(
            status_code=503,
            detail="未能确认删除结果，可能已停用检索，请刷新核对后重试。",
        ) from error
