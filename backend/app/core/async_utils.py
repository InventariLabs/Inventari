import asyncio
import contextvars
from collections.abc import Callable
from typing import Any


async def run_sync_in_thread[T](fn: Callable[[], T]) -> T:
    """Run a sync callable in the default thread pool executor.

    Use for CPU-bound operations that would block the event loop
    (PDF generation, image manipulation, etc.). The caller's context
    variables travel with it, so a document rendered here still reads the
    request's language and organization country.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, contextvars.copy_context().run, fn)


async def maybe_await(value: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Invoke *value* as a coroutine function or fall back to a thread.

    Event handlers may be written sync (CPU-bound, blocking I/O) or
    async. This helper dispatches both without duplicating the
    ``iscoroutinefunction`` + ``run_in_executor`` dance at every call
    site.
    """
    if asyncio.iscoroutinefunction(value):
        return await value(*args, **kwargs)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: value(*args, **kwargs))


async def await_if_awaitable(value: Any) -> Any:
    """Await *value* if it is awaitable, otherwise return it unchanged.

    Dual-mode helper for services that accept either an ``AsyncSession``
    or a sync ``Session`` (the ``asyncio.run`` + sync-Session test path):
    ``db.execute(stmt)`` yields a coroutine on the former and a ready
    ``Result`` on the latter.

    Distinct from :func:`maybe_await`, which takes a **callable** and
    dispatches sync/async handlers. This one takes an already-produced
    **value** — different signature, different contract, don't merge them.
    """
    if hasattr(value, '__await__'):
        return await value
    return value
