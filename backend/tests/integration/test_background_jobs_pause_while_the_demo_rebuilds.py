"""A demo rebuild drops the schema under a running backend; its jobs wait."""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.database
from app.config import settings
from app.core.scheduler import TaskScheduler
from app.core.schema_rebuild import MIGRATION_LOCK_KEY, schema_held_steady

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def rebuild(
    real_async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[asyncio.Event]:
    """The schema is being rebuilt from the moment the event is set to the moment it is cleared."""
    engine = real_async_db_session.bind
    monkeypatch.setattr(
        app.database,
        'AsyncSessionLocal',
        async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
    )
    changed = asyncio.Event()
    async with engine.connect() as holder:
        holder = await holder.execution_options(isolation_level='AUTOCOMMIT')

        async def hold() -> None:
            await holder.execute(
                text('SELECT pg_advisory_lock(:key)'), {'key': MIGRATION_LOCK_KEY}
            )

        async def release() -> None:
            await holder.execute(
                text('SELECT pg_advisory_unlock(:key)'), {'key': MIGRATION_LOCK_KEY}
            )

        changed.hold = hold  # type: ignore[attr-defined]
        changed.release = release  # type: ignore[attr-defined]
        yield changed
        await release()


async def test_a_job_is_refused_while_the_rebuild_holds_the_lock(rebuild) -> None:
    async with schema_held_steady() as may_run:
        assert may_run is True

    await rebuild.hold()
    async with schema_held_steady() as may_run:
        assert may_run is False

    await rebuild.release()
    async with schema_held_steady() as may_run:
        assert may_run is True


async def test_a_rebuild_waits_for_a_job_already_running(
    rebuild, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The probe passing is not enough: the claim lasts as long as the job does."""
    monkeypatch.setattr(settings, 'INVENTARI_DEMO', True)
    engine = app.database.AsyncSessionLocal.kw['bind']
    started, finish = asyncio.Event(), asyncio.Event()

    async def handler() -> None:
        started.set()
        await finish.wait()

    scheduler = TaskScheduler()
    scheduler.register(
        name='probe',
        interval=timedelta(hours=1),
        handler=handler,
        module_name='core',
    )
    task = scheduler._tasks['core.probe']
    job = asyncio.create_task(scheduler._execute_task(task))
    try:
        await asyncio.wait_for(started.wait(), 5)
        async with engine.connect() as rebuilder:
            rebuilder = await rebuilder.execution_options(isolation_level='AUTOCOMMIT')
            sql = text('SELECT pg_try_advisory_lock(:key)')
            got = await rebuilder.scalar(sql, {'key': MIGRATION_LOCK_KEY})
            assert got is False, 'the rebuild took the lock under a running job'

            finish.set()
            await asyncio.wait_for(job, 5)
            got = await rebuilder.scalar(sql, {'key': MIGRATION_LOCK_KEY})
            assert got is True, 'the job kept the lock after it finished'
            await rebuilder.execute(
                text('SELECT pg_advisory_unlock(:key)'), {'key': MIGRATION_LOCK_KEY}
            )
    finally:
        finish.set()
        await asyncio.gather(job, return_exceptions=True)


async def test_a_demo_job_skips_its_ticks_during_the_rebuild_and_resumes_after(
    rebuild, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, 'INVENTARI_DEMO', True)
    ticks: list[int] = []
    scheduler = TaskScheduler()
    scheduler.register(
        name='probe',
        interval=timedelta(seconds=0.05),
        handler=lambda: ticks.append(1),
        module_name='core',
    )

    await rebuild.hold()
    scheduler.start_all()
    try:
        await asyncio.sleep(0.5)
        assert ticks == [], 'a job ran while the schema was being rebuilt'

        await rebuild.release()
        for _ in range(40):
            if ticks:
                break
            await asyncio.sleep(0.05)
        assert ticks, 'the job did not resume after the rebuild'
    finally:
        await scheduler.stop_all_async()


async def test_an_install_that_is_not_a_demo_never_asks(
    rebuild, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The probe is a demo's concern; other installs keep their ticks as they were."""
    monkeypatch.setattr(settings, 'INVENTARI_DEMO', False)
    ticks: list[int] = []
    scheduler = TaskScheduler()
    scheduler.register(
        name='probe',
        interval=timedelta(seconds=0.05),
        handler=lambda: ticks.append(1),
        module_name='core',
    )

    await rebuild.hold()
    scheduler.start_all()
    try:
        for _ in range(40):
            if ticks:
                break
            await asyncio.sleep(0.05)
        assert ticks, 'a non-demo job was held back'
    finally:
        await rebuild.release()
        await scheduler.stop_all_async()
