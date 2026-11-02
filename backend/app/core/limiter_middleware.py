"""Rate-limit middleware that sees through ``include_router``.

slowapi resolves the handler for an incoming request by walking ``app.routes``
and reading ``route.endpoint``. FastAPI does not splice included routes into
``app.routes``: every ``include_router()`` call stays a single
``_IncludedRouter`` node, which carries no ``endpoint``. The stock lookup
therefore finds nothing for any path under a router, ``_should_exempt`` reads
that as "unknown route, skip", and the limiter's default limits guard nothing —
only the explicit ``@limiter.limit`` decorators keep working.

``iter_route_contexts()`` is FastAPI's public flattening of those nodes, so the
lookup below resolves handlers the same way the router itself will. It costs a
regex match per candidate route on every request; the walk stops at the first
full match, which is also the route Starlette would pick.
"""

import asyncio
import time
from collections.abc import Callable, Iterable
from typing import Any

from fastapi.routing import iter_route_contexts
from slowapi import Limiter
from slowapi.middleware import SlowAPIMiddleware, _should_exempt, sync_check_limits
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.applications import Starlette
from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import BaseRoute
from starlette.routing import Match as RouteMatch
from starlette.types import Scope

from app.core import db_facade
from app.core.api_key_auth import load_issued_api_keys, resolve_api_key
from app.core.limiter import (
    refund_api_key_lookup,
    reserve_api_key_lookup,
    unverified_api_key,
)


def find_route_handler(
    routes: Iterable[BaseRoute], scope: Scope
) -> Callable[..., Any] | None:
    """Return the endpoint that will serve ``scope``, or None if none matches."""
    for route_context in iter_route_contexts(list(routes)):
        match, _ = route_context.matches(scope)
        if match == RouteMatch.FULL and route_context.endpoint is not None:
            return route_context.endpoint
    return None


# A sender out of lookups (``app.core.limiter``) may still carry an issued key
# — a client behind the same address as a forger — and counting that key
# under the address would refuse it before authentication could accept it.
# Such a key is told from a forged one by the list of the issued keys, loaded
# in one query. A key the list does not name waits for a list whose load began
# after the key arrived, so neither a load still in flight nor a key issued
# since the last one turns an issued key away; a load starts at most once a
# refresh interval, however many requests wait on it, so a forger past its
# budget buys a wait and a share of one query an interval. A key the list
# names is looked up once per load, every request presenting it meanwhile
# sharing that answer, so a key once real and since refused (expired, its
# module switched off) cannot become the unbounded work a forged one no
# longer can; a request that comes after the refusal waits for the next load
# and asks again, so a key valid again is not refused for what an older list
# said.
_ISSUED_LIST_REFRESH_SECONDS = 1.0


def _nothing_issued(raw_key: str) -> bool:
    return False


_issued_list: Callable[[str], bool] = _nothing_issued
# When the query behind ``_issued_list`` started: a key committed before that
# moment is on it.
_issued_list_loaded_at = float('-inf')
_issued_list_load: asyncio.Future[None] | None = None
_listed_lookups: dict[str, asyncio.Future[None]] = {}


async def _load_issued_list(session_factory: Callable[[], AsyncSession]) -> None:
    global _issued_list, _issued_list_loaded_at
    await asyncio.sleep(
        _issued_list_loaded_at + _ISSUED_LIST_REFRESH_SECONDS - time.monotonic()
    )
    started = time.monotonic()
    async with session_factory() as db:
        is_issued = await load_issued_api_keys(db)
    _issued_list, _issued_list_loaded_at = is_issued, started
    _listed_lookups.clear()


async def _issued_list_loaded_since(
    moment: float, session_factory: Callable[[], AsyncSession]
) -> None:
    """Wait until the issued-key list in use was loaded at or after ``moment``."""
    global _issued_list_load
    while _issued_list_loaded_at < moment:
        if _issued_list_load is None or _issued_list_load.done():
            _issued_list_load = asyncio.ensure_future(
                _load_issued_list(session_factory)
            )
        await asyncio.shield(_issued_list_load)


async def _look_up_listed(
    session_factory: Callable[[], AsyncSession], raw_key: str
) -> None:
    async with session_factory() as db:
        if await resolve_api_key(db, raw_key) is not None:
            # Accepted keys are asked about again once their verdict lapses.
            _listed_lookups.pop(raw_key, None)


async def _look_up_if_issued(
    session_factory: Callable[[], AsyncSession], raw_key: str
) -> None:
    """Look ``raw_key`` up if the issued-key list names it, sharing the lookup."""
    arrived = time.monotonic()
    while True:
        lookup = _listed_lookups.get(raw_key)
        if lookup is not None and lookup.done():
            # A refusal answers only the requests that waited on it; a later
            # one waits for a list loaded since it arrived, which forgets it.
            await _issued_list_loaded_since(arrived, session_factory)
            continue
        if lookup is None and _issued_list(raw_key):
            lookup = _listed_lookups[raw_key] = asyncio.ensure_future(
                _look_up_listed(session_factory, raw_key)
            )
        if lookup is not None:
            await asyncio.shield(lookup)
            return
        if _issued_list_loaded_at >= arrived:
            return
        await _issued_list_loaded_since(arrived, session_factory)


class RouterAwareSlowAPIMiddleware(SlowAPIMiddleware):
    """``SlowAPIMiddleware`` with a handler lookup that understands routers.

    The dispatch body mirrors the parent class; the handler lookup differs
    (the parent calls a module-level function, so it cannot be overridden),
    and an API key is checked before the limits are counted.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        app: Starlette = request.app
        limiter: Limiter = app.state.limiter

        if not limiter.enabled:
            return await call_next(request)

        handler = find_route_handler(app.routes, request.scope)
        if _should_exempt(limiter, handler):
            return await call_next(request)

        # The key function cannot ask the database, so a key-shaped credential
        # this process has no verdict on is checked here first: an issued key
        # counts under a bucket of its own from its first request, a made-up
        # one under whoever sent it (``app.core.limiter``). A sender who has
        # had its share of refused lookups has its keys looked up only when
        # the issued-key list names them, so forged keys cannot be turned into
        # database work and an issued one still gets its own count.
        raw_key = unverified_api_key(request)
        session_factory = db_facade.AsyncSessionLocal
        if raw_key is not None and session_factory is not None:
            if reserve_api_key_lookup(request):
                async with session_factory() as db:
                    if await resolve_api_key(db, raw_key) is not None:
                        refund_api_key_lookup(request)
            else:
                await _look_up_if_issued(session_factory, raw_key)

        error_response, should_inject_headers = sync_check_limits(
            limiter, request, handler, app
        )
        if error_response is not None:
            return error_response

        response = await call_next(request)
        if should_inject_headers:
            with_headers: Response = limiter._inject_headers(
                response, request.state.view_rate_limit
            )
            return with_headers
        return response
