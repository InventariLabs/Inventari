"""What startup built is out of the garbage collector's way.

A worker that has imported the application holds close to nine hundred
thousand objects the collector tracks — modules, routes, mappers, schemas —
and every one of them lives as long as the process. A full collection walked
all of them, two to three hundred milliseconds, and the requests that
allocate the most set one off the most often: at a hundred thousand products
the location tree asked without a single count answered in under a tenth of
a second at the median and in over half a second at the ninety-fifth
percentile, and that alone put the tail of the read above the screen's
budget.

Frozen once startup is done, they are no longer the collector's to walk; a
collection after it reads only what requests made.
"""

from __future__ import annotations

import gc
import logging
from collections.abc import Iterator

import pytest

from app import _lifespan


@pytest.fixture
def started_outside_tests(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """``_start_services`` on the path a deployed worker takes, with each
    service it connects to stubbed out."""

    async def nothing(*_args: object, **_kwargs: object) -> None:
        return None

    async def no_failed_modules(*_args: object) -> list[str]:
        return []

    monkeypatch.setattr('app.config.settings.TESTING', False)
    monkeypatch.setattr(_lifespan, '_connect_redis_services', nothing)
    monkeypatch.setattr(_lifespan, '_wire_token_blacklist_and_cache', nothing)
    monkeypatch.setattr(_lifespan, '_seed_and_bootstrap', nothing)
    monkeypatch.setattr(_lifespan, '_initialize_modules', no_failed_modules)
    monkeypatch.setattr(_lifespan, '_register_background_jobs', lambda *_: None)
    monkeypatch.setattr(_lifespan, '_reclaim_after_restart', nothing)
    monkeypatch.setattr('app.core.dev_guard.run_dev_guard', lambda: None)
    try:
        yield
    finally:
        # The test process is not a worker: its objects go back to the
        # collector, or every later test's garbage would stay with them.
        gc.unfreeze()


async def test_a_started_worker_leaves_its_startup_heap_to_no_collection(
    started_outside_tests: None,
) -> None:
    before = gc.get_freeze_count()

    await _lifespan._start_services(logging.getLogger('test'), event_bus=None)

    assert gc.get_freeze_count() > before


async def test_the_test_suite_freezes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    # Under TESTING each test enters the lifespan again; freezing there would
    # keep every earlier test's leftovers out of the collector for good.
    monkeypatch.setattr('app.config.settings.TESTING', True)
    before = gc.get_freeze_count()

    await _lifespan._start_services(logging.getLogger('test'), event_bus=None)

    assert gc.get_freeze_count() == before
