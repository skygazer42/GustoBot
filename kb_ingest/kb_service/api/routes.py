import logging
from contextlib import closing
import tempfile
import shutil
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    status,
    UploadFile,
    File,
    Form,
)
from openai import APIConnectionError, AuthenticationError, OpenAIError, RateLimitError

from kb_service.api.deps import get_config
from kb_service.core.config import Config, clone_config
from kb_service.schemas.ingest import ExcelIngestRequest, MySQLIngestRequest
from kb_service.schemas.search import SearchRequest, HybridSearchRequest
from kb_service.services.processor import DataProcessor
from kb_service.services.search import VectorSearcher
from kb_service.services.mysql_ingest import MySQLIngestor

logger = logging.getLogger(__name__)


class ExcelIngestResponse(BaseModel):
    message: str
    path: str
    mode: Literal["incremental", "full"]


class ExcelUploadResponse(BaseModel):
    message: str
    filename: str
    mode: Literal["incremental", "full"]
    size_bytes: int


class MySQLIngestResponse(BaseModel):
    message: str
    table: str


class SearchResponse(BaseModel):
    query: str
    results: List[Dict[str, Any]]
    count: int


router = APIRouter()


@router.post(
    "/ingest/excel",
    response_model=ExcelIngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Process an Excel file and push embeddings into pgvector",
)
def ingest_excel(
    payload: ExcelIngestRequest, background: BackgroundTasks, config: Config = Depends(get_config)
):
    excel_path = Path(payload.excel_path)
    if not excel_path.exists():
        raise HTTPException(status_code=404, detail=f"Excel file not found: {excel_path}")

    def run_ingest() -> None:
        try:
            local_config = clone_config(config)
            local_config.excel_file_path = str(excel_path)
            with closing(DataProcessor(local_config, incremental=payload.incremental)) as processor:
                processor.process_excel()
        except Exception:  # pragma: no cover - background task logging
            logger.exception("Excel ingest failed for %s", excel_path)

    background.add_task(run_ingest)
    mode = "增量" if payload.incremental else "全量"
    logger.info("Excel ingest queued for %s (模式: %s)", excel_path, mode)
    return {
        "message": "ingest started",
        "path": str(excel_path),
        "mode": "incremental" if payload.incremental else "full",
    }


@router.post(
    "/ingest/excel/upload",
    response_model=ExcelUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload an Excel file and push embeddings into pgvector",
)
def upload_and_ingest_excel(
    background: BackgroundTasks,
    file: UploadFile = File(..., description="Excel file to upload"),
    incremental: bool = Form(False, description="Whether to use incremental mode"),
    config: Config = Depends(get_config),
):
    """
    上传 Excel 文件并处理：
    - 支持主机任意路径的文件上传
    - 文件会保存到临时目录
    - 处理完成后自动清理临时文件
    """
    # 验证文件类型
    if not file.filename or Path(file.filename).suffix.lower() not in {".xlsx", ".xls"}:
        raise HTTPException(status_code=400, detail="只支持 Excel 文件 (.xlsx, .xls)")

    # 创建临时文件
    temp_dir = tempfile.mkdtemp()
    temp_file_path = Path(temp_dir) / ("upload" + Path(file.filename).suffix.lower())

    try:
        # 保存上传的文件
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        logger.info("文件已上传到临时目录: %s", temp_file_path)

        # 定义后台任务
        def run_ingest() -> None:
            try:
                local_config = clone_config(config)
                local_config.excel_file_path = str(temp_file_path)
                with closing(DataProcessor(local_config, incremental=incremental)) as processor:
                    processor.process_excel()
                logger.info("Excel 处理完成，文件: %s", temp_file_path)
            except Exception:
                logger.exception("Excel ingest failed for %s", temp_file_path)
            finally:
                # 清理临时文件
                try:
                    shutil.rmtree(temp_dir)
                    logger.info("临时文件已清理: %s", temp_dir)
                except Exception:
                    logger.exception("清理临时文件失败: %s", temp_dir)

        background.add_task(run_ingest)
        mode = "增量" if incremental else "全量"
        logger.info("Excel 上传处理已加入队列: %s (模式: %s)", file.filename, mode)

        return {
            "message": "文件上传成功，处理已开始",
            "filename": file.filename,
            "mode": "incremental" if incremental else "full",
            "size_bytes": temp_file_path.stat().st_size,
        }

    except Exception as e:
        # 如果出错，清理临时文件
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.exception("文件上传失败")
        raise HTTPException(status_code=500, detail=f"文件上传失败: {str(e)}") from e


@router.post(
    "/ingest/mysql",
    response_model=MySQLIngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Fetch rows from MySQL, rewrite/flatten, and store embeddings",
)
def ingest_mysql(
    payload: MySQLIngestRequest,
    background: BackgroundTasks,
    config: Config = Depends(get_config),
):
    payload_data = payload.model_dump()

    def run_ingest() -> None:
        try:
            local_config = clone_config(config)
            with closing(MySQLIngestor(local_config)) as ingestor:
                ingestor.ingest(MySQLIngestRequest(**payload_data))
        except Exception:  # pragma: no cover - background task logging
            logger.exception("MySQL ingest failed for %s", payload_data.get("table"))

    background.add_task(run_ingest)
    logger.info("MySQL ingest queued for %s", payload.table)
    return {"message": "ingest started", "table": payload.table}


@router.post(
    "/search",
    response_model=SearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Query pgvector for similar records",
)
def vector_search(payload: SearchRequest, config: Config = Depends(get_config)):
    searcher = VectorSearcher(config)
    try:
        results = searcher.search_similar(
            query=payload.query,
            top_k=payload.top_k,
            threshold=payload.threshold,
            metric=payload.metric,
            company_filter=payload.company_filter,
            source_tables=payload.source_tables,
        )
        return {"query": payload.query, "results": results, "count": len(results)}
    except AuthenticationError:
        # Treat as service configuration issue (upstream embedding provider auth).
        # Do not leak any credential details into API responses.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Embedding provider authentication failed. "
                "Check KB_EMBEDDING_API_KEY/KB_EMBEDDING_BASE_URL."
            ),
        )
    except (RateLimitError, APIConnectionError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Embedding provider unavailable (rate limited or connection error).",
        )
    except OpenAIError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Embedding provider returned an error.",
        )
    finally:
        searcher.close()


@router.post(
    "/search/hybrid",
    response_model=SearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Hybrid search with vector retrieval + reranking",
)
def hybrid_search(payload: HybridSearchRequest, config: Config = Depends(get_config)):
    searcher = VectorSearcher(config)
    try:
        return searcher.hybrid_search(
            query=payload.query,
            vector_top_k=payload.vector_top_k,
            rerank_top_k=payload.rerank_top_k,
            threshold=payload.threshold,
            metric=payload.metric,
            source_tables=payload.source_tables,
        )
    except AuthenticationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Embedding provider authentication failed. "
                "Check KB_EMBEDDING_API_KEY/KB_EMBEDDING_BASE_URL."
            ),
        )
    except (RateLimitError, APIConnectionError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Embedding provider unavailable (rate limited or connection error).",
        )
    except OpenAIError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Embedding provider returned an error.",
        )
    finally:
        searcher.close()
