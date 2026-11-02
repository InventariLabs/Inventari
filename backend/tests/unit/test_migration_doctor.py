"""Classification rules of the migration doctor, without a database.

The doctor decides whether a deploy proceeds, so both directions matter. It must
catch the state that once crash-looped it — schema ahead of the version table,
which crash-looped the backend — and it must stay quiet on the states that look
similar but are routine: an empty database (every fresh install), a version
behind head (every normal deploy), and baseline leftovers that
``db upgrade-modules`` already reconciles on its own.
"""

from pathlib import Path

import pytest

from app.core.architecture_lint._quality_checks import _collect_module_tablenames
from app.core.migration_doctor import (
    DRIFT_STATUSES,
    RevisionDDL,
    SchemaState,
    diagnose_module,
    has_drift,
    ordered_revisions,
    revision_changes,
    revision_ddl,
    suggest_stamp_revision,
    tables_created_through,
)
from app.core.module_migrations import (
    MODULES_ROOT,
    discover_modules_with_migrations,
    get_version_table_name,
)

# Single-revision chain creating exactly one table — the simplest module the
# repo ships, and the one the CLI was smoke-tested against.
SIMPLE_MODULE = 'example_widgets'
SIMPLE_TABLE = 'example_widgets'
SIMPLE_HEAD = '001_initial'

EMPTY = SchemaState()


def _schema(*tables: str, columns: tuple[str, str] | None = None) -> SchemaState:
    return SchemaState(frozenset(tables), frozenset([columns] if columns else []))


def _one_table_of(module: str) -> str:
    """One table from a module that owns several — a deliberately partial schema."""
    tables = sorted(_collect_module_tablenames(MODULES_ROOT / module))
    assert len(tables) > 1, f'{module} needs >1 table for a partial-schema fixture'
    return tables[0]


def _mid_chain_fixture() -> tuple[str, str, SchemaState, SchemaState]:
    """A real chain where revision N+1 adds DDL the database can be asked about.

    Returns the module, the revision to pretend is stamped, the schema as it
    looks with only that revision applied, and the same schema plus the next
    revision's DDL — the drifted state.
    """
    for name in discover_modules_with_migrations():
        revisions = ordered_revisions(name)
        for index in range(len(revisions) - 1):
            ahead = revision_ddl(revisions[index + 1].path)
            if not ahead:
                continue
            applied = RevisionDDL()
            for rev in revisions[: index + 1]:
                applied = applied | revision_ddl(rev.path)
            clean = SchemaState(applied.tables, applied.columns)
            drifted = SchemaState(
                applied.tables | ahead.tables, applied.columns | ahead.columns
            )
            return name, revisions[index].revision, clean, drifted
    pytest.fail('no module has a revision chain that adds inspectable DDL')


@pytest.mark.unit
class TestDiscovery:
    def test_finds_modules_with_migrations(self):
        modules = discover_modules_with_migrations()

        assert SIMPLE_MODULE in modules
        assert modules == sorted(modules)

    def test_skips_a_versions_dir_holding_only_init(self, tmp_path):
        versions = tmp_path / 'mod' / 'migrations' / 'versions'
        versions.mkdir(parents=True)
        (versions / '__init__.py').touch()

        assert discover_modules_with_migrations(tmp_path) == []

    def test_returns_empty_for_a_missing_root(self, tmp_path):
        assert discover_modules_with_migrations(tmp_path / 'nope') == []


@pytest.mark.unit
class TestFreshInstall:
    """B3's mandatory edge case: an empty database must not block the boot."""

    def test_no_version_row_and_no_tables_is_fresh(self):
        diagnosis = diagnose_module(SIMPLE_MODULE, EMPTY, frozenset())

        assert diagnosis.status == 'fresh'
        assert not diagnosis.is_drift

    def test_an_entirely_empty_database_has_no_drift(self):
        diagnoses = [
            diagnose_module(name, EMPTY, frozenset())
            for name in discover_modules_with_migrations()
        ]

        assert diagnoses, 'no modules discovered — wrong working directory?'
        assert not has_drift(diagnoses)
        assert {d.status for d in diagnoses} == {'fresh'}


@pytest.mark.unit
class TestBaselineLeftovers:
    """`db upgrade-modules` stamps this case itself — flagging it blocks deploys."""

    def test_tables_without_a_version_row_is_reconcilable(self):
        diagnosis = diagnose_module(SIMPLE_MODULE, _schema(SIMPLE_TABLE), frozenset())

        assert diagnosis.status == 'reconcilable'
        assert not diagnosis.is_drift
        assert diagnosis.fix_command is None


@pytest.mark.unit
class TestDrift:
    def test_pending_ddl_that_already_exists_is_drift(self):
        """The incident: version mid-chain, a later revision's DDL already applied."""
        module, applied, _clean, drifted = _mid_chain_fixture()

        diagnosis = diagnose_module(module, drifted, frozenset({applied}))

        assert diagnosis.status == 'schema_ahead'
        assert diagnosis.is_drift
        assert diagnosis.fix_command

    def test_a_partially_created_schema_is_drift(self):
        """Half the tables present: neither a fresh install nor a clean baseline."""
        diagnosis = diagnose_module(
            'warehouse', _schema(_one_table_of('warehouse')), frozenset()
        )

        assert diagnosis.status == 'partial_schema'
        assert diagnosis.is_drift

    def test_a_revision_the_code_does_not_know_is_drift(self):
        """Deploying older code onto a newer database."""
        diagnosis = diagnose_module(
            SIMPLE_MODULE, _schema(SIMPLE_TABLE), frozenset({'999_from_the_future'})
        )

        assert diagnosis.status == 'unknown_revision'
        assert diagnosis.is_drift

    def test_every_drift_status_carries_a_fix_command(self):
        drifting = [
            diagnose_module(
                'warehouse', _schema(_one_table_of('warehouse')), frozenset()
            ),
            diagnose_module(SIMPLE_MODULE, _schema(SIMPLE_TABLE), frozenset({'nope'})),
        ]

        assert {d.status for d in drifting} <= DRIFT_STATUSES
        for diagnosis in drifting:
            assert diagnosis.fix_command


@pytest.mark.unit
class TestHealthyStates:
    def test_at_head_is_ok(self):
        diagnosis = diagnose_module(
            SIMPLE_MODULE, _schema(SIMPLE_TABLE), frozenset({SIMPLE_HEAD})
        )

        assert diagnosis.status == 'ok'
        assert not diagnosis.is_drift

    def test_behind_head_without_the_ddl_is_pending(self):
        """The normal state right before a deploy applies its migrations."""
        module, applied, clean, _drifted = _mid_chain_fixture()

        diagnosis = diagnose_module(module, clean, frozenset({applied}))

        assert diagnosis.status == 'pending'
        assert not diagnosis.is_drift

    def test_a_pending_drop_only_revision_is_not_drift(self):
        """The boot loop, at the diagnosis level: the database still has
        the column the pending migration drops — the normal pre-upgrade state,
        which the doctor misread as schema_ahead because it also scanned
        ``downgrade()``."""
        revisions = ordered_revisions('warehouse')
        names = [rev.revision for rev in revisions]
        assert 'doc_require_price01' in names and 'doc_drop_allowed_fields01' in names

        applied = RevisionDDL()
        for rev in revisions[: names.index('doc_require_price01') + 1]:
            applied = applied | revision_ddl(rev.path)
        schema = SchemaState(
            applied.tables,
            applied.columns | {('document_type_configs', 'allowed_fields')},
        )

        diagnosis = diagnose_module(
            'warehouse', schema, frozenset({'doc_require_price01'})
        )

        assert diagnosis.status == 'pending'
        assert not diagnosis.is_drift


@pytest.mark.unit
class TestRevisionDDL:
    def test_reads_create_table_and_add_column_literals(self, tmp_path):
        migration = tmp_path / 'rev.py'
        migration.write_text(
            'def upgrade():\n'
            "    op.create_table('widgets')\n"
            "    op.add_column('gadgets', sa.Column('size', sa.Integer()))\n",
            encoding='utf-8',
        )

        ddl = revision_ddl(str(migration))

        assert ddl.tables == frozenset({'widgets'})
        assert ddl.columns == frozenset({('gadgets', 'size')})

    def test_ignores_non_literal_names(self, tmp_path):
        """Better to under-report than to block a deploy over an invented table."""
        migration = tmp_path / 'rev.py'
        migration.write_text(
            'def upgrade():\n'
            '    op.create_table(name)\n'
            "    op.add_column('gadgets', sa.Column(col))\n",
            encoding='utf-8',
        )

        assert not revision_ddl(str(migration))

    def test_ignores_ddl_in_downgrade(self, tmp_path):
        """The boot loop: a drop-column migration whose downgrade re-adds
        the column was read as "pending DDL already exists" and blocked the boot."""
        migration = tmp_path / 'rev.py'
        migration.write_text(
            'def upgrade():\n'
            "    op.drop_column('gadgets', 'size')\n"
            '\n'
            'def downgrade():\n'
            "    op.add_column('gadgets', sa.Column('size', sa.Integer()))\n"
            "    op.create_table('widgets')\n",
            encoding='utf-8',
        )

        assert not revision_ddl(str(migration))

    def test_reads_upgrade_ddl_next_to_a_downgrade(self, tmp_path):
        migration = tmp_path / 'rev.py'
        migration.write_text(
            'def upgrade():\n'
            "    op.create_table('widgets')\n"
            '\n'
            'def downgrade():\n'
            "    op.drop_table('widgets')\n"
            "    op.add_column('gadgets', sa.Column('size', sa.Integer()))\n",
            encoding='utf-8',
        )

        ddl = revision_ddl(str(migration))

        assert ddl.tables == frozenset({'widgets'})
        assert not ddl.columns

    def test_chain_up_to_head_covers_the_module_tables(self):
        assert tables_created_through(SIMPLE_MODULE, SIMPLE_HEAD) == {SIMPLE_TABLE}

    def test_every_shipped_migration_parses(self):
        """AST reading must not choke on any migration we ship."""
        for module in discover_modules_with_migrations():
            versions = MODULES_ROOT / module / 'migrations' / 'versions'
            for migration in sorted(versions.glob('*.py')):
                if migration.name == '__init__.py':
                    continue
                revision_ddl(str(migration))  # must not raise


@pytest.mark.unit
class TestRevisionChanges:
    """What ``db stamp-baseline`` sets aside as a pending module revision's work."""

    def test_reads_columns_dropped_and_altered_as_well_as_added(self, tmp_path):
        migration = tmp_path / 'rev.py'
        migration.write_text(
            'def upgrade():\n'
            "    op.add_column('gadgets', sa.Column('size', sa.Integer()))\n"
            "    op.drop_column('gadgets', 'colour')\n"
            "    op.alter_column('gadgets', 'name', nullable=False)\n"
            "    op.alter_column('gadgets', column, nullable=False)\n"
            "    op.create_index('ix_gadgets_size', 'gadgets', ['size'])\n"
            "    op.create_foreign_key('fk_gadgets_owner', 'gadgets', 'owners')\n",
            encoding='utf-8',
        )

        changes = revision_changes(str(migration))

        assert changes.added == frozenset({('gadgets', 'size')})
        assert changes.dropped == frozenset({('gadgets', 'colour')})
        assert changes.altered == frozenset({('gadgets', 'name')})
        assert changes.names == frozenset({'ix_gadgets_size', 'fk_gadgets_owner'})

    def test_reads_the_sql_a_migration_executes(self, tmp_path):
        """``IF [NOT] EXISTS`` is only written as SQL, and the api keys use it."""
        migration = tmp_path / 'rev.py'
        migration.write_text(
            'def upgrade():\n'
            "    op.execute(sa.text('ALTER TABLE gadgets ADD COLUMN IF NOT EXISTS "
            "size JSONB'))\n"
            '    op.execute(\n'
            '        \'ALTER TABLE public."gadgets" DROP COLUMN IF EXISTS colour, \'\n'
            "        'ALTER COLUMN name SET NOT NULL, ADD CONSTRAINT ck CHECK (true)'\n"
            '    )\n'
            "    op.execute('CREATE INDEX IF NOT EXISTS ix_gadgets_size ON gadgets (size)')\n"
            "    op.execute('UPDATE gadgets SET size = 1')\n",
            encoding='utf-8',
        )

        changes = revision_changes(str(migration))

        assert changes.added == frozenset({('gadgets', 'size')})
        assert changes.dropped == frozenset({('gadgets', 'colour')})
        assert changes.altered == frozenset({('gadgets', 'name')})
        assert changes.names == frozenset({'ix_gadgets_size'})

    def test_ignores_downgrade_and_a_file_without_upgrade(self, tmp_path):
        migration = tmp_path / 'rev.py'
        migration.write_text(
            "def downgrade():\n    op.drop_column('gadgets', 'size')\n",
            encoding='utf-8',
        )

        changes = revision_changes(str(migration))

        assert not changes.columns
        assert not changes.names


@pytest.mark.unit
class TestStampSuggestion:
    def test_suggests_the_revision_whose_ddl_is_present(self):
        assert suggest_stamp_revision(SIMPLE_MODULE, _schema(SIMPLE_TABLE)) == (
            SIMPLE_HEAD
        )

    def test_suggests_nothing_when_no_ddl_exists(self):
        assert suggest_stamp_revision(SIMPLE_MODULE, EMPTY) is None


@pytest.mark.unit
class TestVersionTableNaming:
    def test_every_env_py_writes_the_table_the_doctor_reads(self):
        """A mismatch here makes the doctor read a table nobody ever writes."""
        for module in discover_modules_with_migrations():
            env_py = Path(MODULES_ROOT / module / 'migrations' / 'env.py')
            # Quote style varies across modules; the identifiers do not.
            source = env_py.read_text(encoding='utf-8').replace('"', "'")

            assert f"MODULE_NAME = '{module}'" in source, env_py
            assert "VERSION_TABLE = f'alembic_version_{MODULE_NAME}'" in source, env_py
            assert get_version_table_name(module) == f'alembic_version_{module}'
