"""NOTICE and the About screen must name the same copyright years.

The About screen carries its own copy of the line — a name and years, not a
sentence to translate — because the browser cannot read NOTICE. Two copies
drift, and they did: both opened the range a year before the project began,
while the first commit is from February 2026. This pins them to each other,
and to the years the project has existed: a copyright line may not name a
year before the project began.
"""

import os
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

#: The checkout root, wherever this test runs: on the host three parents above
#: this file, in the container the read-only mount docker-compose.yml names
#: with ``INVENTARI_REPO_ROOT``.
_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)

_NOTICE = _REPO_ROOT / 'NOTICE'
_ABOUT = (
    _REPO_ROOT
    / 'frontend'
    / 'src'
    / 'modules'
    / 'settings'
    / 'pages'
    / 'SettingsAboutSection.tsx'
)

#: The year the project began — its first commit is from February 2026.
_FIRST_YEAR = 2026

_YEAR = re.compile(r'\b(\d{4})\b')
_NOTICE_LINE = re.compile(r'^Copyright \(C\) (.+)$', re.MULTILINE)
_ABOUT_LINE = re.compile(r'^const COPYRIGHT = "(.+)";$', re.MULTILINE)


def _years(line: str) -> list[int]:
    """The years a copyright line names, in the order it names them."""
    return [int(year) for year in _YEAR.findall(line)]


def _notice_line() -> str:
    match = _NOTICE_LINE.search(_NOTICE.read_text(encoding='utf-8'))
    assert match, f'NOTICE carries no "Copyright (C)" line: {_NOTICE}'
    return match.group(1)


def _about_line() -> str:
    match = _ABOUT_LINE.search(_ABOUT.read_text(encoding='utf-8'))
    assert match, f'the About screen carries no COPYRIGHT constant: {_ABOUT}'
    return match.group(1)


class TestTheCopyrightYears:
    def test_the_about_screen_names_the_years_notice_names(self) -> None:
        assert _years(_about_line()) == _years(_notice_line())

    def test_neither_names_a_year_before_the_project_existed(self) -> None:
        for source, line in (
            ('NOTICE', _notice_line()),
            ('the About screen', _about_line()),
        ):
            years = _years(line)
            assert years, f'{source} names no year at all: {line}'
            assert min(years) >= _FIRST_YEAR, (
                f'{source} names a year before the project began: {line}'
            )
