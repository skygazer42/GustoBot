"""
Embedding helpers for the knowledge base module.

Provides a simple OpenAI-compatible embedding client that can talk to OpenAI,
DashScope (Qwen), or any service that exposes the compatible `/embeddings`
endpoint. We intentionally avoid depending on LangChain abstractions here so
that we can fine-tune the request payload for vendors that only support a
subset of OpenAI parameters (e.g., DashScope).
"""

from typing import List, Optional, Sequence

from loguru import logger
from openai import OpenAI
import httpx


class OpenAICompatibleEmbeddings:
    """Thin wrapper around the official OpenAI client for embedding requests."""

    def __init__(
        self,
        *,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        dimension: Optional[int] = None,
        max_batch_size: int = 64,
        request_timeout: Optional[float] = 60.0,
    ) -> None:
        if max_batch_size <= 0:
            raise ValueError("max_batch_size must be positive")
        self.model = model
        self.dimension = dimension
        self.max_batch_size = max_batch_size
        self.request_timeout = request_timeout

        try:
            self._client = OpenAI(api_key=api_key, base_url=base_url)
        except ValueError as exc:
            # Some environments set ALL_PROXY to an unsupported scheme like `socks://...`,
            # which makes httpx (and therefore the OpenAI client) crash at import-time.
            # Fall back to a client that ignores env proxies to keep the KB functional.
            if "Unknown scheme for proxy URL" in str(exc):
                logger.warning(
                    "Invalid proxy env detected; disabling trust_env for OpenAI client: {}", exc
                )
                self._client = OpenAI(
                    api_key=api_key, base_url=base_url, http_client=httpx.Client(trust_env=False)
                )
            else:
                raise
        logger.info(
            "Initialised OpenAI-compatible embeddings client (model={}, base_url={})",
            model,
            base_url or "https://api.openai.com/v1",
        )

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        """Embed a sequence of texts."""
        return self._embed(texts)

    def embed_query(self, text: str) -> List[float]:
        """Embed a single query string."""
        embeddings = self._embed([text])
        return embeddings[0]

    def _embed(self, texts: Sequence[str]) -> List[List[float]]:
        if not texts:
            return []

        ordered_inputs: List[str] = []
        for text in texts:
            value = text.strip()
            if not value:
                # DashScope 对空字符串会报错，使用单空格保持顺序
                value = " "
            ordered_inputs.append(value)

        embeddings_flat: List[List[float]] = []
        for start in range(0, len(ordered_inputs), self.max_batch_size):
            batch = ordered_inputs[start : start + self.max_batch_size]
            response = self._client.embeddings.create(
                model=self.model,
                input=batch,
                timeout=self.request_timeout,
            )

            ordered_items = sorted(response.data, key=lambda item: item.index)
            if [item.index for item in ordered_items] != list(range(len(batch))):
                raise ValueError("Embedding API returned invalid batch indices or vector count")

            for item in ordered_items:
                vector = list(item.embedding)
                if not vector:
                    raise ValueError("Embedding API returned an empty vector")
                if self.dimension is not None and len(vector) != self.dimension:
                    logger.warning(
                        "Embedding dimension mismatch: expected={} actual={}",
                        self.dimension,
                        len(vector),
                    )
                embeddings_flat.append(vector)

        return embeddings_flat

    def close(self) -> None:
        self._client.close()
