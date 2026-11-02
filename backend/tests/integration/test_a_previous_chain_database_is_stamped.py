"""The database the previous chain built is stamped, not replayed, and keeps its rows.

Before v0.11.0 the core chain was flattened into one baseline revision. An
installation that grew through the old chain carries a revision id this
checkout no longer knows, so ``alembic upgrade`` cannot even start on it: the
migration it would look up is gone. The upgrade path is a stamp — the schema
is already what the baseline creates, so only the recorded revision changes.

That is only safe if the two schemas really are the same, and the previous
flattening is the reason this is a test and not a paragraph. The dump in
``tests/fixtures/previous_head`` is the database the old chain left at its
last revision, with the demo rows in it; ``db stamp-baseline`` must accept it,
rewrite the revision, leave every row where it was, and leave a schema the
models still recognize once the module chains have run. The dump is frozen
at the previous chain, while module chains keep growing: a column a module
adds after it (the warehouse's ``documents.held_by``) is missing from the dump
and is its chain's to add, after the stamp, not a reason to refuse it.

A database that is *not* at that head must be refused, and for two different
reasons: a stamp over a missing column hides it until something reads it, and
an earlier revision can carry the same schema while missing a data-only one.
``docurl01`` rewrote stored notification links and changed no table, so the
schema cannot tell whether it ran; only the recorded revision can.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.cli.commands_db import LEGACY_CHAIN_BASELINE, LEGACY_CHAIN_PREVIOUS_HEAD
from app.core.autogenerate_scope import load_model_metadata, schema_gaps
from app.core.db_isolation import isolated_db_url

pytestmark = pytest.mark.integration

BACKEND = Path(__file__).resolve().parents[2]
PREVIOUS_CHAIN = (
    BACKEND / 'tests' / 'fixtures' / 'previous_head' / 'previous_chain_docvis01.sql.gz'
)
PREVIOUS_HEAD = LEGACY_CHAIN_PREVIOUS_HEAD
BASELINE = LEGACY_CHAIN_BASELINE
#: A revision of the previous chain that already widened ``label_pool``, so a
#: database recording it has exactly the baseline's schema while the link
#: rewrite of its sibling ``docurl01`` has not run.
_SAME_SCHEMA_SIBLING = 'poolcode01'

#: Enough tables that a stamp that quietly rebuilt something would show.
_COUNTED = ('items', 'stock_moves', 'stock_lots', 'audit_log', 'users', 'organizations')


def _restore(url: str) -> None:
    """Run the previous head's dump into the empty database at ``url``.

    The dump sets ``search_path`` to empty for its session, so it gets a
    connection of its own. A raw cursor and no parameters: the rows carry
    ``%``.
    """
    sql = gzip.decompress(PREVIOUS_CHAIN.read_bytes())
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


def _counts(url: str) -> dict[str, int]:
    engine = create_engine(url)
    with engine.connect() as connection:
        counts = {
            table: connection.execute(text(f'SELECT count(*) FROM {table}')).scalar()
            for table in _COUNTED
        }
    engine.dispose()
    return counts


def _revision(url: str) -> str:
    engine = create_engine(url)
    with engine.connect() as connection:
        revision = connection.execute(
            text('SELECT version_num FROM alembic_version')
        ).scalar()
    engine.dispose()
    return revision


def _stamp(url: str, monkeypatch) -> None:
    from app.cli.commands_db import stamp_baseline

    monkeypatch.setenv('DATABASE_URL', url)
    monkeypatch.delenv('MIGRATION_DATABASE_URL', raising=False)
    stamp_baseline()


def test_the_previous_head_stamps_onto_the_baseline(monkeypatch):
    with isolated_db_url('stamp') as url:
        _restore(url)
        assert _revision(url) == PREVIOUS_HEAD
        before = _counts(url)
        assert before['items'], 'the dump restored no items'

        _stamp(url, monkeypatch)

        assert _revision(url) == BASELINE
        assert _counts(url) == before, 'the stamp touched the data'

        # The rest of the upgrade: the core chain is at head, and the module
        # chains run what they grew since the previous chain.
        from app.cli.commands_db import upgrade_modules

        command.upgrade(Config('alembic.ini'), 'head')
        upgrade_modules()
        assert _counts(url) == before

        engine = create_engine(url)
        with engine.connect() as connection:
            gaps = schema_gaps(connection, load_model_metadata())
        engine.dispose()
        assert not gaps, (
            'a stamped and upgraded database is not the schema the models '
            'declare:\n' + '\n'.join(f'  - {op}' for op in gaps)
        )


@pytest.mark.parametrize(
    ('table', 'column'),
    [
        # A module's table that its chain still extends after the stamp: the
        # columns its revisions add are expected missing, this one is not.
        ('documents', 'notes'),
        ('items', 'description'),
    ],
)
def test_a_previous_head_that_lost_a_column_is_refused(
    monkeypatch, capsys, table, column
):
    """No chain run after the stamp brings back a column the database lost."""
    import typer

    with isolated_db_url('stamplost') as url:
        _restore(url)
        engine = create_engine(url)
        with engine.begin() as connection:
            connection.execute(text(f'ALTER TABLE {table} DROP COLUMN {column}'))
        engine.dispose()

        with pytest.raises(typer.Exit) as refusal:
            _stamp(url, monkeypatch)

        assert refusal.value.exit_code == 1
        assert _revision(url) == PREVIOUS_HEAD, (
            'a refused stamp still wrote the revision'
        )
        refused = capsys.readouterr().out
        assert f"'{table}', Column('{column}'" in refused, refused


def test_a_lost_column_a_pending_revision_only_alters_is_refused(monkeypatch, capsys):
    """Altering a column the database lost does not bring it back.

    The maker chain's ``015_default_result_margin`` only changes the default
    of ``reference_direction``; with the chain recorded one revision short,
    that revision is pending, and the stamp must still see the column gone.
    """
    import typer

    with isolated_db_url('stampalter') as url:
        _restore(url)
        engine = create_engine(url)
        with engine.begin() as connection:
            connection.execute(
                text(
                    'UPDATE alembic_version_maker SET version_num = '
                    "'014_add_line_shortfall'"
                )
            )
            connection.execute(
                text(
                    'ALTER TABLE maker_module_settings DROP COLUMN reference_direction'
                )
            )
        engine.dispose()

        with pytest.raises(typer.Exit) as refusal:
            _stamp(url, monkeypatch)

        assert refusal.value.exit_code == 1
        assert _revision(url) == PREVIOUS_HEAD
        refused = capsys.readouterr().out
        assert "Column('reference_direction'" in refused, refused


def test_a_database_that_is_not_at_that_head_is_refused(monkeypatch):
    import typer

    with isolated_db_url('stampdrift') as url:
        monkeypatch.setenv('DATABASE_URL', url)
        command.upgrade(Config('alembic.ini'), 'head')

        engine = create_engine(url)
        with engine.begin() as connection:
            connection.execute(
                text('ALTER TABLE items ADD COLUMN not_in_the_models integer')
            )
            connection.execute(
                text('UPDATE alembic_version SET version_num = :r'),
                {'r': PREVIOUS_HEAD},
            )
        engine.dispose()

        with pytest.raises(typer.Exit) as refusal:
            _stamp(url, monkeypatch)

        assert refusal.value.exit_code == 1
        assert _revision(url) == PREVIOUS_HEAD, (
            'a refused stamp still wrote the revision'
        )


def test_a_database_before_the_last_revision_is_refused(monkeypatch):
    """The schema alone cannot see a data-only revision.

    ``poolcode01`` widened ``label_pool.short_code`` and its sibling
    ``docurl01`` rewrote the stored notification links. A database that
    records the first has exactly the baseline's schema while the second has
    not run; stamping it would keep the old links for good, and only the
    recorded revision tells the two apart.
    """
    import typer

    with isolated_db_url('stampearlier') as url:
        _restore(url)
        engine = create_engine(url)
        with engine.begin() as connection:
            connection.execute(
                text('UPDATE alembic_version SET version_num = :r'),
                {'r': _SAME_SCHEMA_SIBLING},
            )
        engine.dispose()

        with pytest.raises(typer.Exit) as refusal:
            _stamp(url, monkeypatch)

        assert refusal.value.exit_code == 1
        assert _revision(url) == _SAME_SCHEMA_SIBLING, (
            'a refused stamp still wrote the revision'
        )
