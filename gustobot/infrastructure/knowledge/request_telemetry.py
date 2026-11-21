"""Request-local provider counters shared by copied async and worker contexts.

Snapshots contain counts only. Elapsed time is summed across logical calls; it
is not a request wall-clock measurement or an estimate of provider latency.
"""

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
from math import isfinite
from threading import Lock, RLock
from time import perf_counter
from typing import Any, Literal
from uuid import UUID

import httpx
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

ProviderPurpose = Literal["document", "candidate", "build", "analysis", "generation", "rerank"]
ModelPhase = Literal["analysis", "generation"]
CounterSnapshot = dict[str, int | float]
TraceSnapshot = dict[str, CounterSnapshot]

_PURPOSES = {"document", "candidate", "build", "analysis", "generation", "rerank"}
_COUNTERS = {
    "logical_calls",
    "provider_batches",
    "http_attempts",
    "texts",
    "input_characters",
    "elapsed_seconds",
    "input_tokens",
    "output_tokens",
    "cache_hits",
}
_EMPTY: CounterSnapshot = {
    "logical_calls": 0,
    "provider_batches": 0,
    "http_attempts": 0,
    "texts": 0,
    "input_characters": 0,
    "elapsed_seconds": 0.0,
}


class RequestTrace:
    """Thread-safe counters and query-vector cache scoped to one request."""

    def __init__(self) -> None:
        self._values: TraceSnapshot = {}
        self._lock = Lock()
        self._vector_lock = RLock()
        self._query_vectors: dict[tuple[str, str], list[float]] = {}

    def _record(self, purpose: ProviderPurpose, counters: Mapping[str, int | float]) -> None:
        if purpose not in _PURPOSES:
            raise ValueError("Unknown provider telemetry purpose")
        for name, value in counters.items():
            if name not in _COUNTERS:
                raise ValueError("Unknown provider telemetry counter")
            if name == "elapsed_seconds":
                valid = type(value) in (int, float) and isfinite(value) and value >= 0
            else:
                valid = type(value) is int and value >= 0
            if not valid:
                raise ValueError(
                    "Provider counters must be finite nonnegative counts or elapsed time"
                )
        with self._lock:
            current = self._values.setdefault(purpose, dict(_EMPTY))
            for name, value in counters.items():
                current[name] = current.get(name, 0) + value

    def snapshot(self) -> TraceSnapshot:
        """Return a detached counter snapshot without exposing mutable internals."""
        with self._lock:
            return {purpose: dict(counters) for purpose, counters in self._values.items()}


_TRACE: ContextVar[RequestTrace | None] = ContextVar("provider_request_trace", default=None)
_PHASE: ContextVar[ModelPhase | None] = ContextVar("provider_request_phase", default=None)


@contextmanager
def capture_request_trace(trace: RequestTrace | None = None) -> Iterator[RequestTrace]:
    """Bind a new or existing trace and restore the caller's context on every exit.

    Copied worker contexts retain their original trace after a caller cancels;
    any late event remains isolated from subsequently captured requests.
    """
    selected = RequestTrace() if trace is None else trace
    trace_token = _TRACE.set(selected)
    phase_token = _PHASE.set(None)
    try:
        yield selected
    finally:
        _PHASE.reset(phase_token)
        _TRACE.reset(trace_token)


def record_provider_event(purpose: ProviderPurpose, **counters: float) -> None:
    """Add provider counters to the trace active in the current context."""
    trace = _TRACE.get()
    if trace is not None:
        trace._record(purpose, counters)


def request_query_vector(
    space_fingerprint: str, text: str, purpose: ProviderPurpose, compute: Callable[[], list[float]]
) -> list[float]:
    """Reuse one request-local embedding for equal text and space identities."""
    trace = _TRACE.get()
    if trace is None:
        return compute()
    key = space_fingerprint, sha256(text.encode()).hexdigest()
    with trace._vector_lock:
        if key in trace._query_vectors:
            trace._record(purpose, {"cache_hits": 1})
            return list(trace._query_vectors[key])
        vector = compute()
        if len(trace._query_vectors) < 16:
            trace._query_vectors[key] = list(vector)
        return vector


@contextmanager
def provider_phase(phase: ModelPhase, *, count_call: bool = True) -> Iterator[None]:
    """Label one model invocation, or one resumed stream iteration.

    Streaming consumers record the logical invocation once and set count_call
    false around each __anext__; they must yield outside this context manager.
    """
    if phase not in {"analysis", "generation"}:
        raise ValueError("Unknown model telemetry phase")
    token = _PHASE.set(phase)
    trace = _TRACE.get()
    started = perf_counter()
    if count_call and trace is not None:
        trace._record(phase, {"logical_calls": 1})
    try:
        yield
    finally:
        if trace is not None:
            trace._record(phase, {"elapsed_seconds": perf_counter() - started})
        _PHASE.reset(token)


def record_sync_http_request(request: httpx.Request) -> None:
    """HTTPX request hook for the model client's actual outgoing attempts."""
    phase = _PHASE.get()
    if phase is not None:
        record_provider_event(phase, provider_batches=1, http_attempts=1)


async def record_async_http_request(request: httpx.Request) -> None:
    """Async HTTPX hook that records the same attempt counters as the sync hook."""
    record_sync_http_request(request)


def _token_counts(response: LLMResult) -> dict[str, int]:
    """Read valid provider token totals once across supported response shapes."""
    raw = None if response.llm_output is None else response.llm_output.get("token_usage")
    if isinstance(raw, Mapping):
        counts = {}
        for target, source in (
            ("input_tokens", "prompt_tokens"),
            ("output_tokens", "completion_tokens"),
        ):
            value = raw[source] if source in raw else raw.get(target)
            if type(value) is int and value >= 0:
                counts[target] = value
        return counts
    if not response.generations or any(not row for row in response.generations):
        return {}
    usages = []
    for row in response.generations:
        first = row[0]
        if not isinstance(first, ChatGeneration) or not isinstance(first.message, AIMessage):
            return {}
        usages.append(first.message.usage_metadata)
    counts = {}
    for name in ("input_tokens", "output_tokens"):
        values = [usage.get(name) if usage is not None else None for usage in usages]
        if all(type(value) is int and value >= 0 for value in values):
            counts[name] = sum(value for value in values if isinstance(value, int))
    return counts


class ProviderUsageCallback(BaseCallbackHandler):
    """Use reported usage once; OpenAI repeats totals on each output choice."""

    run_inline = True

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        """Record provider-reported token totals once for the active model phase."""
        phase = _PHASE.get()
        if phase is not None:
            counts = _token_counts(response)
            if counts:
                record_provider_event(phase, **counts)
