import logging
import os
from enum import Enum
from typing import List

import numpy as np
import requests
from openai import OpenAI

from kb_service.core.config import Config

logger = logging.getLogger(__name__)


class EmbeddingProvider(str, Enum):
    OPENAI = "openai"
    OLLAMA = "ollama"


class EmbeddingClient:
    """Uniform embedding interface with provider specific fallbacks."""

    def __init__(self, config: Config):
        self.config = config
        self.provider = EmbeddingProvider(config.embedding_provider.lower())
        self.dimension = config.embedding_dimension
        self._setup_client()

    def _setup_client(self) -> None:
        if self.provider == EmbeddingProvider.OPENAI:
            api_key = self.config.embedding_api_key or os.getenv("OPENAI_API_KEY")
            self.openai_client = OpenAI(api_key=api_key, base_url=self.config.embedding_base_url)
            model_dimensions = {
                "text-embedding-3-small": 1536,
                "text-embedding-3-large": 3072,
                "text-embedding-ada-002": 1536,
            }
            self.dimension = model_dimensions.get(self.config.embedding_model, self.dimension)

        elif self.provider == EmbeddingProvider.OLLAMA:
            base = (
                self.config.embedding_base_url
                or self.config.llm_base_url
                or "http://localhost:11434"
            )
            self.ollama_url = f"{base.rstrip('/')}/api/embeddings"

    def embed_texts(self, texts: List[str]) -> np.ndarray:
        if not texts:
            return np.array([])

        if self.provider == EmbeddingProvider.OPENAI:
            return self._embed_openai(texts)
        if self.provider == EmbeddingProvider.OLLAMA:
            return self._embed_ollama(texts)
        raise ValueError(f"Unsupported embedding provider: {self.provider}")

    def _embed_openai(self, texts: List[str]) -> np.ndarray:
        max_batch_size = 100
        all_embeddings: List[List[float]] = []
        for start in range(0, len(texts), max_batch_size):
            batch = texts[start : start + max_batch_size]
            response = self.openai_client.embeddings.create(
                model=self.config.embedding_model,
                input=batch,
            )
            ordered_items = sorted(response.data, key=lambda item: item.index)
            if [item.index for item in ordered_items] != list(range(len(batch))):
                raise ValueError("Embedding API returned invalid batch indices or vector count")
            all_embeddings.extend(item.embedding for item in ordered_items)
        return np.array(all_embeddings, dtype=np.float32)

    def _embed_ollama(self, texts: List[str]) -> np.ndarray:
        embeddings: List[List[float]] = []
        for text in texts:
            with requests.post(
                self.ollama_url,
                json={"model": self.config.embedding_model, "prompt": text},
                timeout=60,
            ) as resp:
                resp.raise_for_status()
                payload = resp.json()
            embeddings.append(payload["embedding"])
        return np.array(embeddings, dtype=np.float32)

    def close(self) -> None:
        if self.provider == EmbeddingProvider.OPENAI:
            self.openai_client.close()
