"""What the migrations build is what the models declare.

``baseline_001_full_schema`` created the whole core with not a single
foreign key, and the unique constraint on the quant table (since dropped)
existed only in the versions archive no fresh database replays. Later migrations added a
few constraints for their own new tables, so an instance that grew
through the chain and an instance that started from the baseline have
been two different databases: the fresh one does not cascade a delete
the models promise to cascade, and a guard built on ``IntegrityError``
never fires. The test databases are built from the models
(``create_all``), so no gate saw any of it.

This closes the gap and keeps it closed: migrate an empty database to
head, then let ``compare_metadata`` diff what the migrations built
against what the models declare. Anything the models promise and the
chain fails to build — a foreign key, the unique constraint, a column —
fails here. Module tables are out of scope: they come from module
migrations, which this chain does not run.
"""

from __future__ import annotations

import importlib

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.core.autogenerate_scope import schema_gaps
from app.core.db_isolation import isolated_db_url

pytestmark = pytest.mark.integration


def _registered_base():
    """``Base`` with every model module imported, so its metadata is complete."""
    importlib.import_module('app.core.template_models')
    importlib.import_module('app.models')
    from app.database import Base

    return Base


def test_what_migrations_build_is_what_the_models_declare(monkeypatch):
    metadata = _registered_base().metadata

    with isolated_db_url('schema') as url:
        monkeypatch.setenv('DATABASE_URL', url)
        command.upgrade(Config('alembic.ini'), 'head')

        engine = create_engine(url)

        with engine.connect() as conn:
            # Module tables are declared in metadata but built by module
            # migrations, which this core chain does not run — their add_table
            # entries, and the foreign keys anchored on them, are expected
            # noise. ``schema_gaps`` drops that (and the indexes migrations
            # build by hand); a missing foreign key on a core table surfaces
            # as an ``add_fk`` entry and fails.
            gaps = schema_gaps(conn, metadata)
        engine.dispose()

    assert not gaps, (
        'the migration chain builds a schema the models do not declare:\n'
        + '\n'.join(f'  - {op}' for op in gaps)
    )


#: Indexes whose migrated definition differs from the model's in a way that
#: changes no behaviour: the baseline built ``uq_partner_org_code`` without the
#: ``WHERE code IS NOT NULL`` predicate, and NULLs never collide in a unique
#: index anyway. Only this exact pair of definitions is waived: any other
#: predicate under the same name still fails.
_EQUIVALENT_DEFINITION_DRIFT = {
    'uq_partner_org_code': (
        'CREATE UNIQUE INDEX uq_partner_org_code ON public.partners'
        ' USING btree (organization_id, code)',
        'CREATE UNIQUE INDEX uq_partner_org_code ON public.partners'
        ' USING btree (organization_id, code) WHERE (code IS NOT NULL)',
    ),
}


def _index_definitions(url: str) -> dict[str, str]:
    """Every index in the database, by name, as Postgres itself prints it.

    ``compare_metadata`` matches an index by name and column list, so a
    migration that writes the columns in the other order or leaves out a
    ``DESC`` can still diff clean. The printed definition carries both.
    """
    engine = create_engine(url)
    with engine.connect() as conn:
        rows = conn.execute(
            text('SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = :s'),
            {'s': 'public'},
        ).all()
    engine.dispose()
    return dict(rows)


def test_the_migrated_indexes_are_the_ones_the_models_declare(monkeypatch):
    """Column order and sort direction of an index survive the migration chain.

    The test databases are built by ``create_all``, so the order and the
    ``DESC`` a model declares are there whatever the migration wrote. This
    builds both databases and prints every index of each: a migration that
    swaps two columns of a composite index, or drops its ``DESC``, leaves the
    two definitions different and fails here, on every core index at once.
    """
    metadata = _registered_base().metadata

    with isolated_db_url('migidx') as migrated_url:
        monkeypatch.setenv('DATABASE_URL', migrated_url)
        command.upgrade(Config('alembic.ini'), 'head')
        migrated = _index_definitions(migrated_url)

        with isolated_db_url('modelidx') as model_url:
            engine = create_engine(model_url)
            metadata.create_all(engine)
            engine.dispose()
            declared = _index_definitions(model_url)

    differing = [
        f'  - {name}\n      migrated: {migrated[name]}\n      declared: {declared[name]}'
        for name in sorted(migrated.keys() & declared.keys())
        if migrated[name] != declared[name]
        and _EQUIVALENT_DEFINITION_DRIFT.get(name) != (migrated[name], declared[name])
    ]
    assert not differing, (
        'an index the migrations build is not the index the models declare:\n'
        + '\n'.join(differing)
    )
    assert 'ix_audit_log_org_created_at_id' in migrated.keys() & declared.keys()


def test_a_column_type_that_drifted_is_a_diff(monkeypatch):
    """The type comparison has teeth: a JSONB column turned back to JSON shows.

    Type comparison is spelled out in the gate rather than left to the
    library default, and this pins that it is really on.
    """
    metadata = _registered_base().metadata

    with isolated_db_url('typedrift') as url:
        monkeypatch.setenv('DATABASE_URL', url)
        command.upgrade(Config('alembic.ini'), 'head')
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(
                text(
                    'ALTER TABLE storage_locations ALTER COLUMN warehouse_config '
                    'TYPE json USING warehouse_config::json'
                )
            )
        with engine.connect() as conn:
            diff = compare_metadata(
                MigrationContext.configure(conn, opts={'compare_type': True}),
                metadata,
            )
        engine.dispose()

    def _type_changes(ops):
        return [
            op
            for op in ops
            if isinstance(op, list)
            for entry in op
            if entry[0] == 'modify_type' and entry[3] == 'warehouse_config'
        ]

    assert _type_changes(diff), diff


def test_the_migrated_schema_enforces_what_the_models_promise(monkeypatch):
    """The cascade and the refusal, exercised on the migrated database.

    A fresh install used to keep the orphan: the journal row survived its
    organization, and an item could point at an organization that does
    not exist, because the foreign keys the models declare were words
    without a constraint behind them. This runs on the schema the
    migrations built — not on ``create_all``.
    """
    from uuid import uuid4

    from sqlalchemy import delete, insert, select

    from app.models.audit_log import AuditLog
    from app.models.organization import Organization
    from app.models.partner import Partner

    org_id = uuid4()
    with isolated_db_url('enforce') as url:
        monkeypatch.setenv('DATABASE_URL', url)
        command.upgrade(Config('alembic.ini'), 'head')
        engine = create_engine(url)

        journal_only_org = uuid4()  # never deleted: its journal is immutable
        with engine.begin() as conn:
            conn.execute(
                insert(Organization).values(
                    id=org_id, name=f'Enforced {uuid4().hex[:6]}'
                )
            )
            conn.execute(
                insert(Organization).values(
                    id=journal_only_org, name=f'Journaling {uuid4().hex[:6]}'
                )
            )
            conn.execute(
                insert(AuditLog).values(
                    organization_id=journal_only_org,
                    action='UPDATE',
                    target_type='item',
                    target_id=uuid4(),
                )
            )
            conn.execute(
                insert(Partner).values(
                    id=uuid4(),
                    organization_id=org_id,
                    name='Cascade Partner',
                    type='SUPPLIER',
                )
            )

        # A journal row naming an organization that does not exist is
        # refused by the foreign key the models declare.
        refused = False
        try:
            with engine.begin() as conn:
                conn.execute(
                    insert(AuditLog).values(
                        organization_id=uuid4(),  # no such organization
                        action='UPDATE',
                        target_type='item',
                        target_id=uuid4(),
                    )
                )
        except IntegrityError:
            refused = True

        # Deleting the organization takes its partners with it — the
        # CASCADE the models promise fires in the database. (The journal
        # deliberately does not: its immutability trigger outvotes the
        # cascade, so an organization with history refuses to go.)
        with engine.begin() as conn:
            conn.execute(delete(Organization).where(Organization.id == org_id))
        survivors = 0
        with engine.connect() as conn:
            survivors = conn.execute(
                select(Partner).where(Partner.organization_id == org_id)
            ).all()
        engine.dispose()

    assert refused, 'a journal row for a missing organization was kept'
    assert not survivors, 'the cascade the models promise did not fire'


def test_the_migrated_database_carries_the_trigram_indexes(monkeypatch):
    """The searches over text ride GIN indexes a squash from the models would lose.

    The previous flattening dropped them and nothing failed: every ILIKE
    search then read the whole table. They are not model objects — an index
    over ``gin_trgm_ops`` is not something a ``Column`` declares — so the
    baseline writes them by hand, and this asks the database a fresh install
    leaves behind.
    """
    from migrations.versions.baseline_002_full_schema import TRIGRAM_INDEXES
    from migrations.versions.listreads01_index_the_list_searches import (
        TRIGRAM_INDEXES as LIST_TRIGRAM_INDEXES,
    )

    with isolated_db_url('trgm') as url:
        monkeypatch.setenv('DATABASE_URL', url)
        command.upgrade(Config('alembic.ini'), 'head')
        engine = create_engine(url)
        with engine.connect() as conn:
            found = dict(
                conn.execute(
                    text(
                        'SELECT indexname, indexdef FROM pg_indexes '
                        "WHERE schemaname = 'public' "
                        "AND indexdef LIKE '%gin_trgm_ops%'"
                    )
                ).all()
            )
            extension = conn.execute(
                text("SELECT count(*) FROM pg_extension WHERE extname = 'pg_trgm'")
            ).scalar()
        engine.dispose()

    assert set(found) == {
        name for name, _table, _column in (*TRIGRAM_INDEXES, *LIST_TRIGRAM_INDEXES)
    }
    assert all('USING gin' in definition for definition in found.values())
    assert extension == 1, 'the pg_trgm extension the indexes need is missing'
