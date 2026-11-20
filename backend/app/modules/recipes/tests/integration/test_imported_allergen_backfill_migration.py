"""The second allergen backfill fills the lines a recipe import left empty.

Its ``upgrade`` runs against a scratch ``recipe_ingredients`` (a temporary
table that shadows the real one for the connection) on a connection of its
own, because the revision commits page by page.
"""

from __future__ import annotations

import importlib.util
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection, Engine, text

from app.core.module_migrations import module_migrations_dir

pytestmark = pytest.mark.integration


@pytest.fixture(scope='module')
def revision() -> ModuleType:
    path = (
        module_migrations_dir('recipes')
        / 'versions'
        / '014_backfill_imported_allergens.py'
    )
    spec = importlib.util.spec_from_file_location(
        'recipes_014_backfill_imported_allergens', Path(path)
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def scratch(engine: Engine, setup_test_db: Engine) -> Iterator[Connection]:
    with engine.connect() as conn:
        conn.execute(
            text(
                'CREATE TEMP TABLE recipe_ingredients '
                '(id uuid PRIMARY KEY, name text NOT NULL, allergens jsonb)'
            )
        )
        conn.commit()
        try:
            yield conn
        finally:
            conn.rollback()
            conn.execute(text('DROP TABLE IF EXISTS pg_temp.recipe_ingredients'))
            conn.commit()


def test_it_infers_what_the_recipe_form_infers(revision: ModuleType) -> None:
    assert revision._infer_allergens('Butter') == ['milk']
    assert revision._infer_allergens('Cheddar cheese') == ['milk']
    assert revision._infer_allergens('Eggs') == ['eggs']
    assert revision._infer_allergens('Spaghetti') == ['gluten']
    assert revision._infer_allergens('Masło') == ['milk']
    assert revision._infer_allergens('Masło orzechowe') == ['peanuts']
    assert revision._infer_allergens('Peanut butter') == ['peanuts']
    assert revision._infer_allergens('Coconut milk') == []
    assert revision._infer_allergens('Almond milk') == ['nuts']
    assert revision._infer_allergens('Mixed nuts') == ['nuts']
    assert revision._infer_allergens('Nutmeg') == []
    assert revision._infer_allergens('') == []


def test_upgrade_fills_every_empty_line_across_pages(
    revision: ModuleType, scratch: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two rows a page, and lines the inference leaves empty between the ones
    # it fills: the walk has to step past them rather than meet them again.
    monkeypatch.setattr(revision, '_BATCH', 2)
    rows = [
        ('Butter', None),
        ('Water', '[]'),
        ('Eggs', '[]'),
        ('Cream', '["soy"]'),
        ('Cheddar cheese', '[]'),
        ('Salt', '[]'),
        ('Coconut milk', '[]'),
    ]
    scratch.execute(
        text(
            'INSERT INTO recipe_ingredients (id, name, allergens) '
            'VALUES (:id, :name, CAST(:allergens AS jsonb))'
        ),
        [
            {'id': uuid.UUID(int=n), 'name': name, 'allergens': allergens}
            for n, (name, allergens) in enumerate(rows, start=1)
        ],
    )
    scratch.commit()

    with Operations.context(MigrationContext.configure(scratch)):
        revision.upgrade()
        revision.upgrade()  # a replay finds nothing more to write
        revision.downgrade()

    stored = {
        row.name: row.allergens
        for row in scratch.execute(
            text('SELECT name, allergens FROM recipe_ingredients')
        )
    }
    assert stored == {
        'Butter': ['milk'],
        'Water': [],
        'Eggs': ['eggs'],
        'Cream': ['soy'],  # a line with allergens of its own is never touched
        'Cheddar cheese': ['milk'],
        'Salt': [],
        'Coconut milk': [],
    }
