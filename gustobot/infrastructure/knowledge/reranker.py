"""Reranker integration supporting multiple providers."""

import asyncio
import math
from time import perf_counter
from traceback import extract_tb
from typing import Any

import httpx
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from gustobot.config import settings
from gustobot.infrastructure.knowledge.request_telemetry import record_provider_event


class _RerankResult(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    index: int = Field(ge=0)
    relevance_score: float | None = Field(default=None, allow_inf_nan=False)
    score: float | None = Field(default=None, allow_inf_nan=False)


class Reranker:
    """Reranker supporting Cohere, Jina, Voyage, and custom APIs."""

    def __init__(self) -> None:
        self.enabled = settings.RERANK_ENABLED
        self.provider = settings.RERANK_PROVIDER.lower()
        self.api_format = settings.RERANK_API_FORMAT
        self.base_url = settings.RERANK_BASE_URL
        self.endpoint = settings.RERANK_ENDPOINT
        self.model = settings.RERANK_MODEL
        self.api_key = settings.RERANK_API_KEY
        self.top_n = settings.RERANK_TOP_N
        self.timeout = settings.RERANK_TIMEOUT

        if not self.enabled:
            logger.info("Reranker disabled via config")
            return

        if self.top_n <= 0:
            raise ValueError("RERANK_TOP_N must be positive")
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("RERANK_TIMEOUT must be finite and positive")
        if not self.model.strip():
            raise ValueError("RERANK_MODEL must not be empty")

        if not self.provider or not self.api_key:
            logger.warning("Reranker enabled but missing provider or API key, disabling")
            self.enabled = False
            return

        logger.info(
            "Reranker initialized: provider={}, model={}",
            self.provider,
            self.model,
        )

    async def rerank(
        self,
        query: str,
        documents: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Rerank documents based on relevance to query."""
        if type(top_k) is not int or top_k < 0:
            raise ValueError("Reranker top_k must be a nonnegative integer")
        if not self.enabled or not documents or top_k == 0:
            return documents[:top_k]

        record_provider_event(
            "rerank",
            logical_calls=1,
            texts=len(documents) + 1,
            input_characters=len(query) + sum(len(doc["content"]) for doc in documents),
        )
        started = perf_counter()
        try:
            if self.provider == "custom":
                ranked = await self._custom_rerank(query, documents, top_k)
            elif self.provider == "cohere":
                ranked = await asyncio.to_thread(self._cohere_rerank, query, documents, top_k)
            elif self.provider == "jina":
                ranked = await self._jina_rerank(query, documents, top_k)
            elif self.provider == "voyage":
                ranked = await self._voyage_rerank(query, documents, top_k)
            else:
                logger.warning("Unsupported reranker provider: {}", self.provider)
                return documents[:top_k]

            if ranked:
                return ranked
        except Exception as exc:  # noqa: BLE001
            # Provider exception text and frame locals can contain credentials.
            stack = " -> ".join(
                f"{frame.filename}:{frame.lineno} ({frame.name})"
                for frame in extract_tb(exc.__traceback__)
            )
            logger.error(
                "Reranker provider {} failed ({}), stack={}",
                self.provider,
                type(exc).__name__,
                stack,
            )
        finally:
            record_provider_event("rerank", elapsed_seconds=perf_counter() - started)

        return documents[:top_k]

    @staticmethod
    def _http_attempt(request: httpx.Request) -> None:
        record_provider_event("rerank", http_attempts=1)

    @staticmethod
    async def _async_http_attempt(request: httpx.Request) -> None:
        record_provider_event("rerank", http_attempts=1)

    async def _custom_rerank(
        self,
        query: str,
        documents: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Custom reranker API (e.g., BGE reranker)."""
        if not self.base_url:
            raise ValueError("Custom reranker requires RERANK_BASE_URL")

        # 准备文档内容
        texts = [doc["content"] for doc in documents]

        # 构建请求
        url = f"{self.base_url.rstrip('/')}{self.endpoint}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        if self.api_format == "standard":
            payload = {
                "model": self.model,
                "query": query,
                "documents": texts,
                "top_n": min(self.top_n, len(documents), top_k),
                "return_documents": False,
            }
        else:
            payload = {
                "model": self.model,
                "input": {"query": query, "documents": texts},
                "parameters": {
                    "return_documents": True,
                    "top_n": min(self.top_n, len(documents)),
                },
            }

        async with httpx.AsyncClient(
            timeout=self.timeout,
            trust_env=False,
            event_hooks={"request": [self._async_http_attempt]},
        ) as client:
            record_provider_event("rerank", provider_batches=1)
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        results = data["results"] if self.api_format == "standard" else data["output"]["results"]

        if not results:
            logger.warning("Custom reranker returned no results")
            return documents[:top_k]

        return self._process_rerank_results(results, documents, top_k)

    async def _jina_rerank(
        self,
        query: str,
        documents: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Jina AI reranker."""
        texts = [doc["content"] for doc in documents]

        url = "https://api.jina.ai/v1/rerank"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "query": query,
            "documents": texts,
            "top_n": min(self.top_n, len(documents)),
        }

        async with httpx.AsyncClient(
            timeout=self.timeout,
            trust_env=False,
            event_hooks={"request": [self._async_http_attempt]},
        ) as client:
            record_provider_event("rerank", provider_batches=1)
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        results = data["results"]
        return self._process_rerank_results(results, documents, top_k)

    async def _voyage_rerank(
        self,
        query: str,
        documents: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Voyage AI reranker."""
        texts = [doc["content"] for doc in documents]

        url = "https://api.voyageai.com/v1/rerank"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "query": query,
            "documents": texts,
            "top_k": min(self.top_n, len(documents)),
        }

        async with httpx.AsyncClient(
            timeout=self.timeout,
            trust_env=False,
            event_hooks={"request": [self._async_http_attempt]},
        ) as client:
            record_provider_event("rerank", provider_batches=1)
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        results = data["data"]
        return self._process_rerank_results(results, documents, top_k)

    def _cohere_rerank(
        self,
        query: str,
        documents: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Cohere reranker (synchronous)."""
        try:
            from cohere import Client as CohereClient
        except ImportError as exc:
            raise RuntimeError("cohere package not installed") from exc

        texts = [doc["content"] for doc in documents]

        with httpx.Client(
            timeout=self.timeout, trust_env=False, event_hooks={"request": [self._http_attempt]}
        ) as transport:
            client = CohereClient(
                token=self.api_key, timeout=self.timeout, httpx_client=transport, max_retries=0
            )
            record_provider_event("rerank", provider_batches=1)
            response = client.rerank(
                query=query,
                documents=texts,
                top_n=min(self.top_n, len(documents)),
                model=self.model,
                request_options={"max_retries": 0, "timeout": self.timeout},
            )

        results = [
            {"index": r.index, "relevance_score": r.relevance_score} for r in response.results
        ]

        return self._process_rerank_results(results, documents, top_k)

    @staticmethod
    def _process_rerank_results(
        results: list[dict[str, Any]],
        documents: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Process reranker results into reordered document list."""
        reranked = []
        ranked_indices = set()

        for item in results:
            result = _RerankResult.model_validate(item)
            idx = result.index
            if idx >= len(documents) or idx in ranked_indices:
                raise ValueError("Reranker returned an invalid or duplicate document index")
            score = result.relevance_score
            if score is None:
                score = result.score
            if score is None:
                raise ValueError("Reranker result requires a relevance score")
            doc = dict(documents[idx])
            doc["rerank_score"] = score
            reranked.append(doc)
            ranked_indices.add(idx)

        # 添加未被重排的文档
        for index, doc in enumerate(documents):
            if index not in ranked_indices:
                reranked.append(doc)

        return reranked[:top_k]
