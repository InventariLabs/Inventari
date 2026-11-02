"""A deadlocked request is retried, not handed to the client as a 500.

The lock discipline (ADR-020 and its siblings) keeps concurrent writes
from colliding, but two paths that lock the same rows in opposite orders
can still meet in the middle: Postgres kills one transaction with SQLSTATE
40P01 and, before the retry guard existed, that answer went straight to
the user. The tests below produce a real deadlock with two live sessions
on the real database — advisory locks, taken in opposite orders, one on
each side — and read what the request actually got.

The steps are coordinated on events, not sleeps: the endpoint says it
holds the first lock, the antagonist says it holds the second, and only
then does each side walk into the other. Who the database picks as the
victim is not left to chance either — the probe session sets a
``deadlock_timeout`` of milliseconds, so its detector fires long before
the antagonist's (set to a minute) and the probe is the
transaction that dies.

Postgres runs that detector once per wait, when the timeout elapses. So the
probe walks into its second lock only after the database shows the
antagonist already waiting for the first: were the probe first, a machine
slow enough to keep the antagonist's request away for those milliseconds
would find no cycle yet, and the deadlock would wait for the antagonist's
minute instead — past the request's timeout, which is how a two-CPU CI
runner failed this file.

The third test is the safety rule the whole mechanism stands on: a
request that has already published an event (a bare ``emit``, before the
commit) is not repeated, because the second attempt would announce the
same thing twice. The refusal is the mechanism working, not a gap in it.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core import db_retry
from app.core._event_bus import EventBus
from app.core.contracts.events import EventPayload
from app.database import get_async_db

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# Two advisory lock ids only these tests use. Transaction-scoped, so
# commit or rollback releases them without leaving anything behind.
_LOCK_A = 910_001
_LOCK_B = 910_002


def _async_test_url() -> str:
    return settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)


class _Choreography:
    """The deadlock, step by step, on events rather than sleeps."""

    def __init__(self) -> None:
        self.probe_holds_first = asyncio.Event()
        self.antagonist_holds_second = asyncio.Event()
        self.probe_attempts = 0

    async def antagonist(self, factory) -> None:
        """Hold the second lock, then come waiting for the first.

        Its wait ends the moment the probe's transaction is killed (the
        deadlock detector cancels the detecting backend, which releases its
        locks), and it rolls straight back so the retried attempt finds
        both locks free.
        """
        async with factory() as session:
            # Far above the probe's 20ms, so the probe stays the victim even
            # when a loaded machine delays it by more than the server default.
            await session.execute(text("SET LOCAL deadlock_timeout = '60s'"))
            await session.execute(text(f'SELECT pg_advisory_xact_lock({_LOCK_B})'))
            self.antagonist_holds_second.set()
            await self.probe_holds_first.wait()
            await session.execute(text(f'SELECT pg_advisory_xact_lock({_LOCK_A})'))
            await session.rollback()


@pytest.fixture
async def engine(real_async_db_session):
    # ``real_async_db_session`` provisions this worker's run-scoped database
    # (and keeps its truncate/seed discipline); the engine above connects to
    # the same URL it was built from.
    engine = create_async_engine(_async_test_url(), poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _someone_waits_for(db: AsyncSession, lock: int) -> None:
    """Return once another session is queued on the advisory lock ``lock``."""
    while not (
        await db.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory'"
                ' AND objid = :lock AND NOT granted AND database = ('
                'SELECT oid FROM pg_database WHERE datname = current_database()))'
            ),
            {'lock': lock},
        )
    ).scalar():
        await asyncio.sleep(0.01)


def _build_app(
    choreography: _Choreography,
    *,
    install_retry: bool,
    emit_before_deadlock: bool = False,
) -> FastAPI:
    """The probe app: one route that walks into a deadlock on the request session.

    The route mirrors how a real endpoint is wired — ``get_async_db``, the
    dependency that commits when the endpoint returns — and the retry is
    the same middleware ``app.main`` registers, so the tests measure the
    production mechanism, not a copy of it.
    """

    app = FastAPI()

    @app.post('/probe')
    async def probe(db: AsyncSession = Depends(get_async_db)) -> dict:
        choreography.probe_attempts += 1
        # The probe must be the session that detects the deadlock: Postgres
        # reports it from whichever waiter's deadlock_timeout elapses first,
        # so the probe waits on a timeout of milliseconds while the
        # antagonist's is a minute.
        await db.execute(text("SET LOCAL deadlock_timeout = '20ms'"))
        await db.execute(text(f'SELECT pg_advisory_xact_lock({_LOCK_A})'))
        choreography.probe_holds_first.set()
        await asyncio.wait_for(choreography.antagonist_holds_second.wait(), 10)
        if choreography.probe_attempts == 1:
            # A retried attempt finds the antagonist gone, nobody waiting.
            await asyncio.wait_for(_someone_waits_for(db, _LOCK_A), 10)
        if emit_before_deadlock:
            await EventBus().emit('db_retry.probe', EventPayload())
        await db.execute(text(f'SELECT pg_advisory_xact_lock({_LOCK_B})'))
        return {'ok': True, 'attempt': choreography.probe_attempts}

    if install_retry:
        app.add_middleware(db_retry.TransactionRetryMiddleware)
    return app


def _override_dependency(app: FastAPI, factory) -> None:
    async def override_get_async_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_async_db] = override_get_async_db


async def _request_against(
    choreography: _Choreography, factory, *, install_retry: bool, emit: bool = False
):
    app = _build_app(
        choreography, install_retry=install_retry, emit_before_deadlock=emit
    )
    _override_dependency(app, factory)
    opponent = asyncio.create_task(choreography.antagonist(factory))
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False)
        ) as ac:
            return await asyncio.wait_for(ac.post('http://t/probe'), timeout=20)
    finally:
        await asyncio.wait_for(opponent, timeout=20)


async def test_a_deadlock_without_the_guard_is_a_500(engine, session_factory):
    """What the behaviour is without the retry: the error reaches the client.

    This is also the test that fails when the guard is taken out — the
    failure mode the whole task exists for, pinned where it can be seen.
    """
    choreography = _Choreography()
    response = await _request_against(
        choreography, session_factory, install_retry=False
    )

    assert response.status_code == 500
    assert choreography.probe_attempts == 1


async def test_a_deadlocked_request_is_retried_and_succeeds(engine, session_factory):
    """The same deadlock, with the guard installed: a second attempt, a 200."""
    choreography = _Choreography()
    response = await _request_against(choreography, session_factory, install_retry=True)

    assert response.status_code == 200
    assert response.json()['attempt'] == 2
    assert response.headers[db_retry.RETRY_ATTEMPTS_HEADER] == '2'
    assert choreography.probe_attempts == 2


async def test_a_request_that_emitted_before_the_deadlock_is_not_retried(
    engine, session_factory
):
    """One bare ``emit`` before the failure, and the retry is refused."""
    choreography = _Choreography()
    response = await _request_against(
        choreography, session_factory, install_retry=True, emit=True
    )

    assert response.status_code == 500
    assert choreography.probe_attempts == 1
    assert db_retry.RETRY_ATTEMPTS_HEADER not in response.headers
