import hashlib
import json
import math
from collections.abc import Awaitable, Sequence
from datetime import datetime
from typing import Annotated, Any, cast

import httpx
from loguru import logger
from pydantic import BaseModel, Field, TypeAdapter, ValidationError
from redis.asyncio import Redis

from gustobot.config import settings

_EmbeddingVector = list[Annotated[float, Field(strict=True, allow_inf_nan=False)]]


class _EmbeddingItem(BaseModel):
    """One cached vector with finite, strictly typed float values."""

    embedding: _EmbeddingVector = Field(min_length=1)


class _EmbeddingResponse(BaseModel):
    """Expected single-item response shape for an embedding cache hit."""

    data: list[_EmbeddingItem] = Field(min_length=1, max_length=1)


class _HistoryEntry(BaseModel):
    """Validated serialized conversation message stored in Redis."""

    role: str
    content: str
    metadata: dict[str, Any]
    timestamp: str


_CACHED_VECTOR = TypeAdapter(_EmbeddingVector)


def _escape_redis_glob(namespace: str) -> str:
    """Keep a literal namespace inside SCAN's Redis glob syntax."""
    return "".join(
        f"\\{character}" if character in "\\*?[]" else character for character in namespace
    )


def _now_timestamp() -> float:
    """Return a unix timestamp."""
    return datetime.now().timestamp()


def _iso_now() -> str:
    """Return current time in ISO format."""
    return datetime.now().isoformat()


def _decode(value: object) -> str:
    """Decode Redis bytes payloads to string."""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, str):
        return value
    raise TypeError("Redis payload must be bytes or text")


def _cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not a or not b:
        return 0.0

    numerator = sum(x * y for x, y in zip(a, b))
    if numerator == 0:
        return 0.0

    sum_a = sum(x * x for x in a)
    sum_b = sum(y * y for y in b)
    denom = math.sqrt(sum_a) * math.sqrt(sum_b)
    if denom == 0:
        return 0.0
    return numerator / denom


class RedisSemanticCache:
    """Semantic cache backed by Redis storing embeddings alongside responses."""

    def __init__(
        self,
        *,
        redis_client: Redis | None = None,
        redis_url: str | None = None,
        model_name: str | None = None,
        score_threshold: float | None = None,
        prefix: str = "semantic",
        max_cache_size: int | None = None,
        ttl: int | None = None,
    ) -> None:
        self._owns_redis = redis_client is None
        self._redis = (
            Redis.from_url(
                settings.REDIS_URL if redis_url is None else redis_url,
                decode_responses=False,
                socket_connect_timeout=5,
                socket_timeout=30,
            )
            if redis_client is None
            else redis_client
        )
        self.model_name = settings.EMBEDDING_MODEL if model_name is None else model_name
        if not self.model_name.strip():
            raise ValueError("model_name must not be empty")
        self.score_threshold = (
            settings.REDIS_CACHE_THRESHOLD if score_threshold is None else score_threshold
        )
        self.prefix = prefix
        self.max_cache_size = (
            settings.REDIS_CACHE_MAX_SIZE if max_cache_size is None else max_cache_size
        )
        self.ttl = settings.REDIS_CACHE_EXPIRE if ttl is None else ttl
        if self.ttl < 1:
            raise ValueError("ttl must be positive")
        if self.max_cache_size < 0:
            raise ValueError("max_cache_size must be non-negative")

    async def lookup(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        scope: str | None = None,
    ) -> str | None:
        """
        Try to find a cached response for the latest user message in `messages`.

        Args:
            messages: Chat messages containing at least `role` and `content`.
            scope: Optional namespace (e.g. session/user ID) to isolate caches.
        """
        user_message = self._last_user_message(messages)
        if not user_message:
            return None

        try:
            current_vector = await self._get_embedding(user_message)
        # An unavailable optional embedding cache must not fail the chat request.
        except Exception:  # noqa: BLE001
            # Embedding service failure should not break chat flow.
            logger.exception("Embedding service failed during semantic cache lookup")
            return None

        namespace = self._namespace(scope)
        pattern = f"{_escape_redis_glob(namespace)}:vec:*"
        best_similarity = -math.inf
        best_hash: str | None = None

        async for raw_key in self._redis.scan_iter(pattern):
            cached_vector_raw = await self._redis.get(raw_key)
            if not cached_vector_raw:
                continue

            try:
                cached_vector = _CACHED_VECTOR.validate_json(_decode(cached_vector_raw))
            except ValidationError:
                logger.warning("Failed to decode cached vector for key {}", _decode(raw_key))
                continue

            if len(cached_vector) != len(current_vector):
                logger.warning("Skipping cached vector with incompatible dimension: {}", raw_key)
                continue
            similarity = _cosine_similarity(current_vector, cached_vector)
            if similarity > best_similarity:
                best_similarity = similarity
                best_hash = _decode(raw_key).split(":")[-1]

        if best_similarity < self.score_threshold or best_hash is None:
            return None

        response_key = f"{namespace}:resp:{best_hash}"
        cached_response = await self._redis.get(response_key)
        if cached_response is None:
            return None

        await self._update_metadata(namespace, best_hash)
        logger.info(
            "Semantic cache hit | namespace={} similarity={:.4f}",
            namespace,
            best_similarity,
        )
        return _decode(cached_response)

    async def update(
        self,
        messages: Sequence[dict[str, Any]],
        response: str,
        *,
        scope: str | None = None,
        expire: int | None = None,
    ) -> None:
        """
        Store a conversation turn inside the semantic cache.

        Args:
            messages: Conversation context ending with the triggering user message.
            response: Assistant response to cache.
            scope: Optional namespace to isolate caches (e.g. per user/session).
            expire: Custom expiry in seconds (defaults to settings.REL value).
        """
        ttl = self.ttl if expire is None else expire
        if ttl < 1:
            raise ValueError("expire must be positive")
        user_message = self._last_user_message(messages)
        if not user_message:
            return

        try:
            vector = await self._get_embedding(user_message)
        # An unavailable optional embedding cache must not fail the chat request.
        except Exception:  # noqa: BLE001
            logger.exception("Embedding service failed during semantic cache update")
            return

        namespace = self._namespace(scope)
        message_hash = self._message_hash(user_message)
        vector_key = f"{namespace}:vec:{message_hash}"
        response_key = f"{namespace}:resp:{message_hash}"
        metadata_key = f"{namespace}:meta:{message_hash}"

        await self._redis.set(vector_key, json.dumps(vector), ex=ttl)
        await self._redis.set(response_key, response, ex=ttl)
        metadata = {
            "created_at": _now_timestamp(),
            "last_access": _now_timestamp(),
            "access_count": 1,
        }
        await self._redis.set(metadata_key, json.dumps(metadata), ex=ttl)
        await self._ensure_capacity(namespace)

        logger.debug(
            "Semantic cache updated | namespace={} hash={}",
            namespace,
            message_hash,
        )

    async def clear_namespace(self, scope: str | None = None) -> None:
        """Remove every cached entry for a namespace."""
        namespace = self._namespace(scope)
        pattern = f"{_escape_redis_glob(namespace)}:*"
        keys: list[bytes] = []
        async for raw_key in self._redis.scan_iter(pattern):
            keys.append(raw_key)

        if keys:
            await self._redis.delete(*keys)
            logger.info(
                "Cleared semantic cache namespace | namespace={} count={}",
                namespace,
                len(keys),
            )

    async def _ensure_capacity(self, namespace: str) -> None:
        """Trim cache when exceeding the configured capacity."""
        pattern = f"{_escape_redis_glob(namespace)}:meta:*"
        metadata_entries: list[dict[str, Any]] = []

        async for raw_key in self._redis.scan_iter(pattern):
            payload = await self._redis.get(raw_key)
            if not payload:
                continue
            try:
                data = json.loads(_decode(payload))
                metadata_entries.append(
                    {
                        "key": _decode(raw_key),
                        "last_access": data["last_access"],
                    }
                )
            except (json.JSONDecodeError, KeyError, TypeError):
                logger.warning("Failed to decode metadata for key {}", _decode(raw_key))

        if len(metadata_entries) <= self.max_cache_size:
            return

        metadata_entries.sort(key=lambda item: item["last_access"])
        remove_count = len(metadata_entries) - self.max_cache_size
        for entry in metadata_entries[:remove_count]:
            hash_id = entry["key"].split(":")[-1]
            await self._remove_entry(namespace, hash_id)

    async def _remove_entry(self, namespace: str, hash_id: str) -> None:
        """Delete vector/response/metadata triple."""
        vector_key = f"{namespace}:vec:{hash_id}"
        response_key = f"{namespace}:resp:{hash_id}"
        metadata_key = f"{namespace}:meta:{hash_id}"
        await self._redis.delete(
            vector_key,
            response_key,
            metadata_key,
        )

    async def _update_metadata(self, namespace: str, hash_id: str) -> None:
        """Update access metadata for a given entry."""
        metadata_key = f"{namespace}:meta:{hash_id}"
        raw = await self._redis.get(metadata_key)

        metadata: dict[str, object] = {"access_count": 0}
        if raw:
            try:
                metadata.update(json.loads(_decode(raw)))
            except json.JSONDecodeError:
                logger.warning("Failed to decode existing metadata; resetting counters.")

        metadata["last_access"] = _now_timestamp()
        access_count = metadata["access_count"]
        if not isinstance(access_count, int):
            raise TypeError("Cache access_count must be an integer")
        metadata["access_count"] = access_count + 1
        await self._redis.set(
            metadata_key,
            json.dumps(metadata),
            ex=self.ttl,
        )

    async def _get_embedding(self, text: str) -> list[float]:
        """Fetch embedding vector from an OpenAI-compatible endpoint."""
        base_url = settings.OPENAI_API_BASE
        if base_url is None:
            base_url = "https://api.openai.com/v1"
        elif not base_url.strip():
            raise ValueError("Embedding base URL must not be empty")
        url = f"{base_url.rstrip('/')}/embeddings"
        payload = {"model": self.model_name, "input": text}
        headers = {"Content-Type": "application/json"}

        api_key = settings.OPENAI_API_KEY
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = _EmbeddingResponse.model_validate(response.json())
        return data.data[0].embedding

    def _namespace(self, scope: str | None) -> str:
        """Create namespace prefix for a scope."""
        return self.prefix if scope is None else f"{self.prefix}:{scope}"

    async def close(self) -> None:
        """Release a client created by this adapter; borrowed clients stay open."""
        if self._owns_redis:
            await self._redis.aclose()

    @staticmethod
    def _message_hash(message: str) -> str:
        """Generate deterministic hash for message text."""
        return hashlib.md5(message.encode("utf-8"), usedforsecurity=False).hexdigest()

    @staticmethod
    def _last_user_message(messages: Sequence[dict[str, Any]]) -> str | None:
        """Return last user-authored message content."""
        for message in reversed(messages):
            if message["role"] == "user":
                content = message["content"]
                # Multimodal user messages are not text-only cache keys.
                return content if isinstance(content, str) else None
        return None


class RedisConversationHistory:
    """Persist ordered conversation history using Redis lists."""

    def __init__(
        self,
        *,
        redis_client: Redis | None = None,
        redis_url: str | None = None,
        prefix: str = "history",
        ttl: int | None = None,
        max_messages: int | None = None,
    ) -> None:
        self._owns_redis = redis_client is None
        self._redis = (
            Redis.from_url(
                settings.REDIS_URL if redis_url is None else redis_url,
                decode_responses=False,
                socket_connect_timeout=5,
                socket_timeout=30,
            )
            if redis_client is None
            else redis_client
        )
        self.prefix = prefix
        self.ttl = ttl if ttl is not None else settings.CONVERSATION_HISTORY_TTL
        self.max_messages = (
            max_messages if max_messages is not None else settings.CONVERSATION_HISTORY_MAX_MESSAGES
        )
        if self.ttl < 1 or self.max_messages < 1:
            raise ValueError("ttl and max_messages must be positive")

    async def append(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Append a new message to the session history."""
        key = self._key(session_id)
        entry = {
            "role": role,
            "content": content,
            "metadata": metadata or {},
            "timestamp": _iso_now(),
        }
        # Redis 5 shares union annotations with sync commands; this client is async.
        await cast(Awaitable[int], self._redis.rpush(key, json.dumps(entry)))
        await cast(Awaitable[bool], self._redis.ltrim(key, -self.max_messages, -1))
        await self._redis.expire(key, self.ttl)

    async def get_recent(self, session_id: str, limit: int = 5) -> list[dict[str, Any]]:
        """Retrieve the latest `limit` messages for a session."""
        if limit < 0:
            raise ValueError("limit must be non-negative")
        if limit == 0:
            return []
        key = self._key(session_id)
        raw_items = await cast(Awaitable[list[bytes | str]], self._redis.lrange(key, -limit, -1))
        messages: list[dict[str, Any]] = []
        for raw_item in raw_items:
            messages.append(_HistoryEntry.model_validate_json(_decode(raw_item)).model_dump())
        return messages

    async def clear(self, session_id: str) -> None:
        """Remove history for a session."""
        await self._redis.delete(self._key(session_id))

    async def size(self, session_id: str) -> int:
        """Return the number of stored messages for a session."""
        return await cast(Awaitable[int], self._redis.llen(self._key(session_id)))

    def _key(self, session_id: str) -> str:
        return f"{self.prefix}:{session_id}"

    async def close(self) -> None:
        """Release a client created by this adapter; borrowed clients stay open."""
        if self._owns_redis:
            await self._redis.aclose()
