"""The full suite ends when its last worker does, so no worker may be left alone.

xdist's default ``load`` scheduler hands every worker consecutive chunks of
the collection up front and never takes them back. A chunk that happens to
hold the heavy tests — the demo seed story, the upgrade stamp guard, the
property tests over stock postings — keeps one worker busy long after the
other eleven have nothing left: measured on a full run, eleven workers were
done at 392 s and the twelfth ran alone until 587 s, a third of the suite's
wall time spent on one core.

``worksteal`` lets an idle worker take half of the queue of the busiest one,
so the run ends with the work, not with the unluckiest chunk. It lives in
``pytest.ini`` so that every way the suite is started — the Makefile, CI and
the test wrapper all pass ``-n`` and nothing else — schedules the same way.
Without ``-n`` xdist ignores the option and the run stays in one process.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_the_suite_lets_idle_workers_steal_from_busy_ones(
    pytestconfig: pytest.Config,
) -> None:
    assert '--dist=worksteal' in pytestconfig.getini('addopts')
