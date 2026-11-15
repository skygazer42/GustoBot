import logging
import math
import time
from typing import Iterable, List, Optional

import requests

from kb_service.core.config import Config

logger = logging.getLogger(__name__)


class RerankAPIError(Exception):
    """Reranker API 调用异常"""

    pass


class RerankerClient:
    """
    重排序客户端，支持两种模式：
    1. 自建 Reranker 服务
    2. Cohere API
    """

    def __init__(self, config: Config):
        self.config = config
        self.timeout = config.rerank_timeout
        self.provider = config.rerank_provider.lower()
        self.api_key: Optional[str]
        self.model: Optional[str]

        # 根据 provider 初始化
        if self.provider == "cohere":
            if not config.cohere_api_key:
                raise ValueError("使用 Cohere 模式时必须配置 COHERE_API_KEY")
            self.mode = "cohere"
            self.endpoint = config.cohere_rerank_url
            self.api_key = config.cohere_api_key
            self.model = config.cohere_rerank_model
            logger.info("Reranker 使用 Cohere API 模式 (model=%s)", self.model)

        elif self.provider == "custom":
            # 构建完整 URL
            if config.rerank_base_url:
                # 如果 endpoint 是完整 URL，直接使用；否则拼接
                if config.rerank_endpoint.startswith("http"):
                    self.endpoint = config.rerank_endpoint
                else:
                    base = config.rerank_base_url.rstrip("/")
                    path = config.rerank_endpoint.lstrip("/")
                    self.endpoint = f"{base}/{path}"
            elif config.rerank_endpoint.startswith("http"):
                # endpoint 本身就是完整 URL
                self.endpoint = config.rerank_endpoint
            else:
                raise ValueError(
                    "自建服务模式需要配置 RERANK_BASE_URL 或完整的 RERANK_ENDPOINT URL"
                )

            self.mode = "custom"
            self.api_key = config.rerank_api_key
            self.model = config.rerank_model  # 可选的模型名称
            if self.model:
                logger.info(
                    "Reranker 使用自建服务模式 (endpoint=%s, model=%s)", self.endpoint, self.model
                )
            else:
                logger.info("Reranker 使用自建服务模式 (endpoint=%s)", self.endpoint)

        else:
            raise ValueError(
                f"不支持的 RERANK_PROVIDER: {config.rerank_provider}，仅支持 'cohere' 或 'custom'"
            )

    def rerank(
        self,
        query: str,
        candidates: Iterable[dict],
        top_n: Optional[int] = None,
    ) -> Optional[List[dict]]:
        """
        对候选文档进行重排序

        Args:
            query: 查询文本
            candidates: 候选文档列表，每项包含 id, text/content
            top_n: 返回前 N 个结果（None 则使用配置）

        Returns:
            重排序后的结果列表，格式: [{"id": str, "score": float}, ...]
        """
        documents = []
        for item in candidates:
            doc_id = str(item["id"])
            text = item["text"] if "text" in item else item["content"]
            documents.append(
                {
                    "id": doc_id,
                    "text": text,
                }
            )

        if not documents:
            return None

        if top_n is None:
            top_n = self.config.rerank_top_n

        if top_n < 0:
            raise ValueError("top_n cannot be negative")
        if top_n == 0:
            return []
        # 根据模式调用不同的 API
        if self.mode == "cohere":
            return self._rerank_cohere(query, documents, top_n)
        else:
            return self._rerank_custom(query, documents, top_n)

    def _rerank_cohere(
        self,
        query: str,
        documents: List[dict],
        top_n: int,
    ) -> Optional[List[dict]]:
        """调用 Cohere Rerank API"""
        # Cohere API 期望的文档格式是字符串列表
        doc_texts = [doc["text"] for doc in documents]

        payload = {
            "model": self.model,
            "query": query,
            "documents": doc_texts,
            "top_n": min(top_n, len(doc_texts)),
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        start = time.time()
        try:
            response = self._post_with_retry(
                self.endpoint,
                headers=headers,
                payload=payload,
                retries=3,
            )
            elapsed = (time.time() - start) * 1000
            logger.info("Cohere Rerank 完成 (%.1f ms, %d 文档)", elapsed, len(doc_texts))
        except Exception as exc:
            elapsed = (time.time() - start) * 1000
            logger.warning("Cohere Rerank 请求失败(%.1f ms): %s", elapsed, exc, exc_info=True)
            return None

        # Cohere API 返回格式: {"results": [{"index": int, "relevance_score": float}, ...]}
        results = response.get("results", [])
        if not results:
            logger.warning("Cohere Rerank 返回空结果")
            return None

        # 转换为统一格式，使用原始 documents 的 id
        reranked = []
        for item in results:
            index = item.get("index")
            score = item.get("relevance_score")
            if index is None or score is None:
                continue
            if 0 <= index < len(documents):
                reranked.append(
                    {
                        "id": documents[index]["id"],
                        "score": float(score),
                    }
                )

        # Cohere 已按分数排序，但我们再确保一次
        reranked.sort(key=lambda x: x["score"], reverse=True)
        return reranked or None

    def _rerank_custom(
        self,
        query: str,
        documents: List[dict],
        top_n: int,
    ) -> Optional[List[dict]]:
        """调用自建 Reranker 服务"""
        # 提取文本列表（服务期望字符串数组，不是dict数组）
        doc_texts = [doc["text"] for doc in documents]

        payload = {
            "query": query,
            "documents": doc_texts,
        }
        # 如果配置了 model，则添加到请求中
        if self.model:
            payload["model"] = self.model

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        start = time.time()
        try:
            with requests.post(
                self.endpoint,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            ) as response:
                response.raise_for_status()
                data = response.json()
            elapsed = (time.time() - start) * 1000
            logger.info("自建 Rerank 完成 (%.1f ms)", elapsed)
        except Exception as exc:
            elapsed = (time.time() - start) * 1000
            logger.warning("自建 Reranker 请求失败(%.1f ms): %s", elapsed, exc, exc_info=True)
            return None

        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            logger.warning("自建 Reranker 响应格式无效: %s", data)
            return None

        reranked = []
        for item in results:
            # 服务返回的是index和relevance_score，需要映射回原始文档
            index = item.get("index")
            score = item.get("relevance_score", item.get("score"))
            if index is None or score is None:
                continue
            if 0 <= index < len(documents):
                try:
                    reranked.append({"id": documents[index]["id"], "score": float(score)})
                except (TypeError, ValueError, KeyError):
                    continue

        reranked.sort(key=lambda x: x["score"], reverse=True)
        return reranked[:top_n] or None

    def _post_with_retry(
        self,
        url: str,
        headers: dict,
        payload: dict,
        retries: int = 3,
        backoff: float = 0.8,
    ) -> dict:
        """带重试的 POST 请求，用于处理 API 限流"""
        if retries <= 0:
            raise ValueError("retries must be positive")
        last_error = None
        for attempt in range(retries):
            retry_after = None
            try:
                with requests.post(
                    url, headers=headers, json=payload, timeout=self.timeout
                ) as response:
                    retry_after = response.headers.get("Retry-After")
                    response.raise_for_status()
                    response_payload: object = response.json()
                    if not isinstance(response_payload, dict):
                        raise RerankAPIError("Rerank response must be a JSON object")
                    return response_payload
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
            except requests.HTTPError as exc:
                if exc.response.status_code not in {429, 500, 502, 503, 504}:
                    raise
                last_error = exc
            if attempt == retries - 1:
                break
            delay = backoff * (2**attempt)
            if retry_after is not None:
                try:
                    delay = max(delay, float(retry_after))
                except ValueError:
                    pass  # HTTP-date Retry-After falls back to bounded backoff.
            time.sleep(min(30.0, max(0.0, delay)))
        raise RerankAPIError(f"Rerank request failed after {retries} attempts") from last_error

    @staticmethod
    def zscore_normalize(scores: List[float]) -> List[float]:
        """Z-score 标准化"""
        if not scores or len(scores) == 1:
            return scores
        mean = sum(scores) / len(scores)
        variance = sum((x - mean) ** 2 for x in scores) / max(1, len(scores) - 1)
        std = math.sqrt(variance) if variance > 0 else 1.0
        return [(x - mean) / std for x in scores]
