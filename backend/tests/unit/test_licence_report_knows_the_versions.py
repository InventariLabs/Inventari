"""The licence gate looks at versions, not only at package names.

`THIRD_PARTY_LICENSES.md` carries a version column and the gate that guards
its freshness compared names alone: a dependency bumped in `uv.lock` left the
report quoting the old version and the check answered "117 listed packages
match pyproject and the lock". The table is the reader's answer to "what is
this shipping" — a wrong number there is the stale report the gate exists to
catch, arriving through the one door it did not watch.
"""

import os
from pathlib import Path

import pytest

from scripts.check_licences_fresh import (
    _locked_versions,
    _reported_backend_rows,
    version_mismatches,
)

pytestmark = pytest.mark.unit

#: The checkout root, wherever this test runs: on the host three parents above
#: this file, in the container the read-only mount docker-compose.yml names
#: with ``INVENTARI_REPO_ROOT``.
_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)


def test_a_package_whose_version_drifted_is_named_with_both_versions():
    """The refusal names the package and the two numbers that disagree."""
    reported = {'weasyprint': ('weasyprint', '69.0')}
    locked = {'weasyprint': '70.0'}

    problems = version_mismatches(reported, locked)

    assert problems == ['weasyprint: report says 69.0, uv.lock says 70.0']


def test_the_names_are_matched_the_way_packages_are_spelled():
    """`typing_extensions` in the table is `typing-extensions` in the lock."""
    reported = {'typing-extensions': ('typing_extensions', '4.0.0')}
    locked = {'typing-extensions': '4.1.0'}

    problems = version_mismatches(reported, locked)

    assert problems == ['typing_extensions: report says 4.0.0, uv.lock says 4.1.0']


def test_matching_versions_leave_nothing_to_say():
    """The green half: a report regenerated after the bump has no complaint."""
    reported = {'weasyprint': ('weasyprint', '70.0'), 'aiohttp': ('aiohttp', '3.14.3')}
    locked = {'weasyprint': '70.0', 'aiohttp': '3.14.3'}

    assert version_mismatches(reported, locked) == []


def test_a_package_the_lock_does_not_hold_is_left_to_the_departure_check():
    """Missing from the lock is a different complaint, made elsewhere.

    Reporting it here too would name the same row twice for one problem.
    """
    reported = {'gone': ('gone', '1.0')}
    locked = {}

    assert version_mismatches(reported, locked) == []


def test_the_shipped_report_agrees_with_the_lock():
    """The state after regeneration: the real files, the real numbers.

    Reads what the gate reads, so a dependency bumped without regenerating
    the report fails here as well as at the commit hook. Both files are
    tracked, so there is nothing to wait for and nothing to skip.
    """
    report = _REPO_ROOT / 'THIRD_PARTY_LICENSES.md'
    lock = _REPO_ROOT / 'backend' / 'uv.lock'

    problems = version_mismatches(
        _reported_backend_rows(report), _locked_versions(lock)
    )

    assert problems == [], problems


def test_the_report_table_carries_a_version_column():
    """The row shape the version comparison is built on still holds."""
    rows = _reported_backend_rows(_REPO_ROOT / 'THIRD_PARTY_LICENSES.md')

    assert rows, 'no "## Backend runtime" rows parsed'
    assert all(version for _, version in rows.values()), (
        'a row with an empty version cell is a version the gate cannot compare'
    )
