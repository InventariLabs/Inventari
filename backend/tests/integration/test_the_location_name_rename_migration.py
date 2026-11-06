"""The revision that clears repeated location names renames only the later ones.

Run against a scratch ``storage_locations`` (a temporary table that shadows the
real one for the session) holding the pairs the unique index could not be built
over: the oldest of each keeps its name, the later ones are numbered, a place
alone under its name is not touched, and the same name under another parent or
in another organization is not a repeat.
"""

from __future__ import annotations

import importlib.util

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import text

pytestmark = pytest.mark.integration

ORG_A = '00000000-0000-0000-0000-00000000000a'
ORG_B = '00000000-0000-0000-0000-00000000000b'
PARENT = '00000000-0000-0000-0000-0000000000f1'


@pytest.fixture(scope='module')
def revision():
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2]
        / 'migrations'
        / 'versions'
        / 'locnames01_one_name_per_level.py'
    )
    spec = importlib.util.spec_from_file_location('locnames01', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(n: int, org: str, parent: str | None, name: str, day: int) -> str:
    parent_sql = f"'{parent}'" if parent else 'NULL'
    return (
        f"('00000000-0000-0000-0000-{n:012d}', '{org}', {parent_sql}, "
        f"'{name}', '2026-10-{day:02d}')"
    )


def test_the_later_place_of_each_pair_is_numbered(revision, db_session):
    conn = db_session.connection()
    conn.execute(
        text(
            'CREATE TEMP TABLE storage_locations (id uuid PRIMARY KEY, '
            'organization_id uuid, parent_id uuid, name varchar(100), '
            'created_at timestamptz)'
        )
    )
    long_name = 'x' * 100
    rows = [
        _row(1, ORG_A, None, 'Cellar', 1),
        _row(2, ORG_A, None, 'Cellar', 2),
        _row(3, ORG_A, None, 'Cellar', 3),
        _row(4, ORG_A, None, 'Cellar (2)', 4),  # the number is taken already
        _row(5, ORG_A, PARENT, 'Cellar', 1),  # another level: not a repeat
        _row(6, ORG_B, None, 'Cellar', 1),  # another organization: not a repeat
        _row(7, ORG_A, None, long_name, 1),
        _row(8, ORG_A, None, long_name, 2),
    ]
    conn.execute(
        text(
            'INSERT INTO storage_locations '
            '(id, organization_id, parent_id, name, created_at) VALUES '
            + ', '.join(rows)
        )
    )

    with Operations.context(MigrationContext.configure(conn)):
        revision.upgrade()
        revision.upgrade()  # a replay changes nothing
        revision.downgrade()

    names = dict(
        conn.execute(
            text('SELECT right(id::text, 2)::int, name FROM storage_locations')
        ).all()
    )
    assert names[1] == 'Cellar'
    assert names[2] == 'Cellar (2)'
    assert names[3] == 'Cellar (3)'
    # The name that already held the number is the younger of the two now.
    assert names[4] == 'Cellar (2) (2)'
    assert names[5] == 'Cellar'
    assert names[6] == 'Cellar'
    assert names[7] == long_name
    assert names[8] == 'x' * 96 + ' (2)'
    assert len(names[8]) == 100
    # No repeat is left on any level.
    repeats = conn.execute(
        text(
            'SELECT count(*) FROM (SELECT 1 FROM storage_locations '
            'GROUP BY organization_id, parent_id, name HAVING count(*) > 1) r'
        )
    ).scalar()
    assert repeats == 0
