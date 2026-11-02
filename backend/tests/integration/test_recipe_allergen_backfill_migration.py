"""The allergen backfill revision fills only the rows that have none.

The revision carries its own copy of the name-to-allergen inference, so what it
writes cannot move when the runtime map does. These tests run its ``upgrade``
against a scratch ``recipe_ingredients`` (a temporary table that shadows the
real one for the session) holding the three kinds of row it meets.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import text

from app.core.module_migrations import module_migrations_dir

pytestmark = pytest.mark.integration


@pytest.fixture(scope='module')
def revision():
    path = (
        module_migrations_dir('recipes')
        / 'versions'
        / '003_backfill_ingredient_allergens.py'
    )
    spec = importlib.util.spec_from_file_location(
        'recipes_003_backfill_allergens', Path(path)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_it_infers_polish_and_english_names(revision):
    assert revision._infer_allergens('Mąka pszenna') == ['gluten']
    assert revision._infer_allergens('Peanuts') == ['peanuts']
    assert revision._infer_allergens('Ser żółty') == ['milk']
    assert revision._infer_allergens('Salmon & shrimp') == ['crustaceans', 'fish']
    assert revision._infer_allergens('coconut') == []
    assert revision._infer_allergens('') == []


def test_upgrade_fills_only_rows_without_allergens(revision, db_session):
    conn = db_session.connection()
    conn.execute(
        text(
            'CREATE TEMP TABLE recipe_ingredients '
            '(id serial PRIMARY KEY, name text, allergens jsonb)'
        )
    )
    conn.execute(
        text(
            'INSERT INTO recipe_ingredients (name, allergens) VALUES '
            "('Milk', NULL), ('Egg', '[]'), ('Cream', '[\"soy\"]'), ('Water', '[]')"
        )
    )

    with Operations.context(MigrationContext.configure(conn)):
        revision.upgrade()
        revision.upgrade()  # a replay changes nothing
        revision.downgrade()

    stored = dict(
        conn.execute(text('SELECT name, allergens FROM recipe_ingredients')).all()
    )
    assert stored == {
        'Milk': ['milk'],
        'Egg': ['eggs'],
        'Cream': ['soy'],  # curated by hand: never touched
        'Water': [],
    }
