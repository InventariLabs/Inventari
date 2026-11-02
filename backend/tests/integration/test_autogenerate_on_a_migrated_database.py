"""On a database ``db upgrade`` built, autogenerate has nothing to propose.

``make db-migrate`` runs ``alembic revision --autogenerate``, and on a fresh
install it wrote a revision that dropped 31 objects: the version table of
every module, a core table whose model nothing imported, and the indexes the
migrations build by hand. The contributor guide then said to apply it. This
builds the database the way ``db upgrade`` does - the core chain, then every
module chain - and asks the question ``env.py`` asks, with ``env.py``'s own
metadata and filter.
"""

from __future__ import annotations

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Column, Integer, MetaData, create_engine

from app.core.autogenerate_scope import include_object, load_model_metadata
from app.core.db_isolation import isolated_db_url

pytestmark = pytest.mark.integration


@pytest.fixture
def migrated_url(monkeypatch):
    """A database at head, core and modules, built by the ``db upgrade`` command."""
    from app.cli.commands_db import upgrade

    with isolated_db_url('autogen') as url:
        monkeypatch.setenv('DATABASE_URL', url)
        monkeypatch.delenv('MIGRATION_DATABASE_URL', raising=False)
        upgrade('head')
        yield url


def _diff(url: str, metadata: MetaData) -> list:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            context = MigrationContext.configure(
                conn,
                opts={'include_object': include_object, 'compare_type': True},
            )
            return compare_metadata(context, metadata)
    finally:
        engine.dispose()


def _copy(metadata: MetaData) -> MetaData:
    copy = MetaData()
    for table in metadata.sorted_tables:
        table.to_metadata(copy)
    return copy


def test_a_migrated_database_leaves_autogenerate_nothing_to_do(migrated_url):
    diff = _diff(migrated_url, load_model_metadata())

    assert not diff, (
        'autogenerate proposes changes on a database the migrations built:\n'
        + '\n'.join(f'  - {op}' for op in diff)
    )


def test_a_real_model_change_still_reaches_the_revision(migrated_url):
    """The filter hides what migrations own, not what a model changes."""
    metadata = _copy(load_model_metadata())
    metadata.tables['items'].append_column(Column('probe_column', Integer))
    metadata.remove(metadata.tables['ai_usage_logs'])

    # Column modifications come as nested lists; the two asked for are tuples.
    kinds = {
        (op[0], op[-1].name)
        for op in _diff(migrated_url, metadata)
        if isinstance(op, tuple)
    }

    assert ('add_column', 'probe_column') in kinds
    assert ('remove_table', 'ai_usage_logs') in kinds


def test_no_model_change_writes_no_revision_file(migrated_url, tmp_path):
    """An empty autogenerate is refused, not written as a file to apply."""
    config = Config('alembic.ini')
    real_versions = config.get_main_option('script_location') + '/versions'
    config.set_main_option('version_locations', f'{real_versions} {tmp_path}')

    written = command.revision(
        config, message='nothing', autogenerate=True, version_path=str(tmp_path)
    )

    assert not written
    assert not list(tmp_path.iterdir())
