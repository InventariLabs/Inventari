"""Every route must take its async session with ``scope='function'``.

FastAPI defaults a dependency with ``yield`` to ``scope='request'``, which
unwinds after the response has been written to the socket. With the default,
``get_async_db``'s ``COMMIT`` runs once the client already holds the response:
a caller that immediately uses an id it was just handed (create a shopping
list, then add an item to it) queries a snapshot that predates the INSERT and
gets a 404 for a row that does exist a moment later. It only shows up when a
commit is slower than the caller's next request — busy server, durability on —
which is what made it read as random e2e flakiness.

``scope='function'`` ends the dependency before the response is sent, so a 2xx
means the write is committed. This test fails if a new endpoint forgets it.
"""

from collections.abc import Iterator

import pytest
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from starlette.routing import BaseRoute

from app.database import get_async_db
from app.main import app

# No endpoint may keep the request scope. The stats SSE stream used to be
# the one exception — it now borrows a fresh AsyncSessionLocal per tick
# instead of declaring a session, so nothing legitimately outlives the path
# operation and the gate stays armed for whoever re-adds one.
REQUEST_SCOPED_ENDPOINTS: set[str] = set()


def _api_routes(routes: list[BaseRoute]) -> Iterator[APIRoute]:
    """Yield every APIRoute, descending through include_router containers."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        nested = getattr(route, 'routes', None)
        if nested is None:
            included = getattr(route, 'original_router', None)
            nested = getattr(included, 'routes', None)
        if nested:
            yield from _api_routes(list(nested))


def _session_dependants(dependant: Dependant) -> Iterator[Dependant]:
    for sub in dependant.dependencies:
        if sub.call is get_async_db:
            yield sub
        yield from _session_dependants(sub)


@pytest.mark.unit
def test_async_db_dependency_is_function_scoped() -> None:
    offenders: list[str] = []
    checked = 0

    for route in _api_routes(list(app.routes)):
        endpoint = f'{route.endpoint.__module__}.{route.endpoint.__qualname__}'
        # Only the session the endpoint itself asks for may be request-scoped;
        # the one auth pulls in behind get_current_user_context is done with
        # before the path operation returns either way.
        direct = {
            id(dep) for dep in route.dependant.dependencies if dep.call is get_async_db
        }
        for dep in _session_dependants(route.dependant):
            checked += 1
            expected = (
                'request'
                if id(dep) in direct and endpoint in REQUEST_SCOPED_ENDPOINTS
                else 'function'
            )
            if dep.scope != expected:
                offenders.append(
                    f'{endpoint} has scope={dep.scope!r}, want {expected!r}'
                )

    assert checked, 'no route injects get_async_db — the walk is broken, not the app'
    assert not offenders, (
        'these endpoints inject get_async_db with the wrong scope — use '
        "Depends(get_async_db, scope='function') so the session commits before "
        f'the response is sent: {sorted(set(offenders))}'
    )
