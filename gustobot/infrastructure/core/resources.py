"""Bounded resource cleanup for asynchronous owners."""

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable, Callable, Coroutine, Optional, TypeVar

import anyio
from loguru import logger


T = TypeVar("T")
R = TypeVar("R")


@asynccontextmanager
async def close_on_exit(
    close: Callable[[], Awaitable[None]], *, timeout: float = 5
) -> AsyncIterator[None]:
    """Release an owner, keeping an active operation failure or cancellation visible."""
    if timeout <= 0:
        raise ValueError("cleanup timeout must be positive")
    failure: Optional[BaseException] = None
    try:
        yield
    except BaseException as exc:
        failure = exc
        raise
    finally:
        try:
            with anyio.fail_after(timeout, shield=True):
                await close()
        except Exception:
            if failure is None or isinstance(failure, GeneratorExit):
                raise
            logger.exception("Resource cleanup failed while preserving {}", type(failure).__name__)


@asynccontextmanager
async def acquire_in_thread(
    factory: Callable[[], T],
    close: Callable[[T], Awaitable[None]],
    *,
    timeout: float = 5,
) -> AsyncIterator[T]:
    """Own a thread-created resource, including acquisition and repeated cancellation.

    A running factory cannot be interrupted. Cancellation waits for its result
    and closes that result before propagating. The close callback must be async;
    adapt a blocking close with ``asyncio.to_thread``.
    """
    if timeout <= 0:
        raise ValueError("cleanup timeout must be positive")
    failure: Optional[BaseException] = None

    async def wait_for_owner(operation: Coroutine[Any, Any, R]) -> R:
        nonlocal failure
        outcome: asyncio.Future[R] = asyncio.get_running_loop().create_future()

        async def run() -> None:
            try:
                outcome.set_result(await operation)
            except BaseException as exc:
                # A Future retains the original CancelledError on Python 3.10;
                # a cancelled Task drops its message and identity on that runtime.
                outcome.set_exception(exc)

        owner = asyncio.create_task(run())
        try:
            await asyncio.shield(owner)
        except asyncio.CancelledError as exc:
            if failure is None:
                failure = exc
            with anyio.CancelScope(shield=True):
                while not owner.done():
                    try:
                        await asyncio.shield(owner)
                    except asyncio.CancelledError:
                        continue
        return outcome.result()

    try:
        resource = await wait_for_owner(asyncio.to_thread(factory))
    except BaseException as acquisition_failure:
        if failure is None or failure is acquisition_failure:
            raise
        raise failure from acquisition_failure

    cleanup_scope = close_on_exit(lambda: close(resource), timeout=timeout)
    await cleanup_scope.__aenter__()
    try:
        if failure is None:
            yield resource
    except BaseException as exc:
        failure = exc

    # Run the existing exit policy under its own task so native task.cancel()
    # cannot interrupt its async close while this owner waits for completion.
    try:
        await wait_for_owner(
            cleanup_scope.__aexit__(
                type(failure) if failure is not None else None,
                failure,
                failure.__traceback__ if failure is not None else None,
            )
        )
    except Exception:
        if failure is None or isinstance(failure, GeneratorExit):
            raise
        logger.exception("Resource cleanup failed while preserving {}", type(failure).__name__)
    if failure is not None:
        raise failure
