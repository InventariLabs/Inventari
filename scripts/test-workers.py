#!/usr/bin/env python3
"""How many parallel test workers this machine carries: pytest-xdist or Playwright.

    scripts/test-workers.py pytest
    scripts/test-workers.py playwright

The one place both counts come from. The Makefile's test targets, the CI
workflow and `frontend/playwright.config.ts` all ask this script, so a suite
follows the hardware it runs on instead of a number picked on one machine:
CI once ran `pytest -n 8` and eight Playwright workers on a two-CPU, 7 GB
runner, and the backend job lost an xdist worker to the out-of-memory killer
while the browser specs timed out on a starved CPU.

The machine is read the way a container sees it as well as the way a VM does.
A container started with `--cpus 2 --memory 7g` still reports every core and
all the RAM of its host through `nproc` and `/proc/meminfo`; its cgroup holds
the real limits, so those win when they are tighter.

Each count is the smaller of a CPU budget and a memory budget:

- pytest: four workers per core, because the suite spends its time waiting on
  Postgres, not on the CPU (measured on a two-core runner with coverage on:
  239 s at -n 2, 137 s at -n 8); at most 12, past which the 24-core
  development machine stopped gaining. Each worker is given 1 GiB of the
  memory available now, which covers it, its Postgres backend and the
  coverage data it holds until the end of the run.
- Playwright: one worker per core, because each one drives a browser that
  renders, and the backend and the dev server under test need the same CPUs;
  at most 8, the most the stack's database connections took. Each worker is
  given 1.5 GiB: a browser, and its share of the servers under test.

Never fewer than one worker. `PYTEST_WORKERS=<n>` (make) and
`PLAYWRIGHT_WORKERS=<n>` override a single run.

`scripts/test_test_workers.py` runs both budgets against synthetic cgroup and
meminfo files (`make lint` runs it), so a change that stops either the CPU or
the memory budget from limiting the count fails there, not on a runner.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

GIB = 1024**3

# suite: (workers per core, ceiling, memory per worker)
BUDGETS = {
    'pytest': (4, 12, 1 * GIB),
    'playwright': (1, 8, 1.5 * GIB),
}

_CGROUP = Path('/sys/fs/cgroup')
_MEMINFO = Path('/proc/meminfo')


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def cores() -> int:
    """Cores this process may use: its CPU affinity, capped by a cgroup CPU quota."""
    count = len(os.sched_getaffinity(0))
    # cgroup v2: "<quota> <period>" or "max <period>".
    quota, _, period = (_read(_CGROUP / 'cpu.max') or 'max').partition(' ')
    if quota == 'max':
        # cgroup v1: a quota of -1 means none.
        quota = _read(_CGROUP / 'cpu' / 'cpu.cfs_quota_us') or '-1'
        period = _read(_CGROUP / 'cpu' / 'cpu.cfs_period_us') or '100000'
    if quota.lstrip('-').isdigit() and int(quota) > 0:
        count = min(count, math.ceil(int(quota) / int(period)))
    return max(1, count)


def available_memory() -> int:
    """Bytes free for new work now: the machine's, capped by a cgroup memory limit."""
    meminfo = dict(
        line.split(':', 1) for line in (_read(_MEMINFO) or '').splitlines()
    )
    free = int(meminfo.get('MemAvailable', '0 kB').split()[0]) * 1024
    for group in (_CGROUP, _CGROUP / 'memory'):
        v2 = group == _CGROUP
        limit = _read(group / ('memory.max' if v2 else 'memory.limit_in_bytes'))
        usage = _read(group / ('memory.current' if v2 else 'memory.usage_in_bytes'))
        if not (limit and limit.isdigit() and usage and usage.isdigit()):
            continue
        # The group's usage counts the page cache an install left behind; the
        # kernel drops its inactive part before it kills anything.
        stat = dict(
            line.split(' ', 1) for line in (_read(group / 'memory.stat') or '').splitlines()
        )
        cache = int(stat.get('inactive_file' if v2 else 'total_inactive_file', '0'))
        return min(free, int(limit) - int(usage) + cache)
    return free


def workers(suite: str) -> int:
    per_core, ceiling, per_worker = BUDGETS[suite]
    by_cpu = cores() * per_core
    by_memory = int(available_memory() // per_worker)
    return max(1, min(by_cpu, by_memory, ceiling))


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in BUDGETS:
        print(f'usage: {argv[0]} {"|".join(BUDGETS)}', file=sys.stderr)
        return 2
    print(workers(argv[1]))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
