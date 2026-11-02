#!/usr/bin/env python3
"""Run the backend suite and report where its time actually goes.

Why this exists: a timing claim about this suite is worthless without the
conditions it was measured under. The review that produced this script found
two published numbers off by 4x and 2.2x — "the seed replay costs 216 ms a
test" (it costs ~55 ms) and "the arch-lint test takes 15.15 s" (6.84 s) —
and neither was wrong about the method. Both were measured on a 24-core host
at a load average of 25-53, and neither said so.
A reader had no way to tell those numbers from honest ones.

So the report always carries the machine with it: load average before and
after, CPU count, worker count, and whatever note the caller passes. A run
taken on a loaded host is still useful — it just has to admit what it is.

Usage (inside the backend container, via `make test-profile`):

    uv run python scripts/profile_suite.py --note "busy host"
    uv run python scripts/profile_suite.py --workers 8 -- tests/integration -k storage
    uv run python scripts/profile_suite.py --compare a.json b.json

The comparison mode answers the question the instrument exists for: are two
runs on this machine close enough that a difference between them means
anything? It prints the per-phase drift and says so outright.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

# `<seconds>s <phase> <nodeid>` — pytest's own duration report. The phase is
# what makes it interesting: setup is fixtures, call is the assertion the test
# was written for, teardown is the cleanup. A suite whose setup dwarfs its
# calls is paying for its fixture model, not for its assertions.
_DURATION = re.compile(r'^\s*([\d.]+)s\s+(setup|call|teardown)\s+(\S+)')
_PHASES = ('setup', 'call', 'teardown')

# Twelve, not ``auto``, for the reason every other suite run here uses twelve:
# the containers have no CPU limit, so ``auto`` takes every core of the host,
# and a profile taken that way measures the profiler's own contention.
_DEFAULT_WORKERS = 12

# Where reports land. Gitignored: they are measurements of one machine at one
# moment, not source.
_REPORT_DIR = Path(__file__).resolve().parent.parent / '.pytest-profile'


def _loadavg() -> tuple[float, float, float]:
    """Host load, not container load — /proc/loadavg is shared with the host."""
    try:
        parts = Path('/proc/loadavg').read_text().split()
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    except (OSError, ValueError, IndexError):
        return (-1.0, -1.0, -1.0)


def _run_pytest(extra: list[str], workers: int) -> tuple[str, float, int]:
    """Run the suite with every duration reported, and hand back its output.

    ``-vv`` matters: without it pytest hides every measurement under 5 ms,
    and those are exactly the pure-unit tests whose share of the suite the
    report is trying to state.
    """
    # No ``-q`` here: pytest sums verbosity flags, so ``-q -vv`` lands on 1 and
    # the sub-5ms measurements stay hidden — which is precisely the pure-unit
    # half of the suite this report has to account for.
    cmd = ['python', '-m', 'pytest', '-n', str(workers), '-vv', '--durations=0', *extra]
    started = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.stdout + proc.stderr, time.perf_counter() - started, proc.returncode


def _aggregate(output: str) -> dict:
    """Sum the per-phase durations, and keep the ten costliest files."""
    totals: dict[str, float] = dict.fromkeys(_PHASES, 0.0)
    counts: dict[str, int] = dict.fromkeys(_PHASES, 0)
    per_file: dict[str, float] = defaultdict(float)
    slowest: list[tuple[float, str, str]] = []

    for line in output.splitlines():
        match = _DURATION.match(line)
        if not match:
            continue
        seconds, phase, nodeid = float(match.group(1)), match.group(2), match.group(3)
        totals[phase] += seconds
        counts[phase] += 1
        per_file[nodeid.split('::')[0]] += seconds
        slowest.append((seconds, phase, nodeid))

    slowest.sort(reverse=True)
    measured = sum(totals.values())
    return {
        'phases': {
            phase: {
                'seconds': round(totals[phase], 2),
                'share_pct': round(100 * totals[phase] / measured, 1)
                if measured
                else 0.0,
                'n': counts[phase],
                'mean_ms': round(1000 * totals[phase] / counts[phase], 1)
                if counts[phase]
                else 0.0,
            }
            for phase in _PHASES
        },
        'measured_seconds': round(measured, 2),
        'top_files': [
            {'file': name, 'seconds': round(total, 1)}
            for name, total in sorted(per_file.items(), key=lambda kv: -kv[1])[:10]
        ],
        'slowest_single': [
            {'seconds': round(s, 2), 'phase': p, 'nodeid': n}
            for s, p, n in slowest[:10]
        ],
    }


def _outcome(output: str) -> str:
    """The summary line, which is the only thing that says the run happened.

    An interrupted run can still exit 0 through a pipe, so the report quotes
    the line pytest wrote rather than trusting a status.
    """
    for line in reversed(output.splitlines()):
        if ' passed' in line or ' failed' in line or ' error' in line:
            return line.strip()
    return '(no pytest summary line — the run did not finish)'


def _render(report: dict) -> str:
    machine = report['machine']
    lines = [
        f'suite profile — {report["started_utc"]}',
        '',
        f'  outcome      {report["outcome"]}',
        f'  wall         {report["wall_seconds"]}s across {machine["workers"]} workers',
        f'  cpus         {machine["cpus"]}',
        f'  load 1/5/15  {machine["load_before"]} -> {machine["load_after"]}',
        f'  note         {machine["note"] or "(none)"}',
        '',
        '  phase      seconds   share      n    mean',
    ]
    for phase in _PHASES:
        data = report['phases'][phase]
        lines.append(
            f'  {phase:9} {data["seconds"]:9.1f} {data["share_pct"]:6.1f}% '
            f'{data["n"]:6} {data["mean_ms"]:7.0f}ms'
        )
    lines += [
        '',
        f'  measured     {report["measured_seconds"]}s of test time',
        f'  worker-time  {report["worker_seconds"]}s (wall x workers)',
        f'  unaccounted  {report["unaccounted_pct"]}% — collection, imports, '
        'session fixtures, and workers waiting',
        '',
        '  costliest files',
    ]
    lines += [f'  {row["seconds"]:8.1f}s  {row["file"]}' for row in report['top_files']]
    lines += ['', '  costliest single measurements']
    lines += [
        f'  {row["seconds"]:8.2f}s  {row["phase"]:8} {row["nodeid"]}'
        for row in report['slowest_single']
    ]

    if machine['load_before'][0] > machine['cpus'] * 0.5:
        lines += [
            '',
            '  WARNING: this host was already busy when the run started '
            f'(load {machine["load_before"][0]} against {machine["cpus"]} cpus). '
            'Absolute numbers from this run compare only with other runs taken '
            'under the same load — not with a number someone quoted elsewhere.',
        ]
    return '\n'.join(lines) + '\n'


def _compare(first: Path, second: Path) -> int:
    """Say whether two runs on this machine are close enough to compare.

    The threshold is the acceptance criterion this instrument was written
    for: two consecutive runs must agree on the setup share within five
    percentage points, or the machine is too noisy to measure on right now.
    """
    a, b = json.loads(first.read_text()), json.loads(second.read_text())
    print(f'{"phase":10} {first.name:>14} {second.name:>14}   drift')
    worst = 0.0
    for phase in _PHASES:
        first_share = a['phases'][phase]['share_pct']
        second_share = b['phases'][phase]['share_pct']
        drift = abs(first_share - second_share)
        worst = max(worst, drift)
        print(f'{phase:10} {first_share:13.1f}% {second_share:13.1f}% {drift:7.1f}pp')
    print(f'\nwall: {a["wall_seconds"]}s vs {b["wall_seconds"]}s')
    if worst <= 5.0:
        print(f'\nComparable: worst phase drift {worst:.1f}pp is within 5pp.')
        return 0
    print(
        f'\nNOT comparable: worst phase drift {worst:.1f}pp exceeds 5pp. '
        'This machine is too noisy right now — a difference measured here '
        'cannot be attributed to a code change.'
    )
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--note', default='', help='what else was running, in your words'
    )
    parser.add_argument(
        '--compare', nargs=2, metavar=('A.json', 'B.json'), help='compare two reports'
    )
    parser.add_argument(
        '--workers',
        type=int,
        default=_DEFAULT_WORKERS,
        help=f'pytest-xdist workers (default {_DEFAULT_WORKERS})',
    )
    parser.add_argument('pytest_args', nargs='*', help='passed through to pytest')
    args = parser.parse_args()

    if args.compare:
        return _compare(Path(args.compare[0]), Path(args.compare[1]))

    cpus = os.cpu_count() or 0
    load_before = _loadavg()
    output, wall, code = _run_pytest(args.pytest_args, args.workers)
    load_after = _loadavg()

    report = _aggregate(output)
    # What the workers could have spent, so it follows the workers the run
    # actually had — not the host's cores, which the run was told to leave.
    worker_seconds = round(wall * args.workers, 1)
    report.update(
        {
            'started_utc': datetime.now(UTC).isoformat(timespec='seconds'),
            'wall_seconds': round(wall, 1),
            'worker_seconds': worker_seconds,
            'unaccounted_pct': round(
                100 * (1 - report['measured_seconds'] / worker_seconds), 1
            )
            if worker_seconds
            else 0.0,
            'outcome': _outcome(output),
            'pytest_args': args.pytest_args,
            'machine': {
                'cpus': cpus,
                'workers': args.workers,
                'load_before': list(load_before),
                'load_after': list(load_after),
                'note': args.note,
            },
        }
    )

    _REPORT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    (_REPORT_DIR / f'{stamp}.json').write_text(json.dumps(report, indent=1))
    text = _render(report)
    (_REPORT_DIR / f'{stamp}.txt').write_text(text)
    print(text)
    print(f'written: backend/.pytest-profile/{stamp}.{{txt,json}}')
    return code


if __name__ == '__main__':
    sys.exit(main())
