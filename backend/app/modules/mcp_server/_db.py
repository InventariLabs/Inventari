"""A database session for one MCP request or tool call.

The module serves an ASGI app rather than FastAPI routes, so the request-scoped
session FastAPI injects is not there. This drives the same generator Core's
`get_async_db` dependency drives: it commits once when the block returns and
rolls back when it raises, which is the transaction boundary every CoreAPI
call expects ("the caller commits, you flush" — backend/AGENTS.md §3).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.module_sdk import get_async_db


@asynccontextmanager
async def request_session() -> AsyncIterator[AsyncSession]:
    """Yield the request's async session, committing on a clean exit.

    The generator is closed by ``aclose`` in the ``finally``: on success the
    commit already ran, on an exception the session rolls back as it closes,
    and neither path leaves a connection checked out.
    """
    generator = get_async_db()
    session = await anext(generator)
    try:
        yield session
        try:
            await anext(generator)
        except StopAsyncIteration:
            pass
    finally:
        await generator.aclose()
