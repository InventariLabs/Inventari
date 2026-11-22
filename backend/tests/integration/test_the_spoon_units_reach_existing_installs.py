"""The revision that adds the spoons gives them to an installation with cups.

An installation that took the US kitchen measures before the spoons were part
of them gets a tablespoon and a teaspoon in Volume; one without the cup gets
nothing; a spoon already there, or one someone named the same, is not doubled.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import text

pytestmark = pytest.mark.integration


@pytest.fixture(scope='module')
def revision():
    path = (
        Path(__file__).resolve().parents[2]
        / 'migrations'
        / 'versions'
        / 'spoons01_kitchen_spoons_for_existing_installs.py'
    )
    spec = importlib.util.spec_from_file_location('spoons01', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _spoons(conn) -> dict[str, tuple[str, float, str]]:
    rows = conn.execute(
        text(
            'SELECT u.name, u.symbol, u.factor, c.name FROM uoms u '
            'JOIN uom_categories c ON c.id = u.category_id '
            "WHERE u.name IN ('Tablespoon', 'Teaspoon')"
        )
    ).all()
    return {n: (s, float(f), c) for n, s, f, c in rows}


def _kitchen_without_spoons(conn, *, cup: str) -> None:
    """Leave only a cup (named *cup*) of the kitchen measures, in Volume."""
    conn.execute(
        text("DELETE FROM uoms WHERE name IN ('Tablespoon', 'Teaspoon', 'Cup (US)')")
    )
    category = conn.execute(
        text("SELECT id FROM uom_categories WHERE name = 'Volume' LIMIT 1")
    ).scalar()
    if category is None:
        category = conn.execute(
            text(
                'INSERT INTO uom_categories (id, name) '
                "VALUES (gen_random_uuid(), 'Volume') RETURNING id"
            )
        ).scalar()
    conn.execute(
        text(
            'INSERT INTO uoms (id, category_id, name, symbol, factor, '
            'is_reference, is_system, rounding) VALUES '
            '(gen_random_uuid(), :c, :n, :s, 236.588, false, true, 0.001)'
        ),
        {'c': category, 'n': cup, 's': 'cup'},
    )


def _upgrade(revision, conn) -> None:
    with Operations.context(MigrationContext.configure(conn)):
        revision.upgrade()


def test_an_installation_with_cups_gets_both_spoons_once(revision, db_session):
    conn = db_session.connection()
    _kitchen_without_spoons(conn, cup='Cup (US)')

    _upgrade(revision, conn)
    _upgrade(revision, conn)  # a replay adds nothing

    spoons = _spoons(conn)
    assert spoons['Tablespoon'] == ('tbsp', pytest.approx(14.7868), 'Volume')
    assert spoons['Teaspoon'] == ('tsp', pytest.approx(4.92892), 'Volume')
    assert (
        conn.execute(
            text("SELECT count(*) FROM uoms WHERE name IN ('Tablespoon', 'Teaspoon')")
        ).scalar()
        == 2
    )


def test_an_installation_without_cups_gets_no_spoons(revision, db_session):
    conn = db_session.connection()
    _kitchen_without_spoons(conn, cup='Cup (QA)')

    _upgrade(revision, conn)

    assert _spoons(conn) == {}
