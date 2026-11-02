"""Every released database upgrades to head, with its rows in it.

The other migration tests start from an empty database, and no
installation is one. A backfill that assumes a column is still empty, or
a constraint added over rows that break it, passes there and stops the
first boot of somebody who used the release. So each release is cut with
a snapshot of the database it leaves on disk — its schema, the rows the
first run writes and the demo seed — in ``tests/fixtures/release_databases``
(``make release-db-snapshot``), and here every one of them is restored,
upgraded to head, core and modules, and compared with what the models
declare.
"""

from __future__ import annotations

import gzip
import tomllib
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.core.autogenerate_scope import include_object, load_model_metadata
from app.core.db_isolation import isolated_db_url

pytestmark = pytest.mark.integration

BACKEND = Path(__file__).resolve().parents[2]
SNAPSHOTS = BACKEND / 'tests' / 'fixtures' / 'release_databases'


def _released_versions() -> list[str]:
    return sorted(
        path.name.removesuffix('.sql.gz').removeprefix('v')
        for path in SNAPSHOTS.glob('v*.sql.gz')
    )


def _restore(url: str, version: str) -> None:
    """Run the release's dump into the empty database at ``url``.

    The dump sets ``search_path`` to empty for the session it runs in, so
    it gets a connection of its own that is closed afterwards. A raw cursor
    and no parameters, because the rows are full of ``%``.
    """
    sql = gzip.decompress((SNAPSHOTS / f'v{version}.sql.gz').read_bytes())
    engine = create_engine(url)
    try:
        connection = engine.raw_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql.decode())
            connection.commit()
        finally:
            connection.close()
    finally:
        engine.dispose()


def test_the_current_release_has_its_snapshot():
    """A release is not cut without the database it leaves behind."""
    pyproject = tomllib.loads((BACKEND / 'pyproject.toml').read_text())
    assert pyproject['project']['version'] in _released_versions(), (
        f'no tests/fixtures/release_databases/v{pyproject["project"]["version"]}'
        '.sql.gz: cut it on the release commit with `make release-db-snapshot`'
    )


@pytest.mark.parametrize('version', _released_versions())
def test_a_released_database_upgrades_to_head(version, monkeypatch):
    from app.cli.commands_db import upgrade_modules

    metadata = load_model_metadata()

    with isolated_db_url('release') as url:
        _restore(url, version)
        engine = create_engine(url)
        with engine.connect() as conn:
            restored_items = conn.execute(text('SELECT count(*) FROM items')).scalar()

        monkeypatch.setenv('DATABASE_URL', url)
        command.upgrade(Config('alembic.ini'), 'head')
        upgrade_modules()

        migrated_tables = set(inspect(engine).get_table_names())
        with engine.connect() as conn:
            upgraded_items = conn.execute(text('SELECT count(*) FROM items')).scalar()
            gaps = compare_metadata(
                MigrationContext.configure(
                    conn,
                    opts={'include_object': include_object, 'compare_type': True},
                ),
                metadata,
            )
        engine.dispose()

    assert restored_items, f'the v{version} snapshot restored no items'
    assert upgraded_items == restored_items, 'the upgrade lost items'
    assert {'alembic_version', *metadata.tables} <= migrated_tables
    assert not gaps, (
        f'v{version} upgraded to a schema the models do not declare:\n'
        + '\n'.join(f'  - {op}' for op in gaps)
    )
