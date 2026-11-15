"""
LightRAG 问答检索服务

基于 Docker build 时生成的 LightRAG JSON 文件提供问答检索功能
- 使用预生成的索引文件（kv_store_*.json, vdb_*.json, graph_chunk_entity_relation.graphml）
- 支持多种检索模式：naive, local, global, hybrid
- 支持流式响应
- 支持增量文档插入
"""

import json
import os
import inspect
import asyncio
import importlib
import anyio
from collections.abc import AsyncIterator
from typing import (
    TYPE_CHECKING,
    AsyncGenerator,
    Dict,
    Any,
    List,
    Optional,
    Literal,
    Union,
    overload,
)
from pathlib import Path
from types import ModuleType

from pydantic import BaseModel, ConfigDict, Field
import numpy as np

from gustobot.config import settings
from gustobot.infrastructure.core.logger import get_logger
from gustobot.infrastructure.core.resources import close_on_exit

if TYPE_CHECKING:
    from lightrag import LightRAG

logger = get_logger(service="lightrag-service")

# 检索模式类型
SearchMode = Literal["naive", "local", "global", "hybrid", "mix", "bypass"]


class LightRAGUnavailableError(RuntimeError):
    """The optional LightRAG package is not installed."""


def _load_lightrag() -> ModuleType:
    try:
        return importlib.import_module("lightrag")
    except ModuleNotFoundError as exc:
        if exc.name != "lightrag":
            raise
        raise LightRAGUnavailableError(
            "LightRAG is not installed; install lightrag-hku to use graph document queries"
        ) from exc


def _infer_embedding_dim_from_working_dir(working_dir: str) -> Optional[int]:
    """
    Best-effort infer embedding dimension from pre-generated LightRAG VDB files.

    Our build pipeline stores embedding dimension inside `vdb_*.json` (top-level
    `embedding_dim`), which is the most reliable source when the runtime env var
    `EMBEDDING_DIMENSION` is unset/empty.
    """
    for file_name in ("vdb_chunks.json", "vdb_entities.json", "vdb_relationships.json"):
        path = Path(working_dir) / file_name
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            dim = payload.get("embedding_dim") if isinstance(payload, dict) else None
            if isinstance(dim, int) and dim > 0:
                return dim
        except (OSError, ValueError):
            # Never fail init because of inference errors.
            logger.exception("Unable to infer embedding dimension from {}", path)
            continue
    return None


class LightRAGQueryRequest(BaseModel):
    """LightRAG 查询请求"""

    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(..., min_length=1, description="查询问题")
    mode: SearchMode = Field(default="hybrid", description="检索模式")
    top_k: Optional[int] = Field(
        default=None, ge=1, description="返回结果数量，None 则使用默认配置"
    )
    stream: bool = Field(default=False, description="是否使用流式响应")


class LightRAGQueryResponse(BaseModel):
    """LightRAG 查询响应"""

    query: str = Field(..., description="原始查询")
    response: str = Field(..., description="回答内容")
    mode: SearchMode = Field(..., description="使用的检索模式")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="额外元数据")


class LightRAGInsertRequest(BaseModel):
    """LightRAG 文档插入请求"""

    documents: List[str] = Field(..., description="要插入的文档列表")


class LightRAGInsertResponse(BaseModel):
    """LightRAG 文档插入响应"""

    total: int = Field(..., description="总文档数")
    success: int = Field(..., description="成功插入数")
    failed: int = Field(..., description="失败数")
    errors: List[str] = Field(default_factory=list, description="错误信息")


class LightRAGService:
    """
    LightRAG 问答检索服务

    功能：
    - 基于预生成的索引文件进行问答检索
    - 支持多种检索模式（naive, local, global, hybrid）
    - 支持流式和非流式响应
    - 支持增量文档插入
    """

    def __init__(
        self,
        working_dir: Optional[str] = None,
        default_mode: SearchMode = "hybrid",
        default_top_k: int = 10,
    ) -> None:
        """
        初始化 LightRAG 服务

        Parameters
        ----------
        working_dir : str, optional
            LightRAG 工作目录（包含预生成的 JSON 文件）
        default_mode : SearchMode, optional
            默认检索模式
        default_top_k : int, optional
            默认返回结果数量
        """
        if working_dir is None:
            from gustobot.config.domain import get_domain_definition

            domain = get_domain_definition()
            namespace = domain.document_index_namespace
            if namespace is None:
                namespace = domain.id
            working_dir = str(Path(settings.LIGHTRAG_WORKING_DIR) / namespace)
        self.working_dir = working_dir
        self.default_mode = default_mode
        self.default_top_k = default_top_k

        self.rag: Optional["LightRAG"] = None
        self.initialized = False
        self._lifecycle_lock = asyncio.Lock()

        logger.info(f"LightRAG 服务初始化，工作目录: {self.working_dir}")

    async def _llm_model_func(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history_messages: Optional[List] = None,
        **kwargs,
    ) -> str | AsyncIterator[str]:
        """
        LLM 模型函数

        Parameters
        ----------
        prompt : str
            用户提示词
        system_prompt : str, optional
            系统提示词
        history_messages : list, optional
            历史消息
        **kwargs : dict
            其他参数

        Returns
        -------
        str | AsyncIterator[str]
            LLM 生成的文本，或请求流式响应时的文本块迭代器
        """
        from lightrag.llm.openai import openai_complete_if_cache

        response: object = await openai_complete_if_cache(
            model=settings.OPENAI_MODEL,
            prompt=prompt,
            system_prompt=system_prompt,
            history_messages=[] if history_messages is None else history_messages,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_API_BASE,
            **kwargs,
        )
        if isinstance(response, str):
            return response
        if kwargs.get("stream") is True and isinstance(response, AsyncIterator):
            return response
        raise ValueError("LightRAG completion must contain text or a requested text stream")

    async def _embedding_func(self, texts: List[str]) -> np.ndarray:
        """
        Embedding 函数

        Parameters
        ----------
        texts : List[str]
            要嵌入的文本列表

        Returns
        -------
        np.ndarray
            嵌入向量数组
        """
        from lightrag.llm.openai import openai_embed

        api_key = settings.EMBEDDING_API_KEY or settings.OPENAI_API_KEY
        base_url = settings.EMBEDDING_BASE_URL or settings.OPENAI_API_BASE
        # NOTE: In LightRAG v1.4.x, `openai_embed` itself is already wrapped by an
        # EmbeddingFunc (default dim=1536). Calling it directly can cause false
        # "dimension mismatch" errors when using non-1536 embedding models.
        # Use the unwrapped function via `.func` and let *our* EmbeddingFunc
        # (configured with the correct embedding_dim) validate the output.
        embed_func = getattr(openai_embed, "func", openai_embed)
        embeddings: object = await embed_func(
            texts=texts,
            model=settings.EMBEDDING_MODEL,
            api_key=api_key,
            base_url=base_url,
        )
        if not isinstance(embeddings, np.ndarray):
            raise ValueError("LightRAG embeddings must be a NumPy array")
        return embeddings

    async def initialize(self) -> None:
        """Load one runtime, leaving a failed initialization retryable."""
        async with self._lifecycle_lock:
            if self.initialized:
                return
            try:
                _load_lightrag()
                from lightrag import LightRAG
                from lightrag.utils import EmbeddingFunc
                from lightrag.kg.shared_storage import initialize_pipeline_status
                from gustobot.config.domain import get_domain_definition

                os.makedirs(self.working_dir, exist_ok=True)
                stats = self.get_index_stats()
                missing = [name for name, info in stats["files"].items() if not info["exists"]]
                if missing:
                    logger.warning("LightRAG index files are missing: {}", ", ".join(missing))

                embedding_dim: Optional[int] = None
                explicit_dim_env = os.getenv("EMBEDDING_DIMENSION")
                if explicit_dim_env and explicit_dim_env.strip():
                    try:
                        embedding_dim = int(explicit_dim_env)
                    except ValueError:
                        logger.warning("Invalid EMBEDDING_DIMENSION: {!r}", explicit_dim_env)
                if embedding_dim is None:
                    embedding_dim = _infer_embedding_dim_from_working_dir(self.working_dir)
                if embedding_dim is None:
                    embedding_dim = settings.EMBEDDING_DIMENSION

                domain = get_domain_definition()
                self.rag = LightRAG(
                    working_dir=self.working_dir,
                    llm_model_func=self._llm_model_func,
                    embedding_func=EmbeddingFunc(
                        embedding_dim=embedding_dim,
                        max_token_size=settings.LIGHTRAG_MAX_TOKEN_SIZE,
                        func=self._embedding_func,
                    ),
                    addon_params={"entity_types": list(domain.entity_types), "language": "Chinese"},
                )
                await self.rag.initialize_storages()
                await initialize_pipeline_status()
                self.initialized = True
                logger.info("LightRAG initialized for domain {}", domain.id)
            except BaseException:
                logger.exception("LightRAG initialization failed")
                async with close_on_exit(self._cleanup_unlocked):
                    raise

    @overload
    async def query(
        self,
        query: str,
        mode: Optional[SearchMode] = None,
        top_k: Optional[int] = None,
        stream: Literal[False] = False,
    ) -> str: ...

    @overload
    async def query(
        self,
        query: str,
        mode: Optional[SearchMode] = None,
        top_k: Optional[int] = None,
        *,
        stream: Literal[True],
    ) -> AsyncGenerator[str, None]: ...

    @overload
    async def query(
        self,
        query: str,
        mode: Optional[SearchMode] = None,
        top_k: Optional[int] = None,
        *,
        stream: bool,
    ) -> Union[str, AsyncGenerator[str, None]]: ...

    async def query(
        self,
        query: str,
        mode: Optional[SearchMode] = None,
        top_k: Optional[int] = None,
        stream: bool = False,
    ) -> Union[str, AsyncGenerator[str, None]]:
        """
        执行问答检索

        Parameters
        ----------
        query : str
            查询问题
        mode : SearchMode, optional
            检索模式（naive/local/global/hybrid），默认使用配置的模式
        top_k : int, optional
            返回结果数量，默认使用配置的值
        stream : bool, optional
            是否使用流式响应

        Returns
        -------
        str | AsyncGenerator[str, None]
            如果 stream=False，返回完整答案字符串
            如果 stream=True，返回异步生成器
        """
        await self.initialize()
        rag = self.rag
        if rag is None:
            raise RuntimeError("LightRAG initialization did not establish a runtime")

        retrieval_mode = mode or self.default_mode
        k = self.default_top_k if top_k is None else top_k
        if k < 1:
            raise ValueError("top_k must be positive")

        try:
            logger.info(f"执行查询 | 模式: {retrieval_mode} | Top-K: {k}")
            logger.info(f"查询内容: {query}")

            # 创建查询参数
            from lightrag import QueryParam

            param = QueryParam(
                mode=retrieval_mode,
                top_k=k,
                stream=stream,
            )

            # 执行查询
            response: object = await rag.aquery(query, param=param)

            # 如果是流式响应，返回生成器
            if stream and inspect.isasyncgen(response):
                logger.info("返回流式响应")
                return response

            if not isinstance(response, str):
                raise ValueError("LightRAG response must contain text")

            response_text = response
            if stream:
                # Some providers return complete text even when streaming was requested.

                async def one_shot() -> AsyncGenerator[str, None]:
                    if response_text:
                        yield response_text

                logger.info(
                    "stream=true but got non-generator response; wrapped as one-shot stream"
                )
                return one_shot()

            logger.info(f"查询成功 | 响应长度: {len(response_text)} 字符")
            return response_text

        except Exception as e:
            logger.exception("查询失败")
            raise RuntimeError(f"LightRAG 查询失败: {str(e)}") from e

    async def query_structured(self, request: LightRAGQueryRequest) -> LightRAGQueryResponse:
        """Return one generated answer and its retrieval context, without a second query."""
        if request.stream:
            raise ValueError("Structured queries do not support streaming")
        await self.initialize()
        rag = self.rag
        if rag is None:
            raise RuntimeError("LightRAG initialization did not establish a runtime")
        from lightrag import QueryParam

        top_k = self.default_top_k if request.top_k is None else request.top_k
        result = await rag.aquery_llm(
            request.query,
            param=QueryParam(mode=request.mode, top_k=top_k, stream=False),
        )
        if set(result) == {"llm_response"}:
            from lightrag.prompt import PROMPTS

            # 1.4.9.8 omits raw_data when graph keyword extraction finds no context.
            # Naive mode has this shape for a missing tokenizer, so it remains an error.
            if (
                request.mode in {"local", "global", "hybrid", "mix"}
                and result["llm_response"]["content"] == PROMPTS["fail_response"]
                and result["llm_response"]["is_streaming"] is False
            ):
                result = {
                    "status": "failure",
                    "message": "Query returned no results",
                    "data": {},
                    "metadata": {"failure_reason": "no_results", "mode": request.mode},
                    "llm_response": result["llm_response"],
                }
        if not {"status", "message", "metadata", "data", "llm_response"}.issubset(result):
            raise RuntimeError("LightRAG returned an incomplete query response")
        metadata = result["metadata"]
        if result["status"] != "success" and metadata.get("failure_reason") != "no_results":
            raise RuntimeError(f"LightRAG 查询失败: {result['message']}")
        response = result["llm_response"]["content"]
        if result["llm_response"]["is_streaming"] or not isinstance(response, str):
            raise RuntimeError("LightRAG non-streaming response must contain text")

        return LightRAGQueryResponse(
            query=request.query,
            response=response,
            mode=request.mode,
            metadata={
                **metadata,
                "data": result["data"],
                "top_k": top_k,
                "working_dir": self.working_dir,
            },
        )

    async def insert_documents(
        self,
        documents: List[str],
        batch_size: int = 10,
        *,
        file_paths: list[str] | None = None,
    ) -> LightRAGInsertResponse:
        """
        增量插入文档到 LightRAG

        Parameters
        ----------
        documents : List[str]
            要插入的文档列表
        batch_size : int, optional
            批量处理大小（每处理 batch_size 个文档记录一次进度）

        Returns
        -------
        LightRAGInsertResponse
            插入结果统计
        """
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if file_paths is not None and len(file_paths) != len(documents):
            raise ValueError("file_paths must match the number of documents")
        await self.initialize()
        rag = self.rag
        if rag is None:
            raise RuntimeError("LightRAG initialization did not establish a runtime")
        from lightrag.utils import compute_mdhash_id, sanitize_text_for_encoding

        logger.info(f"开始插入 {len(documents)} 个文档")
        success_count = 0
        failed_count = 0
        errors = []

        for document_number, document in enumerate(documents, start=1):
            try:
                if file_paths is None:
                    track_id = await rag.ainsert(document)
                else:
                    track_id = await rag.ainsert(
                        document, file_paths=file_paths[document_number - 1]
                    )
                statuses = await rag.aget_docs_by_track_id(track_id)
                if not statuses:
                    # Duplicate content is skipped before assigning the new tracking ID.
                    document_id = compute_mdhash_id(
                        sanitize_text_for_encoding(document), prefix="doc-"
                    )
                    statuses = await rag.aget_docs_by_ids(document_id)
                if not statuses:
                    raise RuntimeError("LightRAG did not report a document processing status")
                for status in statuses.values():
                    if status.status != "processed":
                        detail = (
                            f"document status: {status.status}"
                            if status.error_msg is None
                            else status.error_msg
                        )
                        raise RuntimeError(detail)
                success_count += 1
            except Exception as exc:
                failed_count += 1
                error_message = f"文档 {document_number} 插入失败: {exc}"
                errors.append(error_message)
                logger.exception(error_message)
                continue

            if document_number % batch_size == 0:
                logger.info(f"已插入 {document_number}/{len(documents)} 个文档")

        logger.info(f"文档插入完成 | 成功: {success_count} | 失败: {failed_count}")
        return LightRAGInsertResponse(
            total=len(documents),
            success=success_count,
            failed=failed_count,
            errors=errors,
        )

    async def _cleanup_unlocked(self) -> None:
        """Release a runtime while the lifecycle lock is already held."""
        rag = self.rag
        self.rag = None
        self.initialized = False
        if rag is not None:
            await rag.finalize_storages()

    async def cleanup(self) -> None:
        """Close the owned runtime once, including after caller cancellation."""
        with anyio.fail_after(5, shield=True):
            async with self._lifecycle_lock:
                await self._cleanup_unlocked()

    def get_index_stats(self) -> Dict[str, Any]:
        """
        获取索引文件统计信息

        Returns
        -------
        Dict[str, Any]
            索引统计信息，包括文件大小、存在性等
        """
        files_info = {}

        index_files = [
            "graph_chunk_entity_relation.graphml",
            "kv_store_doc_status.json",
            "kv_store_full_docs.json",
            "kv_store_text_chunks.json",
            "vdb_chunks.json",
            "vdb_entities.json",
            "vdb_relationships.json",
        ]

        total_size = 0
        for file_name in index_files:
            file_path = os.path.join(self.working_dir, file_name)
            if os.path.exists(file_path):
                file_size = os.path.getsize(file_path)
                total_size += file_size
                files_info[file_name] = {
                    "exists": True,
                    "size_bytes": file_size,
                    "size_mb": round(file_size / 1024 / 1024, 2),
                }
            else:
                files_info[file_name] = {
                    "exists": False,
                    "size_bytes": 0,
                    "size_mb": 0,
                }

        return {
            "working_dir": self.working_dir,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "files": files_info,
            "initialized": self.initialized,
        }


# 全局服务实例（单例模式）
_lightrag_service: Optional[LightRAGService] = None


def get_lightrag_service() -> LightRAGService:
    """
    获取 LightRAG 服务单例

    Returns
    -------
    LightRAGService
        LightRAG 服务实例
    """
    global _lightrag_service
    if _lightrag_service is None:
        _lightrag_service = LightRAGService(
            default_mode=settings.LIGHTRAG_RETRIEVAL_MODE,
            default_top_k=settings.LIGHTRAG_TOP_K,
        )
    return _lightrag_service


async def cleanup_lightrag_service() -> None:
    """Release an existing singleton without initializing an unused service."""
    global _lightrag_service
    service = _lightrag_service
    try:
        if service is not None:
            await service.cleanup()
    finally:
        _lightrag_service = None
