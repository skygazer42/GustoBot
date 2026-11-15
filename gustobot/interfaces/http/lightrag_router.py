"""
LightRAG 问答检索 API 路由

提供基于 LightRAG 的问答检索服务的 REST API
"""

from typing import AsyncIterator, List, Literal, Union
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from gustobot.application.services.lightrag_service import (
    get_lightrag_service,
    LightRAGQueryRequest,
    LightRAGQueryResponse,
    LightRAGInsertRequest,
    LightRAGInsertResponse,
    SearchMode,
)
from gustobot.infrastructure.core.logger import get_logger
from gustobot.infrastructure.core.resources import close_on_exit

logger = get_logger(service="lightrag-api")

router = APIRouter(prefix="/lightrag", tags=["LightRAG"])


class IndexFileStats(BaseModel):
    exists: bool
    size_bytes: int
    size_mb: float


class IndexStatsResponse(BaseModel):
    working_dir: str
    total_size_mb: float
    files: dict[str, IndexFileStats]
    initialized: bool


class ModeQuerySuccess(BaseModel):
    success: Literal[True]
    response: str
    response_length: int


class ModeQueryFailure(BaseModel):
    success: Literal[False]
    error: str


class ModeComparisonResponse(BaseModel):
    query: str
    results: dict[str, Union[ModeQuerySuccess, ModeQueryFailure]]


@router.post("/query", response_model=LightRAGQueryResponse)
async def query_lightrag(request: LightRAGQueryRequest):
    """
    执行 LightRAG 问答检索（非流式）

    Parameters
    ----------
    request : LightRAGQueryRequest
        查询请求，包含：
        - query: 查询问题
        - mode: 检索模式（naive/local/global/hybrid）
        - top_k: 返回结果数量
        - stream: 必须为 False（流式请求请使用 /query-stream）

    Returns
    -------
    LightRAGQueryResponse
        查询响应，包含答案和元数据

    Examples
    --------
    ```bash
    curl -X POST "http://localhost:8000/api/v1/lightrag/query" \\
      -H "Content-Type: application/json" \\
      -d '{
        "query": "红烧肉怎么做？",
        "mode": "hybrid",
        "top_k": 10,
        "stream": false
      }'
    ```
    """
    try:
        # 确保不是流式请求
        if request.stream:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="此接口不支持流式响应，请使用 /query-stream",
            )

        service = get_lightrag_service()
        response = await service.query_structured(request)

        logger.info(f"查询成功 | 模式: {request.mode} | 响应长度: {len(response.response)}")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"查询失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查询失败: {str(e)}",
        )


@router.post("/query-stream")
async def query_lightrag_stream(request: LightRAGQueryRequest):
    """
    执行 LightRAG 问答检索（流式响应）

    Parameters
    ----------
    request : LightRAGQueryRequest
        查询请求，stream 参数会被强制设为 True

    Returns
    -------
    StreamingResponse
        Server-Sent Events (SSE) 流式响应

    Examples
    --------
    ```bash
    curl -X POST "http://localhost:8000/api/v1/lightrag/query-stream" \\
      -H "Content-Type: application/json" \\
      -d '{
        "query": "红烧肉怎么做？",
        "mode": "hybrid",
        "top_k": 10
      }'
    ```
    """
    try:
        service = get_lightrag_service()

        # 执行流式查询
        response_gen = await service.query(
            query=request.query,
            mode=request.mode,
            top_k=request.top_k,
            stream=True,
        )

        # 将异步生成器包装为 StreamingResponse
        async def event_generator() -> AsyncIterator[str]:
            try:
                async with close_on_exit(response_gen.aclose):
                    async for chunk in response_gen:
                        # SSE 格式: data: <content>\n\n
                        yield f"data: {chunk}\n\n"
            except Exception as e:
                logger.exception(f"流式响应中发生错误: {str(e)}")
                yield f"data: [ERROR] {str(e)}\n\n"
            # Do not yield while handling GeneratorExit or request cancellation.
            yield "data: [DONE]\n\n"

        logger.info(f"开始流式查询 | 模式: {request.mode}")
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
        )

    except Exception as e:
        logger.exception(f"流式查询失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"流式查询失败: {str(e)}",
        )


@router.post("/insert", response_model=LightRAGInsertResponse)
async def insert_documents(request: LightRAGInsertRequest):
    """
    增量插入文档到 LightRAG

    Parameters
    ----------
    request : LightRAGInsertRequest
        插入请求，包含文档列表

    Returns
    -------
    LightRAGInsertResponse
        插入结果统计

    Examples
    --------
    ```bash
    curl -X POST "http://localhost:8000/api/v1/lightrag/insert" \\
      -H "Content-Type: application/json" \\
      -d '{
        "documents": [
          "红烧肉是一道经典的中华料理...",
          "宫保鸡丁起源于四川..."
        ]
      }'
    ```
    """
    try:
        if not request.documents:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="文档列表不能为空",
            )

        service = get_lightrag_service()
        response = await service.insert_documents(request.documents)

        logger.info(
            f"文档插入完成 | 总数: {response.total} | "
            f"成功: {response.success} | 失败: {response.failed}"
        )
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"插入文档失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"插入文档失败: {str(e)}",
        )


@router.get("/stats", response_model=IndexStatsResponse)
async def get_index_stats():
    """
    获取 LightRAG 索引文件统计信息

    Returns
    -------
    dict
        索引统计信息，包括：
        - working_dir: 工作目录路径
        - total_size_mb: 总大小（MB）
        - files: 各文件详细信息
        - initialized: 是否已初始化

    Examples
    --------
    ```bash
    curl "http://localhost:8000/api/v1/lightrag/stats"
    ```

    返回示例：
    ```json
    {
      "working_dir": "/app/data/lightrag",
      "total_size_mb": 48.5,
      "files": {
        "graph_chunk_entity_relation.graphml": {
          "exists": true,
          "size_bytes": 15728640,
          "size_mb": 15.0
        },
        ...
      },
      "initialized": true
    }
    ```
    """
    try:
        service = get_lightrag_service()
        stats = await run_in_threadpool(service.get_index_stats)

        logger.info(f"获取索引统计 | 总大小: {stats['total_size_mb']} MB")
        return stats

    except Exception as e:
        logger.exception(f"获取统计信息失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取统计信息失败: {str(e)}",
        )


@router.post("/test-modes", response_model=ModeComparisonResponse)
async def test_all_modes(query: str = "红烧肉怎么做？"):
    """
    测试所有检索模式并返回对比结果

    Parameters
    ----------
    query : str
        测试查询

    Returns
    -------
    dict
        各模式的响应结果

    Examples
    --------
    ```bash
    curl -X POST "http://localhost:8000/api/v1/lightrag/test-modes?query=红烧肉怎么做？"
    ```
    """
    try:
        service = get_lightrag_service()
        modes: List[SearchMode] = ["naive", "local", "global", "hybrid"]

        results = {}
        for mode in modes:
            try:
                logger.info(f"测试模式: {mode}")
                response = await service.query(
                    query=query,
                    mode=mode,
                    stream=False,
                )
                results[mode] = {
                    "success": True,
                    "response": response,
                    "response_length": len(response),
                }
            except Exception as e:
                logger.exception(f"模式 {mode} 测试失败: {str(e)}")
                results[mode] = {
                    "success": False,
                    "error": str(e),
                }

        return {
            "query": query,
            "results": results,
        }

    except Exception as e:
        logger.exception(f"测试失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"测试失败: {str(e)}",
        )
