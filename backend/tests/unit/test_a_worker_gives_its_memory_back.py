"""A worker that grew replaces itself; one that did not stays.

Python keeps the heap of a large answer, so a worker's memory only comes back
when the worker is replaced. The recycler decides when, from the worker's own
start-up size and its traffic, and nothing is decided under a request.
"""

from app.core.worker_recycle import WorkerRecycler


class _Machine:
    def __init__(self) -> None:
        self.rss = 200.0
        self.now = 0.0

    def recycler(self, *, max_growth_mb=200.0, idle_seconds=120.0) -> WorkerRecycler:
        recycler = WorkerRecycler(
            max_growth_mb=max_growth_mb,
            idle_seconds=idle_seconds,
            rss_mb=lambda: self.rss,
            clock=lambda: self.now,
        )
        assert recycler.reason_to_replace() is None  # takes the baseline
        return recycler


def test_a_worker_near_its_start_up_size_stays() -> None:
    machine = _Machine()
    recycler = machine.recycler()
    machine.rss = 230.0
    machine.now = 3600.0
    assert recycler.reason_to_replace() is None


def test_a_worker_that_grew_past_the_cap_is_replaced_after_its_request() -> None:
    machine = _Machine()
    recycler = machine.recycler()
    recycler.request_started()
    machine.rss = 700.0
    assert recycler.reason_to_replace() is None, 'never under a request'
    recycler.request_finished()
    assert recycler.reason_to_replace() is not None


def test_an_idle_worker_a_quarter_over_its_start_up_size_is_replaced() -> None:
    machine = _Machine()
    recycler = machine.recycler()
    machine.rss = 280.0
    machine.now = 60.0
    assert recycler.reason_to_replace() is None, 'not idle for long enough yet'
    machine.now = 130.0
    assert recycler.reason_to_replace() is not None


def test_a_small_growth_is_not_worth_a_replacement() -> None:
    machine = _Machine()
    machine.rss = 40.0
    recycler = machine.recycler()
    machine.rss = 60.0  # +50 %, but 20 MB
    machine.now = 3600.0
    assert recycler.reason_to_replace() is None


def test_the_idle_rule_can_be_turned_off() -> None:
    machine = _Machine()
    recycler = machine.recycler(idle_seconds=0)
    machine.rss = 260.0  # +30 %, under the growth cap
    machine.now = 3600.0
    assert recycler.reason_to_replace() is None


async def test_a_request_in_flight_keeps_the_worker_where_it_is(
    monkeypatch,
) -> None:
    """The middleware counts a request from its first byte to its last."""
    from app.core import worker_recycle

    machine = _Machine()
    recycler = machine.recycler()
    monkeypatch.setattr(worker_recycle, 'active', recycler)
    machine.rss = 900.0
    seen: list[str | None] = []

    async def app(scope, receive, send):
        seen.append(recycler.reason_to_replace())

    await worker_recycle.CountRequests(app)({'type': 'http'}, None, None)

    assert seen == [None], 'never replaced under a request'
    assert recycler.reason_to_replace() is not None, 'and replaced after it'


async def test_a_process_not_told_to_watch_itself_does_not(monkeypatch) -> None:
    """A development server or a test run is no worker an arbiter replaces."""
    from app.core import worker_recycle

    monkeypatch.delenv('BACKEND_WORKER_MAX_GROWTH_MB', raising=False)

    assert worker_recycle.start_watch() is None


async def test_a_process_told_to_watch_itself_starts_the_watch(monkeypatch) -> None:
    from app.core import worker_recycle

    monkeypatch.setenv('BACKEND_WORKER_MAX_GROWTH_MB', '200')
    monkeypatch.setattr(worker_recycle, 'active', None)

    watch = worker_recycle.start_watch()
    try:
        assert watch is not None
        assert worker_recycle.active is not None
        assert worker_recycle.active.max_growth_mb == 200.0
    finally:
        if watch is not None:
            watch.cancel()


async def test_a_background_job_keeps_the_worker_where_it_is(monkeypatch) -> None:
    """An import running in the worker is work in flight, though no request is.

    The task outlives the request that spawned it; a worker that left under it
    would cancel the import half way.
    """
    import asyncio

    from app.core import worker_recycle

    machine = _Machine()
    recycler = machine.recycler()
    monkeypatch.setattr(worker_recycle, 'active', recycler)
    machine.rss = 900.0
    release = asyncio.Event()

    async def job() -> None:
        await release.wait()

    task = asyncio.create_task(job())
    worker_recycle.hold_until_done(task)

    assert recycler.reason_to_replace() is None, 'never under a running job'
    release.set()
    await task
    assert recycler.reason_to_replace() is not None, 'and replaced after it'


async def test_a_job_spawned_for_import_is_held_against_the_recycler(
    monkeypatch,
) -> None:
    """``spawn`` is the one door a job runs through."""
    import asyncio
    from unittest.mock import MagicMock

    from app.core import worker_recycle
    from app.services.items import _import_job

    machine = _Machine()
    recycler = machine.recycler()
    monkeypatch.setattr(worker_recycle, 'active', recycler)
    machine.rss = 900.0
    release = asyncio.Event()

    async def run(*args, **kwargs) -> None:
        await release.wait()

    monkeypatch.setattr(_import_job, 'run_job_async', run)
    task = _import_job.spawn(MagicMock(), MagicMock())

    assert recycler.reason_to_replace() is None
    release.set()
    await task
    assert recycler.reason_to_replace() is not None
