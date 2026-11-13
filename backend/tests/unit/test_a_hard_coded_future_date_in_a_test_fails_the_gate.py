"""The time-bomb gate flags dates that "now" will overtake, and nothing else."""

from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'check_time_bombs.py'
# The gate's own fixtures are dated around a "today" of 2000, so that they are
# already in the past for the real gate scanning this very file.
TODAY = date(2000, 6, 15)
NO_ALLOWLIST = json.dumps({'entries': []})


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location('check_time_bombs', _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def gate() -> ModuleType:
    return _load()


def _failing(gate: ModuleType, text: str, allowlist: str = NO_ALLOWLIST) -> list[str]:
    unlisted, _, _ = gate.check({'backend/tests/t.py': text}, allowlist, TODAY)
    return [hit.literal for hit in unlisted]


@pytest.mark.parametrize(
    'line, literal',
    [
        ("expiry = '2001-01-31'", '2001-01-31'),
        ("at = '2001-01-31T09:00:00+00:00'", '2001-01-31'),
        ('expiry = date(2001, 1, 31)', 'date(2001, 1, 31'),
        ('at = datetime(2001, 1, 31, 9)', 'datetime(2001, 1, 31'),
        ('const d = new Date(2001, 0, 31);', 'new Date(2001, 0, 31'),
        ("expiry = '2000-06-15'", '2000-06-15'),
    ],
)
def test_a_literal_on_or_after_today_fails(
    gate: ModuleType, line: str, literal: str
) -> None:
    assert _failing(gate, line) == [literal]


@pytest.mark.parametrize(
    'line',
    [
        "expiry = '2000-06-14'",
        'expiry = date(1990, 1, 31)',
        'const d = new Date(2000, 4, 31);',  # JavaScript: May
        "never = '2099-01-01'",
        "version = '1.2001-13-45'",  # not a calendar date
        'serial = 12001-01-31',
    ],
)
def test_a_past_sentinel_or_non_date_passes(gate: ModuleType, line: str) -> None:
    assert _failing(gate, line) == []


def test_a_clock_relative_date_passes(gate: ModuleType) -> None:
    assert _failing(gate, 'expiry = date.today() + timedelta(days=30)') == []


def test_an_allowlist_entry_with_a_reason_covers_every_occurrence(
    gate: ModuleType,
) -> None:
    allowlist = json.dumps(
        {
            'entries': [
                {
                    'path': 'backend/tests/t.py',
                    'literal': '2001-01-31',
                    'reason': 'a format round trip',
                }
            ]
        }
    )
    text = "a = '2001-01-31'\nb = '2001-01-31'\nc = '2001-02-01'\n"
    assert _failing(gate, text, allowlist) == ['2001-02-01']


def test_an_allowlist_entry_without_a_reason_fails(gate: ModuleType) -> None:
    allowlist = json.dumps(
        {'entries': [{'path': 'backend/tests/t.py', 'literal': '2001-01-31'}]}
    )
    unlisted, problems, _ = gate.check(
        {'backend/tests/t.py': "a = '2001-01-31'"}, allowlist, TODAY
    )
    assert len(unlisted) == 1  # an entry with no reason excuses nothing
    assert problems and 'reason' in problems[0]


def test_an_entry_for_a_date_that_passed_is_a_note_not_a_failure(
    gate: ModuleType,
) -> None:
    allowlist = json.dumps(
        {
            'entries': [
                {'path': 'backend/tests/t.py', 'literal': '1999-01-01', 'reason': 'x'}
            ]
        }
    )
    unlisted, problems, stale = gate.check(
        {'backend/tests/t.py': "a = '1999-01-01'"}, allowlist, TODAY
    )
    assert (unlisted, problems) == ([], [])
    assert stale == ['backend/tests/t.py 1999-01-01']


def test_the_committed_allowlist_is_well_formed(gate: ModuleType) -> None:
    raw = (_SCRIPT.with_name('time-bomb-allowlist.json')).read_text(encoding='utf-8')
    _, problems = gate.load_allowlist(raw)
    assert problems == []


@pytest.mark.parametrize(
    'path',
    [
        'backend/tests/unit/test_x.py',
        'backend/app/modules/warehouse/tests/integration/test_x.py',
        'backend/app/core/tests/test_x.py',
        'backend/app/services/test_x.py',
        'frontend/src/modules/a/B.test.tsx',
        'frontend/scripts/check-x.test.mjs',
        'frontend/tests/e2e/x.spec.ts',
    ],
)
def test_every_root_a_test_runner_collects_from_is_scanned(
    gate: ModuleType, path: str
) -> None:
    """Module-local suites and the lint scripts' own tests are tests too."""
    assert gate._BACKEND_TEST.match(path) or gate._FRONTEND_TEST.match(path)


@pytest.mark.parametrize(
    'path',
    [
        'backend/app/modules/warehouse/service.py',
        'backend/scripts/check_time_bombs.py',
        'frontend/scripts/check-x.mjs',
    ],
)
def test_production_code_is_not_scanned(gate: ModuleType, path: str) -> None:
    assert not (gate._BACKEND_TEST.match(path) or gate._FRONTEND_TEST.match(path))
