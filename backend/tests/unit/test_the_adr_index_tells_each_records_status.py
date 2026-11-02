"""The ADR index lists every decision record with the status the record states.

``docs/adr/README.md`` is where a reader learns which decisions still hold.
The documentation pass before publication found it drifting from the records
themselves three times in one table: ADR-005 was listed as superseded by an
ADR that has nothing to do with database drivers, ADR-011 had been amended
and ADR-020 superseded in part while the index still said plainly
*Accepted*. Each record's own ``## Status`` section was right; the index was
a copy nobody compared again. This test compares it:

* every ``ADR-*.md`` file has exactly one row, the row links that file, and
  the row's title is the record's heading;
* the row's status opens with the same word as the record's (*Accepted* or
  *Superseded*), says *amended* when a record still in force was amended,
  and names every other
  ADR that the record's status links to as having replaced part of it — and
  no ADR the record's status does not link;
* when a record says it supersedes another, the other one's row says it is
  superseded by this one.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)
_ADR_DIR = _REPO_ROOT / 'docs' / 'adr'

_ROW = re.compile(r'^\| \[(ADR-\d{3})\]\(([^)]+)\) \| (.+?) \| (.+?) \|$', re.MULTILINE)
_HEADING = re.compile(r'^# (ADR-\d{3}): (.+)$', re.MULTILINE)
_LINKED_ADR = re.compile(r'\[(ADR-\d{3})\]\(')
_SUPERSEDES = re.compile(r'Supersedes \[(ADR-\d{3})\]\(')


def _records() -> dict[str, tuple[str, str]]:
    """ADR id -> (file name, text) for every record in the directory."""
    if not _ADR_DIR.is_dir():
        pytest.skip('docs/adr is not part of this checkout')
    records = {}
    for path in sorted(_ADR_DIR.glob('ADR-*.md')):
        records[path.name[:7]] = (path.name, path.read_text(encoding='utf-8'))
    return records


def _status(text: str) -> str:
    """The prose of the record's ``## Status`` section, or its ``**Status:**`` line."""
    match = re.search(r'^## Status\n(.*?)(?=^## )', text, re.MULTILINE | re.DOTALL)
    match = match or re.search(r'^- \*\*Status:\*\* (.+)$', text, re.MULTILINE)
    assert match, 'record states no status'
    return match.group(1).strip()


def _index_rows() -> dict[str, tuple[str, str, str]]:
    index = (_ADR_DIR / 'README.md').read_text(encoding='utf-8')
    rows: dict[str, tuple[str, str, str]] = {}
    for adr, link, title, status in _ROW.findall(index):
        assert adr not in rows, f'{adr} has two rows in docs/adr/README.md'
        rows[adr] = (link, title.strip(), status.strip())
    return rows


def test_every_record_has_one_row_that_links_it_under_its_own_title():
    records = _records()
    rows = _index_rows()

    assert sorted(rows) == sorted(records), (
        'docs/adr/README.md rows and ADR-*.md files differ: '
        f'rows only {sorted(set(rows) - set(records))}, '
        f'files only {sorted(set(records) - set(rows))}'
    )
    for adr, (name, text) in records.items():
        link, title, _ = rows[adr]
        heading = _HEADING.search(text)
        assert heading and heading.group(1) == adr, (
            f'{name} does not open with "# {adr}: …"'
        )
        assert link == name, f'the {adr} row links {link}, the file is {name}'
        assert title == heading.group(2).strip(), (
            f'the {adr} row is titled {title!r}, the record {heading.group(2).strip()!r}'
        )


def test_every_row_states_the_status_its_record_states():
    records = _records()
    rows = _index_rows()
    wrong = []
    for adr, (_, text) in records.items():
        status = _status(text)
        row_status = rows[adr][2]
        first_word = status.split()[0].strip('—(.,')
        if row_status.split()[0].strip(',') != first_word:
            wrong.append(
                f'{adr}: record says {first_word!r}, index says {row_status!r}'
            )
        amended = first_word == 'Accepted' and 'amended' in status.lower()
        if amended and 'amended' not in row_status.lower():
            wrong.append(f'{adr}: record is amended, index says {row_status!r}')
        replaced_by = set(_LINKED_ADR.findall(status)) - set(
            _SUPERSEDES.findall(status)
        )
        for other in sorted(replaced_by - {adr}):
            if other not in row_status:
                wrong.append(
                    f'{adr}: record status names {other}, index says {row_status!r}'
                )
        for other in sorted(
            set(re.findall(r'ADR-\d{3}', row_status)) - set(_LINKED_ADR.findall(status))
        ):
            wrong.append(f'{adr}: index names {other}, the record status does not')
    assert not wrong, 'docs/adr/README.md disagrees with the records:\n' + '\n'.join(
        wrong
    )


def test_a_superseded_record_names_the_record_that_supersedes_it():
    records = _records()
    rows = _index_rows()
    wrong = []
    for adr, (_, text) in records.items():
        for older in _SUPERSEDES.findall(_status(text)):
            if not rows[older][2].startswith(f'Superseded by {adr}'):
                wrong.append(
                    f'{adr} supersedes {older}, whose row says {rows[older][2]!r}'
                )
            if adr not in _LINKED_ADR.findall(_status(records[older][1])):
                wrong.append(
                    f'{adr} supersedes {older}, whose own status does not link {adr}'
                )
    assert not wrong, '\n'.join(wrong)
