"""A module migration converts its own naive timestamp columns to ``timestamptz``.

A database that grew through a module's chain before it was flattened kept
``timestamp without time zone`` where the models declare
``DateTime(timezone=True)``. The API sent those values without an offset, the
browser read a UTC time as local, and one document showed its creation two
hours away from its approval request. Every module's chain carries a
``timestamps carry their zone`` revision that converts its tables through
``convert_naive_timestamps_to_utc``; these tests check that conversion on a
module chain, that the helper touches only the columns it is given, and that
``db doctor`` reports no drift on a database built from the models.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, create_engine, text

from app.core.db_isolation import isolated_db_url
from app.core.migration_doctor import column_type_drift
from app.core.migration_helpers import convert_naive_timestamps_to_utc
from app.core.module_migrations import run_module_migrations

pytestmark = pytest.mark.integration

_NAIVE = 'timestamp without time zone'
_AWARE = 'timestamp with time zone'


def _make_naive(engine: Engine, table: str, column: str) -> None:
    """Give the column the legacy type, keeping its UTC wall-clock values."""
    with engine.begin() as conn:
        conn.execute(
            text(
                f'ALTER TABLE {table} ALTER COLUMN {column} '
                f"TYPE timestamp USING {column} AT TIME ZONE 'UTC'"
            )
        )


def _data_type(engine: Engine, table: str, column: str) -> str:
    with engine.connect() as conn:
        return conn.execute(
            text(
                'SELECT data_type FROM information_schema.columns '
                'WHERE table_schema = current_schema() '
                'AND table_name = :table AND column_name = :column'
            ),
            {'table': table, 'column': column},
        ).scalar_one()


def test_a_module_migration_converts_its_own_tables(monkeypatch):
    with isolated_db_url('tzaware') as url:
        monkeypatch.setenv('DATABASE_URL', url)
        command.upgrade(Config('alembic.ini'), 'head')
        run_module_migrations(
            'warehouse', 'upgrade', db_url=url, revision='doc_cancel_trail01'
        )
        engine = create_engine(url)
        try:
            _make_naive(engine, 'documents', 'confirmed_at')
            before = _data_type(engine, 'documents', 'confirmed_at')
            run_module_migrations('warehouse', 'upgrade', db_url=url)
            after = _data_type(engine, 'documents', 'confirmed_at')
        finally:
            engine.dispose()

    assert (before, after) == (_NAIVE, _AWARE)


def _run_helper(conn, columns: dict[str, tuple[str, ...]]) -> list[tuple[str, str]]:
    with Operations.context(MigrationContext.configure(conn)):
        return convert_naive_timestamps_to_utc(columns)


def test_the_helper_touches_only_listed_naive_columns(engine, db_session):
    """An unlisted naive column, an aware one and a missing table are left as they are."""
    table = f'tz_scratch_{uuid4().hex[:8]}'
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(
                text(
                    f'CREATE TABLE {table} (listed timestamp, unlisted timestamp, '
                    'aware timestamptz)'
                )
            )
            conn.execute(
                text(
                    f"INSERT INTO {table} VALUES ('2026-10-09 22:27:05', "
                    "'2026-10-09 22:27:05', '2026-10-09 22:27:05+00')"
                )
            )
            conn.execute(text("SET LOCAL TimeZone = 'America/New_York'"))
            converted = _run_helper(
                conn, {table: ('listed', 'aware'), 'no_such_table': ('created_at',)}
            )
            again = _run_helper(conn, {table: ('listed', 'aware')})
            types = dict(
                conn.execute(
                    text(
                        'SELECT column_name, data_type FROM information_schema.columns '
                        'WHERE table_name = :table'
                    ),
                    {'table': table},
                ).all()
            )
            listed, aware = conn.execute(
                text(f'SELECT listed, aware FROM {table}')
            ).one()
        finally:
            trans.rollback()

    assert converted == [(table, 'listed')]
    assert again == []
    assert types == {'listed': _AWARE, 'unlisted': _NAIVE, 'aware': _AWARE}
    assert listed == aware


def test_the_type_check_sees_nothing_on_a_database_built_from_the_models(
    engine, db_session
):
    """No false alarms: the test database is ``create_all`` of the same models."""
    assert column_type_drift(engine) == []
