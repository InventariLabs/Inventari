"""The stats SSE stream borrows its DB connection for the length of a tick.

A stream that keeps one session for as long as the dashboard stays open pins
a pooled connection and an open transaction per client: a few dozen tabs
exhaust the worker's pool and freeze every other request, and the long-lived
transaction's snapshot holds back VACUUM. Each tick therefore opens its own
short session and returns the connection before the stream sleeps — the
suspended-at-yield generator holds nothing.
"""

import asyncio
import json
import time
from collections.abc import AsyncGenerator, Iterator
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import app.database

# Importing the app registers every module's models in the SQLAlchemy mapper
# registry — a service-level query through an incomplete registry fails with
# "failed to locate a name" and the stream would dress that up as its error
# event instead of answering.
import app.main
from app.core.contracts import OverviewDTO, UserContextDTO
from app.models.user import User
from app.modules.stats import router as stats_router
from app.modules.stats.router import stream_overview

TICK_TIMEOUT_SECONDS = 15


async def _tick_overview(db: AsyncSession, organization_id: UUID) -> OverviewDTO:
    """The tick's payload: one round trip through the borrowed session.

    The real overview walks a dozen queries through the analytics read model
    and the shared Redis cache. What this test observes is the session
    lifecycle, and the full sweep made the tick itself the least
    deterministic part of the run: one flaky round trip under a loaded suite
    surfaces as the stream's own error event, red here — a fact about the
    machine's load average, not about who holds the connection.
    """
    await db.execute(text('SELECT 1'))
    return OverviewDTO(
        total_items=0,
        total_locations=0,
        expiring_soon=0,
        expired=0,
        low_stock=0,
        total_value=0.0,
    )


# Captured at import time, deliberately: _settle runs while the test has
# asyncio.sleep patched to a no-op, and reading the attribute at call time
# would read the very no-op the capture exists to avoid — an await that
# never suspends, so the settle loop busy-spins the CPU and the events the
# predicate waits for (pool checkins, the generator's own progress) never
# get scheduled. Under xdist load that spin is exactly what used to tip the
# two-second deadline into a flake.
_REAL_SLEEP = asyncio.sleep


async def _instant_noop(_seconds: float) -> None:
    return None


async def _settle(predicate: Any, what: str, limit: float = 2.0) -> None:
    """Wait for a condition instead of sampling it once.

    The predicate reads pool counters the event loop updates; asserting in
    the instant the generator resumes samples at an arbitrary point of that
    churn. The deadline is the detection window: a stream still holding its
    session two seconds after the yield never settles and fails loudly; a
    hold released sooner inside that window settles green — the blindness
    this wait consciously buys for determinism under xdist.
    """
    deadline = time.monotonic() + limit
    while not predicate():
        if time.monotonic() >= deadline:
            pytest.fail(f'{what} (waited {limit:.1f}s)')
        await _REAL_SLEEP(0.005)


@pytest.mark.integration
async def test_each_tick_opens_its_own_session_and_holds_nothing_at_yield(
    monkeypatch: pytest.MonkeyPatch,
    async_engine_fixture: AsyncEngine,
    test_user: User,
) -> None:
    """Two ticks: two short sessions, zero checked-out connections at yield.

    The suspension point after an event is where the stream used to hold the
    request session — there the pool checkout count must be back to zero, and
    the next tick must check out a session of its own rather than reuse one.

    Blindness, named: the settle deadline makes this test catch a hold LONGER
    than two seconds. A session handed back a moment after the yield (released
    by a background task) settles green — a conscious price for a deterministic
    wait under xdist, not a claim that any hold is impossible.
    """
    engine = create_async_engine(async_engine_fixture.url, pool_size=2, max_overflow=2)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    created: list[int] = []

    def counting_factory() -> AsyncSession:
        created.append(1)
        return factory()

    monkeypatch.setattr(app.database, 'AsyncSessionLocal', counting_factory)

    async def instant_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, 'sleep', instant_sleep)
    monkeypatch.setattr(stats_router, 'get_overview_stats', _tick_overview)

    live = 0

    def on_checkout(dbapi_conn: Any, record: Any, proxy: Any) -> None:
        nonlocal live
        live += 1

    def on_checkin(dbapi_conn: Any, record: Any) -> None:
        nonlocal live
        live -= 1

    event.listen(engine.sync_engine, 'checkout', on_checkout)
    event.listen(engine.sync_engine, 'checkin', on_checkin)

    context = UserContextDTO(
        id=test_user.id, organization_id=test_user.organization_id, role='admin'
    )
    response = await stream_overview(current_user=context)
    generator = cast(AsyncGenerator[dict[str, str]], response.body_iterator)

    try:
        first = await asyncio.wait_for(
            generator.__anext__(), timeout=TICK_TIMEOUT_SECONDS
        )
        # A tick answers from its own session and is done with it by the time
        # the event is handed over.
        assert first['event'] == 'overview', first
        # Reads the stub, not the service: total_items is _tick_overview's
        # constant, so this line asserts the tick's WIRE SHAPE — coverage of
        # /overview's numbers lives in other files.
        assert json.loads(first['data'])['total_items'] == 0
        assert len(created) == 1, created
        await _settle(
            lambda: live == 0, 'the first tick holds a connection at the yield'
        )

        second = await asyncio.wait_for(
            generator.__anext__(), timeout=TICK_TIMEOUT_SECONDS
        )
        # The next tick borrows a session again instead of leaning on one it
        # kept open across the sleep.
        assert second['event'] == 'overview', second
        assert len(created) == 2, created
        await _settle(
            lambda: live == 0, 'the second tick holds a connection at the yield'
        )
    finally:
        await generator.aclose()
        await engine.dispose()
        event.remove(engine.sync_engine, 'checkout', on_checkout)
        event.remove(engine.sync_engine, 'checkin', on_checkin)


@pytest.mark.unit
def test_the_stream_route_declares_no_session_dependency() -> None:
    """The stream endpoint takes no db: a request-scoped one is the bug.

    Only the endpoint's own dependency list counts — auth legitimately pulls
    a session behind ``get_current_user_context``, and that one is done
    before the path operation returns either way (same carve-out the scope
    gate makes).
    """
    from app.database import get_async_db
    from app.main import app

    def iter_api_routes(routes: list[Any]) -> Iterator[Any]:
        # Module routers mount nested, so descend like the scope gate does.
        for route in routes:
            if isinstance(route, APIRoute):
                yield route
            nested = getattr(route, 'routes', None)
            if nested is None:
                included = getattr(route, 'original_router', None)
                nested = getattr(included, 'routes', None)
            if nested:
                yield from iter_api_routes(list(nested))

    target = f'{stream_overview.__module__}.{stream_overview.__qualname__}'
    routes = [
        route
        for route in iter_api_routes(list(app.routes))
        if f'{route.endpoint.__module__}.{route.endpoint.__qualname__}' == target
    ]
    assert routes, 'stream route is not registered on the app'

    for route in routes:
        for dependant in route.dependant.dependencies:
            assert dependant.call is not get_async_db, (
                'the stats stream must borrow its session per tick, not declare one'
            )


@pytest.mark.integration
async def test_settle_yields_to_the_event_loop_while_sleep_is_patched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The settle loop must suspend, not spin.

    With asyncio.sleep patched to a no-op — exactly the stream test's
    arrangement — a settle that reads the attribute at call time awaits the
    no-op, never yields, and the task that would make the predicate true
    never runs: the loop burns CPU to its deadline and fails. Capturing the
    real sleep at import time is what makes this test pass; sabotage the
    capture back to a call-time read and this test fails at its deadline.
    """
    monkeypatch.setattr(asyncio, 'sleep', _instant_noop)

    done = False

    async def make_it_true() -> None:
        nonlocal done
        await asyncio.sleep(0)  # needs a real loop turn to run at all
        done = True

    task = asyncio.ensure_future(make_it_true())
    await _settle(lambda: done, 'the settle never yielded to the flip task', limit=2.0)
    await task
    assert done
