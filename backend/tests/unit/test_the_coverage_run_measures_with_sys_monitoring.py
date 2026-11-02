"""The coverage run measures with sys.monitoring, not with the old line tracer.

Coverage picks its measuring core from its configuration, and some settings
quietly send it back to the line tracer it used before Python 3.12 — naming
``greenlet`` in ``concurrency`` is one, dynamic contexts are another. Nothing
fails when that happens; the full suite with ``--cov`` just takes twice as
long. It did, from the day ``greenlet`` was added until 2026-10-12: 464 s
against 239 s at ``-n 12``, with the same report file for file.

This test asks coverage which core the backend's own configuration gives it,
in a process of its own so the run measuring this one is not disturbed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

#: The tree whose pyproject.toml configures coverage — ``backend/`` on the
#: host, ``/app`` in the container. Both are two parents above this file.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]

_ASK_FOR_THE_CORE = """
import coverage
cov = coverage.Coverage(data_file=None)
cov.start()
cov.stop()
print(dict(cov.sys_info())['core'])
"""


def test_the_configured_coverage_measures_with_sys_monitoring() -> None:
    core = subprocess.run(
        [sys.executable, '-c', _ASK_FOR_THE_CORE],
        cwd=_BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    assert core == 'SysMonitor', (
        f'coverage measures with {core}: a setting in [tool.coverage.run] '
        'sent it back to the line tracer, which doubles the suite under --cov'
    )
