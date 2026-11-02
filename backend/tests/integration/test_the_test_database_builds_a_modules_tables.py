"""The test database builds a community module's tables, and clears them.

A module's tables live on ``ModuleModelBase.metadata``, a metadata of its own
that ``Base.metadata.create_all`` never reaches. ``_provision_worker_db`` runs
the second ``create_all`` and ``clearable_names`` walks the second metadata, and
until this file nothing failed when either line went: the module's tests died
with ``relation "..." does not exist`` only the day somebody staged a real
package and ran them. A real package cannot be staged here (the guardian keeps
``app/modules`` read-only for the run), so a throwaway table stands in for it.

Provisioning runs against a scratch database of its own: it drops the schema it
is given, and the worker's database is the one every other test is standing on.
"""

from __future__ import annotations

import importlib
import uuid

import pytest
from sqlalchemy import Column, Integer, String, Table, create_engine, text

from app.core.contracts import ModuleModelBase
from tests import _db_hygiene as hygiene

pytestmark = pytest.mark.integration

PROBE_TABLE = 'zz_module_table_probe'


@pytest.fixture
def probe_table():
    """A table registered on the module metadata, gone from it afterwards."""
    table = Table(
        PROBE_TABLE,
        ModuleModelBase.metadata,
        Column('id', Integer, primary_key=True),
        Column('label', String(20)),
    )
    try:
        yield table
    finally:
        ModuleModelBase.metadata.remove(table)


@pytest.fixture
def scratch_engine(monkeypatch):
    """An empty database to provision, with the worker's bookkeeping put back."""
    suite = importlib.import_module('conftest')
    name = f'{suite.DB_NAME}_modtables_{uuid.uuid4().hex[:8]}'
    admin = create_engine(
        f'postgresql://{suite.DB_USER}:{suite.DB_PASSWORD}@{suite.DB_HOST}:'
        f'{suite.DB_PORT}/postgres',
        isolation_level='AUTOCOMMIT',
    )
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE {name}'))
    engine = create_engine(
        f'postgresql://{suite.DB_USER}:{suite.DB_PASSWORD}@{suite.DB_HOST}:'
        f'{suite.DB_PORT}/{name}'
    )
    # Provisioning resets and refills the hygiene globals and flips the
    # once-per-worker flag; monkeypatch hands every one of them back.
    monkeypatch.setattr(suite, '_worker_db_ready', False)
    monkeypatch.setattr(suite, 'create_test_db_if_not_exists', lambda: None)
    for attribute in ('_ddl_baseline', '_seed_xid', '_may_skip_constraints'):
        monkeypatch.setattr(hygiene, attribute, getattr(hygiene, attribute))
    try:
        yield suite, engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE {name} WITH (FORCE)'))
        admin.dispose()


def test_provisioning_builds_a_table_on_the_module_metadata(
    scratch_engine, probe_table
):
    suite, engine = scratch_engine

    suite._provision_worker_db(engine)

    with engine.connect() as conn:
        present = {
            row[0]
            for row in conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
        }
    assert PROBE_TABLE in present


def test_a_row_in_a_module_table_is_cleared_between_tests(scratch_engine, probe_table):
    suite, engine = scratch_engine
    suite._provision_worker_db(engine)

    with engine.connect() as conn:
        conn.execute(text(f"INSERT INTO {PROBE_TABLE} (label) VALUES ('left behind')"))
        conn.commit()
        assert PROBE_TABLE in hygiene.dirty_tables(conn)

        assert hygiene.restore_pristine(conn) is True
        conn.commit()

        assert conn.execute(text(f'SELECT count(*) FROM {PROBE_TABLE}')).scalar() == 0
        assert PROBE_TABLE not in hygiene.dirty_tables(conn)


def test_the_clearing_walk_names_the_module_table_after_the_core_tables(probe_table):
    names = hygiene.clearable_names({PROBE_TABLE, 'organizations'})

    assert names == ('organizations', PROBE_TABLE)
