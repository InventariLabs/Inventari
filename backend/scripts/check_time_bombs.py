#!/usr/bin/env python3
"""Gate: a test must not hard-code a calendar date that "now" will overtake.

A fixture such as ``expiry_date = '2027-01-31'`` reads as "far in the future"
on the day it is written. On 2027-01-31 it silently turns into "in the past",
and the test goes on passing or failing about something other than what its
name says. Nothing marks that day in advance, so the gate looks for the
literals instead.

What is flagged: an absolute date written in a test file — an ISO literal
(``2027-01-31``, with or without a time) or a constructor call
(``date(2027, 1, 31)``, ``datetime(2027, 1, 31, ...)``, ``new Date(2027, 0,
31)``) — that falls on or after today. A date already in the past cannot
become a time bomb: it stays in the past. A date in 2099 or later is a
sentinel for "never" and is out of reach of any clock a test will see. The gate therefore only ever gets
greener as the calendar moves; it never turns red on its own, and a literal
that was fine yesterday is not reported today.

What is not flagged is whatever lives in ``time-bomb-allowlist.json``: an entry
names a file and a literal and carries a reason (a format or round-trip test
that never compares with the clock, a sentinel such as 2099-01-01 that stands
for "never"). An entry without a reason fails the gate. An entry covers every
occurrence of that literal in that file, so line numbers drifting does not
break it. An entry whose literal no longer fires is reported, not failed:
it may have passed into the past, and the gate must not go red by the clock.

The better fix is nearly always to write the date relative to the clock
(``date.today() + timedelta(days=30)``, ``addDays(new Date(), 30)``); the
allowlist is for the few places where a fixed date is the point.

Standard library only: it runs on the host, where ``make lint`` lives.

    python3 backend/scripts/check_time_bombs.py [--today YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import NamedTuple

_ROOT = Path(__file__).resolve().parents[2]
_ALLOWLIST = Path(__file__).with_name('time-bomb-allowlist.json')

# Test files only, and every root a gate collects them from. Backend: what
# pytest.ini's ``testpaths`` names — Python files under backend/tests, under
# any ``tests`` directory inside backend/app (module-local suites), and
# ``test_*.py`` beside the code. Frontend: ``*.test.ts(x)`` anywhere in src,
# the ``*.test.mjs`` of the lint scripts, and everything under frontend/tests
# (the Playwright specs and their helpers).
_SENTINEL_YEAR = 2099

_BACKEND_TEST = re.compile(
    r'^backend/(?:tests/.+|app/(?:.+/)?tests/.+|app/(?:.+/)?test_[^/]+)\.py$'
)
_FRONTEND_TEST = re.compile(
    r'^frontend/(?:src/.+\.(?:test|spec)\.tsx?|scripts/.+\.test\.mjs|tests/.+\.tsx?)$'
)

_ISO = re.compile(r'(?<![\d-])(\d{4})-(\d{2})-(\d{2})(?![\d-]\d)')
_CALL = re.compile(
    r'\b(?P<fn>date|datetime|new Date)\(\s*(?P<y>\d{4})\s*,\s*(?P<m>\d{1,2})\s*,\s*(?P<d>\d{1,2})\b'
)


class Hit(NamedTuple):
    path: str
    line: int
    literal: str
    day: date


def _day(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def scan_text(path: str, text: str) -> list[Hit]:
    """Every absolute date in ``text``, as written, with its line."""
    hits: list[Hit] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for match in _ISO.finditer(line):
            day = _day(*(int(g) for g in match.groups()))
            if day:
                hits.append(Hit(path, number, match.group(0), day))
        for match in _CALL.finditer(line):
            month = int(match['m'])
            if match['fn'] == 'new Date':
                month += 1  # JavaScript months count from zero
            day = _day(int(match['y']), month, int(match['d']))
            if day:
                hits.append(Hit(path, number, match.group(0), day))
    return hits


def load_allowlist(raw: str) -> tuple[dict[tuple[str, str], str], list[str]]:
    """(path, literal) -> reason, and a message per malformed entry."""
    entries: dict[tuple[str, str], str] = {}
    problems: list[str] = []
    for index, entry in enumerate(json.loads(raw).get('entries', [])):
        path, literal = entry.get('path', ''), entry.get('literal', '')
        reason = str(entry.get('reason', '')).strip()
        if not path or not literal:
            problems.append(f'allowlist entry {index}: needs "path" and "literal"')
        elif not reason:
            problems.append(f'allowlist entry {path} {literal}: needs a "reason"')
        else:
            entries[(path, literal)] = reason
    return entries, problems


def check(
    files: dict[str, str], allowlist_raw: str, today: date
) -> tuple[list[Hit], list[str], list[str]]:
    """(unlisted hits, allowlist problems, stale allowlist entries)."""
    allowed, problems = load_allowlist(allowlist_raw)
    used: set[tuple[str, str]] = set()
    unlisted: list[Hit] = []
    for path, text in sorted(files.items()):
        for hit in scan_text(path, text):
            if hit.day < today or hit.day.year >= _SENTINEL_YEAR:
                continue
            if (hit.path, hit.literal) in allowed:
                used.add((hit.path, hit.literal))
            else:
                unlisted.append(hit)
    stale = [f'{p} {lit}' for p, lit in sorted(set(allowed) - used)]
    return unlisted, problems, stale


def _tracked_test_files() -> dict[str, str]:
    names = subprocess.run(
        ['git', 'ls-files', '-z', '--', 'backend/tests', 'backend/app', 'frontend'],
        cwd=_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split('\0')
    files: dict[str, str] = {}
    for name in names:
        if name and (_BACKEND_TEST.match(name) or _FRONTEND_TEST.match(name)):
            target = _ROOT / name
            if target.is_file():
                files[name] = target.read_text(encoding='utf-8', errors='replace')
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--today', type=date.fromisoformat, default=date.today())
    args = parser.parse_args()

    files = _tracked_test_files()
    if not files:
        print('check_time_bombs: no test files found — wrong working tree?')
        return 2
    unlisted, problems, stale = check(
        files, _ALLOWLIST.read_text(encoding='utf-8'), args.today
    )
    for note in stale:
        print(f'note: allowlist entry no longer fires: {note}')
    for problem in problems:
        print(f'FAIL: {problem}')
    for hit in unlisted:
        print(
            f'FAIL: {hit.path}:{hit.line}: {hit.literal} is on or after '
            f'{args.today} — write it relative to the clock, or allowlist it '
            f'with a reason in backend/scripts/{_ALLOWLIST.name}'
        )
    if unlisted or problems:
        return 1
    print(f'time bombs: {len(files)} test files, none unlisted')
    return 0


if __name__ == '__main__':
    sys.exit(main())
