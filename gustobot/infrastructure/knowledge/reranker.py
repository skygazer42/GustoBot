"""Reranker integration supporting multiple providers."""

import asyncio
import httpx
from typing import Any, Dict, List

from loguru import logger

from gustobot.config import settings


class Reranker:
    """Reranker supporting Cohere, Jina, Voyage, and custom APIs."""

    def __init__(self) -> None:
        self.enabled = settings.RERANK_ENABLED
        self.provider = settings.RERANK_PROVIDER.lower()
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
        if not self.model.strip():
            raise ValueError("RERANK_MODEL must not be empty")

        if not self.provider or not self.api_key:
            logger.warning("Reranker enabled but missing provider or API key, disabling")
            self.enabled = False
            return

        logger.info(
            "Reranker initialized: provider={}, model={}, base_url={}",
            self.provider,
            self.model,
            self.base_url,
        )

    async def rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """Rerank documents based on relevance to query."""
        if not self.enabled or not documents:
            return documents[:top_k]

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
                logger.warning(f"Unsupported reranker provider: {self.provider}")
                return documents[:top_k]

            if ranked:
                return ranked
        except Exception as exc:
            logger.exception("Reranker failed: {}", exc)

        return documents[:top_k]

    async def _custom_rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """Custom reranker API (e.g., BGE reranker)."""
        if not self.base_url:
            logger.error("Custom reranker requires RERANK_BASE_URL")
            return documents[:top_k]

        # 准备文档内容
        texts = [doc["content"] for doc in documents]

        # 构建请求
        url = f"{self.base_url.rstrip('/')}{self.endpoint}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # DashScope API 格式
        payload = {
            "model": self.model,
            "input": {
                "query": query,
                "documents": texts,
            },
            "parameters": {
                "return_documents": True,
                "top_n": min(self.top_n, len(documents)),
            },
        }

        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        # 解析响应 (DashScope 格式: output.results)
        output = data.get("output", {})
        results = output.get("results", [])

        if not results:
            logger.warning("Custom reranker returned no results")
            return documents[:top_k]

        return self._process_rerank_results(results, documents, top_k)

    async def _jina_rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_k: int,
    ) -> List[Dict[str, Any]]:
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

        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        results = data.get("results", [])
        return self._process_rerank_results(results, documents, top_k)

    async def _voyage_rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_k: int,
    ) -> List[Dict[str, Any]]:
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

        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        results = data.get("data", [])
        return self._process_rerank_results(results, documents, top_k)

    def _cohere_rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """Cohere reranker (synchronous)."""
        try:
            from cohere import Client as CohereClient
        except ImportError as exc:
            raise RuntimeError("cohere package not installed") from exc

        client = CohereClient(self.api_key)
        texts = [doc["content"] for doc in documents]

        response = client.rerank(
            query=query,
            documents=texts,
            top_n=min(self.top_n, len(documents)),
            model=self.model,
        )

        results = [
            {"index": r.index, "relevance_score": r.relevance_score} for r in response.results
        ]

        return self._process_rerank_results(results, documents, top_k)

    def _process_rerank_results(
        self,
        results: List[Dict[str, Any]],
        documents: List[Dict[str, Any]],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """Process reranker results into reordered document list."""
        reranked = []
        ranked_indices = set()

        for item in results:
            idx = item.get("index")
            score = item.get("relevance_score")
            if score is None:
                score = item.get("score")

            if idx is not None and 0 <= idx < len(documents):
                doc = dict(documents[idx])
                if score is not None:
                    doc["rerank_score"] = float(score)
                reranked.append(doc)
                ranked_indices.add(idx)

        # 添加未被重排的文档
        for index, doc in enumerate(documents):
            if index not in ranked_indices:
                reranked.append(doc)

        return reranked[:top_k]
