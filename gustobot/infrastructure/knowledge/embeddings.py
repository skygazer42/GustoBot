"""OpenAI-compatible embeddings with explicit budgets and provider telemetry."""

import asyncio
import math
import re
from collections.abc import Callable, Mapping, Sequence
from numbers import Real
from threading import Lock
from time import perf_counter
from typing import Literal

import httpx
from loguru import logger
from openai import APIConnectionError, OpenAI

from gustobot.infrastructure.knowledge.request_telemetry import record_provider_event

EmbeddingPurpose = Literal["document", "candidate", "build"]
TelemetrySnapshot = dict[str, int | float | str]
TelemetryCallback = Callable[[str, Mapping[str, int | float | str]], None]


class EmbeddingResponseError(ValueError):
    """Malformed provider data, before SDK response coercion."""


class EmbeddingTelemetry:
    """Counters shared safely by calls dispatched to worker threads."""

    def __init__(self, purpose: EmbeddingPurpose) -> None:
        self._lock = Lock()
        self._values: TelemetrySnapshot = {
            "purpose": purpose,
            "logical_calls": 0,
            "provider_batches": 0,
            "http_attempts": 0,
            "texts": 0,
            "input_characters": 0,
            "elapsed_seconds": 0.0,
        }

    def record(self, **increments: float) -> None:
        with self._lock:
            for name, value in increments.items():
                current = self._values[name]
                if isinstance(current, str):
                    raise TypeError("Telemetry counter must be numeric")
                self._values[name] = current + value

    def snapshot(self) -> TelemetrySnapshot:
        with self._lock:
            return dict(self._values)


class OpenAICompatibleEmbeddings:
    """The wrapper owns its SDK client, including an explicitly supplied HTTP client."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        dimension: int | None = None,
        max_batch_size: int = 64,
        request_timeout: float = 60.0,
        purpose: EmbeddingPurpose = "document",
        max_retries: int = 0,
        telemetry_callback: TelemetryCallback | None = None,
        http_client: httpx.Client | None = None,
        space_fingerprint: str | None = None,
    ) -> None:
        if max_batch_size <= 0:
            raise ValueError("max_batch_size must be positive")
        if dimension is not None and dimension <= 0:
            raise ValueError("Embedding dimension must be positive")
        if not math.isfinite(request_timeout) or request_timeout <= 0:
            raise ValueError("Embedding request timeout must be finite and positive")
        if purpose not in {"document", "candidate", "build"}:
            raise ValueError("Unknown embedding purpose")
        if max_retries != 0:
            raise ValueError(
                "Embedding SDK retries must be zero; retry as a separate logical attempt"
            )
        if (
            space_fingerprint is not None
            and re.fullmatch(r"[0-9a-f]{64}", space_fingerprint) is None
        ):
            raise ValueError("Embedding cache space must be a SHA-256 fingerprint")
        self.space_fingerprint = space_fingerprint
        self.model = model
        self.dimension = dimension
        self.max_batch_size = max_batch_size
        self.request_timeout = request_timeout
        self.purpose = purpose
        self.telemetry = EmbeddingTelemetry(purpose)
        self._telemetry_callback = telemetry_callback
        self._observed_dimension = dimension
        self._dimension_lock = Lock()

        transport_client = http_client
        try:
            if transport_client is None:
                transport_client = httpx.Client(
                    timeout=request_timeout,
                    event_hooks={
                        "request": [self._record_http_attempt],
                        "response": [self._validate_http_vectors],
                    },
                )
            else:
                transport_client.event_hooks["response"].append(self._validate_http_vectors)
                transport_client.event_hooks["request"].append(self._record_http_attempt)
            self._client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=request_timeout,
                max_retries=max_retries,
                http_client=transport_client,
            )
        except ValueError as exc:
            if transport_client is not None and http_client is None:
                transport_client.close()
            if http_client is not None or "Unknown scheme for proxy URL" not in str(exc):
                raise
            logger.warning(
                "Unsupported environment proxy scheme; disabling embedding proxy discovery"
            )
            transport_client = httpx.Client(
                trust_env=False,
                timeout=request_timeout,
                event_hooks={
                    "request": [self._record_http_attempt],
                    "response": [self._validate_http_vectors],
                },
            )
            try:
                self._client = OpenAI(
                    api_key=api_key,
                    base_url=base_url,
                    timeout=request_timeout,
                    max_retries=max_retries,
                    http_client=transport_client,
                )
            except BaseException:
                transport_client.close()
                raise
        except BaseException:
            if transport_client is not None and http_client is None:
                transport_client.close()
            raise

    def _event(self, event: str, **increments: float) -> None:
        self.telemetry.record(**increments)
        record_provider_event(self.purpose, **increments)
        if self._telemetry_callback is not None:
            self._telemetry_callback(event, self.telemetry.snapshot())

    def _record_http_attempt(self, request: httpx.Request) -> None:
        self._event("http_attempt", http_attempts=1)

    def _validate_http_vectors(self, response: httpx.Response) -> None:
        if not response.is_success:
            return
        response.read()
        try:
            payload = response.json()
            rows = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                raise EmbeddingResponseError("Embedding API returned invalid vector data")
            for row in rows:
                if not isinstance(row, dict) or type(row.get("index")) is not int:
                    raise ValueError("Embedding API returned invalid batch indices")
                values = row.get("embedding")
                if not isinstance(values, list):
                    raise EmbeddingResponseError("Embedding API returned nonnumeric vector values")
                self._validate_vector(values)
        except ValueError as error:
            raise EmbeddingResponseError(str(error)) from error

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        if self.space_fingerprint is not None:
            from gustobot.infrastructure.knowledge.request_telemetry import (
                request_query_vector,
            )

            return request_query_vector(
                self.space_fingerprint, text, self.purpose, lambda: self._embed([text])[0]
            )
        return self._embed([text])[0]

    async def aembed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return await asyncio.to_thread(self.embed_documents, texts)

    async def aembed_query(self, text: str) -> list[float]:
        return await asyncio.to_thread(self.embed_query, text)

    def _validate_vector(self, values: Sequence[float]) -> list[float]:
        if not values:
            raise ValueError("Embedding API returned an empty vector")
        if any(isinstance(value, bool) or not isinstance(value, Real) for value in values):
            raise ValueError("Embedding API returned nonnumeric vector values")
        vector = [float(value) for value in values]
        if not all(math.isfinite(value) for value in vector):
            raise ValueError("Embedding API returned non-finite vector values")
        with self._dimension_lock:
            if self._observed_dimension is None:
                self._observed_dimension = len(vector)
            if len(vector) != self._observed_dimension:
                raise ValueError(f"Embedding dimension must be {self._observed_dimension}")
        return vector

    def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        ordered_inputs = [text.strip() or " " for text in texts]
        self._event(
            "logical_call",
            logical_calls=1,
            texts=len(ordered_inputs),
            input_characters=sum(map(len, ordered_inputs)),
        )
        started = perf_counter()
        try:
            vectors: list[list[float]] = []
            for start in range(0, len(ordered_inputs), self.max_batch_size):
                batch = ordered_inputs[start : start + self.max_batch_size]
                self._event("provider_batch", provider_batches=1)
                response = self._client.embeddings.create(
                    model=self.model,
                    input=batch,
                    timeout=self.request_timeout,
                    encoding_format="float",
                )
                if len(response.data) != len(batch) or any(
                    type(item.index) is not int for item in response.data
                ):
                    raise ValueError("Embedding API returned invalid batch indices or vector count")
                ordered_items = sorted(response.data, key=lambda item: item.index)
                if [item.index for item in ordered_items] != list(range(len(batch))):
                    raise ValueError("Embedding API returned invalid batch indices or vector count")
                vectors.extend(self._validate_vector(item.embedding) for item in ordered_items)
            return vectors
        except APIConnectionError as error:
            if isinstance(error.__cause__, EmbeddingResponseError):
                raise error.__cause__ from error
            raise
        finally:
            self._event("logical_complete", elapsed_seconds=perf_counter() - started)

    def close(self) -> None:
        self._client.close()
