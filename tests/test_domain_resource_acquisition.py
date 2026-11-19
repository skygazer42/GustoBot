"""Thread-created resources keep an owner through native asyncio cancellation."""

import asyncio
import importlib
import threading
from contextvars import ContextVar
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def _acquire():
    module = importlib.import_module("gustobot.infrastructure.core.resources")
    return module.acquire_in_thread


@pytest.mark.asyncio
async def test_factory_runs_off_loop_and_close_owns_the_resource_until_exit():
    acquire = _acquire()
    loop_thread = threading.get_ident()
    trace = ContextVar("resource_trace", default="missing")
    trace.set("request")
    resource = SimpleNamespace(closed=False)
    factory_threads = []

    def factory():
        factory_threads.append(threading.get_ident())
        assert trace.get() == "request"
        return resource

    async def close(value):
        assert value is resource
        assert threading.get_ident() == loop_thread
        await asyncio.sleep(0)
        value.closed = True

    async with acquire(factory, close) as acquired:
        assert acquired is resource
        assert not resource.closed
    assert resource.closed
    assert len(factory_threads) == 1
    assert factory_threads[0] != loop_thread


@pytest.mark.asyncio
async def test_factory_failure_propagates_without_closing_an_unacquired_resource():
    acquire = _acquire()
    failure = ValueError("constructor failed")
    close = AsyncMock()

    def factory():
        raise failure

    with pytest.raises(ValueError) as raised:
        async with acquire(factory, close):
            pytest.fail("failed acquisition entered the body")
    assert raised.value is failure
    close.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("close_fails", [False, True])
async def test_body_failure_is_preserved_after_resource_cleanup(close_fails):
    acquire = _acquire()
    resource = object()
    failure = ValueError("operation failed")
    close = AsyncMock(side_effect=RuntimeError("close failed") if close_fails else None)

    with pytest.raises(ValueError) as raised:
        async with acquire(lambda: resource, close):
            raise failure
    assert raised.value is failure
    close.assert_awaited_once_with(resource)


@pytest.mark.asyncio
async def test_cleanup_failure_is_visible_after_a_successful_body():
    acquire = _acquire()
    resource = object()
    failure = RuntimeError("close failed")
    close = AsyncMock(side_effect=failure)

    with pytest.raises(RuntimeError) as raised:
        async with acquire(lambda: resource, close):
            pass
    assert raised.value is failure
    close.assert_awaited_once_with(resource)


@pytest.mark.asyncio
@pytest.mark.parametrize("close_fails", [False, True])
async def test_cancelled_acquisition_waits_for_factory_and_close_despite_repeated_cancel(
    close_fails,
):
    acquire = _acquire()
    loop = asyncio.get_running_loop()
    factory_started = asyncio.Event()
    factory_release = threading.Event()
    close_started = asyncio.Event()
    close_release = asyncio.Event()
    resource = object()
    closed = []
    entered = []
    cancellations = []

    def factory():
        loop.call_soon_threadsafe(factory_started.set)
        if not factory_release.wait(2):
            raise TimeoutError("test did not release factory")
        return resource

    async def close(value):
        closed.append(value)
        close_started.set()
        await close_release.wait()
        if close_fails:
            raise RuntimeError("close failed")

    async def use():
        try:
            async with acquire(factory, close):
                entered.append(True)
        except asyncio.CancelledError as exc:
            cancellations.append(exc)
            raise

    task = asyncio.create_task(use())
    try:
        await asyncio.wait_for(factory_started.wait(), 1)
        task.cancel("first cancellation")
        await asyncio.sleep(0)
        assert not task.done()
        task.cancel("second cancellation")
        await asyncio.sleep(0)
        assert not task.done()
        factory_release.set()
        await asyncio.wait_for(close_started.wait(), 1)
        task.cancel("third cancellation")
        await asyncio.sleep(0)
        assert not task.done()
        close_release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert cancellations[0].args == ("first cancellation",)
        assert entered == []
        assert closed == [resource]
    finally:
        factory_release.set()
        close_release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("close_fails", [False, True])
async def test_native_body_cancellation_keeps_cleanup_owned_through_another_cancel(close_fails):
    acquire = _acquire()
    body_started = asyncio.Event()
    close_started = asyncio.Event()
    close_release = asyncio.Event()
    resource = object()
    closed = []
    cancellations = []

    async def close(value):
        closed.append(value)
        close_started.set()
        await close_release.wait()
        if close_fails:
            raise RuntimeError("close failed")

    async def use():
        try:
            async with acquire(lambda: resource, close):
                body_started.set()
                await asyncio.Event().wait()
        except asyncio.CancelledError as exc:
            cancellations.append(exc)
            raise

    task = asyncio.create_task(use())
    try:
        await asyncio.wait_for(body_started.wait(), 1)
        task.cancel("operation cancelled")
        await asyncio.wait_for(close_started.wait(), 1)
        task.cancel("cleanup cancelled again")
        await asyncio.sleep(0)
        assert not task.done()
        close_release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert cancellations[0].args == ("operation cancelled",)
        assert closed == [resource]
    finally:
        close_release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancellation_during_normal_cleanup_is_delayed_until_close_finishes():
    acquire = _acquire()
    close_started = asyncio.Event()
    close_release = asyncio.Event()
    closed = []
    cancellations = []

    async def close(resource):
        close_started.set()
        await close_release.wait()
        closed.append(resource)

    resource = object()

    async def use():
        try:
            async with acquire(lambda: resource, close):
                pass
        except asyncio.CancelledError as exc:
            cancellations.append(exc)
            raise

    task = asyncio.create_task(use())
    try:
        await asyncio.wait_for(close_started.wait(), 1)
        task.cancel("cancel during close")
        await asyncio.sleep(0)
        assert not task.done()
        task.cancel("cancel close again")
        await asyncio.sleep(0)
        close_release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert cancellations[0].args == ("cancel during close",)
        assert closed == [resource]
    finally:
        close_release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_cleanup_own_cancellation_remains_visible_like_close_on_exit():
    acquire = _acquire()
    cancellation = asyncio.CancelledError("close itself cancelled")
    close = AsyncMock(side_effect=cancellation)
    with pytest.raises(asyncio.CancelledError) as raised:
        async with acquire(object, close):
            raise ValueError("body failed")
    assert raised.value is cancellation


@pytest.mark.asyncio
async def test_factory_failure_after_cancellation_keeps_cancellation_and_chains_failure():
    acquire = _acquire()
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = threading.Event()
    failure = ValueError("factory failed after cancellation")
    close = AsyncMock()
    cancellations = []

    def factory():
        loop.call_soon_threadsafe(started.set)
        if not release.wait(2):
            raise TimeoutError("test did not release factory")
        raise failure

    async def use():
        try:
            async with acquire(factory, close):
                pytest.fail("failed acquisition entered the body")
        except asyncio.CancelledError as exc:
            cancellations.append(exc)
            raise

    task = asyncio.create_task(use())
    try:
        await asyncio.wait_for(started.wait(), 1)
        task.cancel("request cancelled")
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert cancellations[0].args == ("request cancelled",)
        assert cancellations[0].__cause__ is failure
        close.assert_not_awaited()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("body_fails", [False, True])
async def test_cooperative_cleanup_timeout_uses_existing_failure_priority(body_fails):
    acquire = _acquire()
    body_failure = ValueError("body failed")

    async def close(resource):
        await asyncio.Event().wait()

    with pytest.raises(ValueError if body_fails else TimeoutError) as raised:
        async with acquire(object, close, timeout=0.01):
            if body_fails:
                raise body_failure
    if body_fails:
        assert raised.value is body_failure


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [0, -1])
async def test_invalid_cleanup_timeout_does_not_acquire_a_resource(timeout):
    acquire = _acquire()
    created = []
    close = AsyncMock()

    def factory():
        created.append(True)
        return object()

    with pytest.raises(ValueError, match="timeout"):
        async with acquire(factory, close, timeout=timeout):
            pass
    assert created == []
    close.assert_not_awaited()
