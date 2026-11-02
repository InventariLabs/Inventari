"""The table-name helper sees community modules, and its consumers act on it.

A community module may not import ``app.database`` (the safety validator
forbids it), so every community model sits on a ``DeclarativeBase`` of its
own. The table walk used to skip exactly those files — non-Core bases are
not tracked by core Alembic — and reported zero tables for the one kind of
module the migration checks exist for: the gate read green while the module
had tables and no migrations.
"""

from __future__ import annotations

from pathlib import Path

from app.core.architecture_lint._quality_checks_migrations import (
    _check_module_migrations_exist,
    _collect_module_tablenames,
)

COMMUNITY_MODEL = """from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class CommunityBase(DeclarativeBase):
    pass


class Claim(CommunityBase):
    __tablename__ = 'inv2039demo_claims'

    id: Mapped[int] = mapped_column(primary_key=True)
"""

COMMUNITY_MIGRATION = '''"""create claims"""

revision = '001_initial'
down_revision = None


def upgrade() -> None:
    op.create_table(
        'inv2039demo_claims',
        sa.Column('id', sa.Integer(), primary_key=True),
    )
'''

SEPARATE_DB_MODULE_PY = """from app.core.db_facade import products_engine
"""


def _write_community_module(
    root: Path, *, with_migration: bool = False, with_separate_db: bool = False
) -> Path:
    module = root / 'inv2039demo'
    (module / 'migrations' / 'versions').mkdir(parents=True, exist_ok=True)
    (module / 'models.py').write_text(COMMUNITY_MODEL, encoding='utf-8')
    if with_migration:
        (module / 'migrations' / 'versions' / '001_initial.py').write_text(
            COMMUNITY_MIGRATION, encoding='utf-8'
        )
    if with_separate_db:
        (module / 'module.py').write_text(SEPARATE_DB_MODULE_PY, encoding='utf-8')
    return module


def _on_separate_database(module_dir: Path) -> bool:
    """Whether the module has a class that inherits the separate-database base."""
    from app.core.architecture_lint._quality_checks_migrations import (
        _separate_database_classes,
    )

    return any(True for _ in _separate_database_classes(module_dir))


class TestCollectModuleTablenames:
    def test_counts_own_base_tables_of_a_community_module(self, tmp_path: Path):
        module = _write_community_module(tmp_path)

        assert _collect_module_tablenames(module) == {'inv2039demo_claims'}

    def test_counts_tables_named_only_in_migrations(self, tmp_path: Path):
        module = _write_community_module(tmp_path, with_migration=True)
        (module / 'migrations' / 'versions' / '002_audit.py').write_text(
            "revision = '002'\ndown_revision = '001'\n\n"
            'def upgrade() -> None:\n'
            "    op.create_table('inv2039demo_audit', sa.Column('id', sa.Integer()))\n",
            encoding='utf-8',
        )

        tables = _collect_module_tablenames(module)
        assert 'inv2039demo_audit' in tables

    def test_counts_tables_created_by_the_if_absent_helper(self, tmp_path: Path):
        """The uninstall flow names the module's tables with this walk and
        asks the database which of them survived the drop-hook — a table
        the migration creates through ``create_table_if_absent`` (how this
        repository's own migrations create tables) but the walk never
        named stayed in the database under a summary that said every
        table and its data were dropped."""
        module = _write_community_module(tmp_path, with_migration=True)
        (module / 'migrations' / 'versions' / '002_extra.py').write_text(
            'from alembic import op\n'
            'import sqlalchemy as sa\n'
            'from app.core.migration_helpers import create_table_if_absent\n\n\n'
            'def upgrade() -> None:\n'
            "    op.create_table('inv2039demo_audit', sa.Column('id', sa.Integer()))\n"
            '    create_table_if_absent(\n'
            "        'inv2039demo_extra',\n"
            "        sa.Column('id', sa.Integer(), primary_key=True),\n"
            '    )\n',
            encoding='utf-8',
        )

        tables = _collect_module_tablenames(module)
        assert 'inv2039demo_audit' in tables
        assert 'inv2039demo_extra' in tables

    def test_a_table_the_history_retires_leaves_the_owned_set(self, tmp_path: Path):
        """A table created in one revision and dropped by a later one is
        not the module's table at head — the set answers ``owners``, not
        ``ever named``. The drop may carry the name through a module-level
        constant, the way migration files reuse one name through upgrade
        and downgrade."""
        module = _write_community_module(tmp_path, with_migration=True)
        (module / 'migrations' / 'versions' / '002_era.py').write_text(
            'from alembic import op\n'
            'import sqlalchemy as sa\n\n'
            "_ERA = 'inv2039demo_era'\n\n\n"
            'def upgrade() -> None:\n'
            "    op.create_table(_ERA, sa.Column('id', sa.Integer()))\n",
            encoding='utf-8',
        )
        (module / 'migrations' / 'versions' / '003_retire_era.py').write_text(
            'from alembic import op\n\n\n'
            'def upgrade() -> None:\n'
            "    op.drop_table('inv2039demo_era')\n",
            encoding='utf-8',
        )

        tables = _collect_module_tablenames(module)
        assert 'inv2039demo_era' not in tables
        assert 'inv2039demo_claims' in tables

    def test_a_separate_database_module_stays_out(self, tmp_path: Path):
        """Own-Base tables on another database (nutrition's products db)
        are runtime-managed there and core Alembic will never track them.
        What makes a module separate-database is its models INHERITING the
        separate-database base — a table joins that base's metadata only by
        inheritance — never the mere presence of an import."""
        module = _write_community_module(tmp_path)
        (module / 'module.py').write_text(
            'from app.modules.nutrition.models import OFFBase\n\n\n'
            'class Claim(OFFBase):\n'
            "    __tablename__ = 'inv2039demo_claims'\n",
            encoding='utf-8',
        )

        assert _collect_module_tablenames(module) == set()

    def test_the_products_engine_import_alone_blinds_nobody(self, tmp_path: Path):
        """The old contract let ONE line — ``from app.core.db_facade import
        products_engine`` — switch the whole module off, so a module with
        tables and no migrations could opt out of this gate on demand. The
        import says nothing about where any table lives; the tables stay
        visible and the gate keeps reading them."""
        module = _write_community_module(tmp_path, with_separate_db=True)

        assert _collect_module_tablenames(module) == {'inv2039demo_claims'}

    def test_a_local_offbase_lookalike_does_not_exile_the_module(self, tmp_path: Path):
        """Naming a local class ``OFFBase`` is not the seam: the separate
        base is the one DEFINED in ``app.modules.nutrition.models``. A
        lookalike defined in the module inherits nothing that the products
        engine knows about, so the module stays on the main database and in
        this gate's sight."""
        module = _write_community_module(tmp_path)
        (module / 'models.py').write_text(
            'from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column\n\n\n'
            'class OFFBase(DeclarativeBase):\n'
            '    pass\n\n\n'
            'class Claim(OFFBase):\n'
            "    __tablename__ = 'inv2039demo_claims'\n\n"
            '    id: Mapped[int] = mapped_column(primary_key=True)\n',
            encoding='utf-8',
        )

        assert _collect_module_tablenames(module) == {'inv2039demo_claims'}

    def test_a_nested_app_catalog_crowns_nobody(self, tmp_path: Path):
        """A module can build a directory shaped like the package path —
        ``app/modules/nutrition/models.py`` inside itself — and define a
        local ``OFFBase`` there. Reading the defining file out of the
        path's segments crowned that lookalike: the name anchored at the
        last ``app`` of the absolute path, matched the real defining
        module, and one inherited class switched the whole module to the
        separate-database reading — tables invisible, gate green. The
        defining file is recognized by structure instead: the nutrition
        module's own top-level ``models.py``, in a directory actually
        named ``nutrition``. A lookalike built from folders names
        nothing, and the module's real tables stay in this gate's sight."""
        module = _write_community_module(tmp_path)
        nested = module / 'app' / 'modules' / 'nutrition'
        nested.mkdir(parents=True)
        (nested / 'models.py').write_text(
            'from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column\n\n\n'
            'class OFFBase(DeclarativeBase):\n'
            '    pass\n\n\n'
            'class Claim(OFFBase):\n'
            "    __tablename__ = 'nested_probe_claims'\n\n"
            '    id: Mapped[int] = mapped_column(primary_key=True)\n',
            encoding='utf-8',
        )

        assert _on_separate_database(module) is False
        assert _collect_module_tablenames(module) == {'inv2039demo_claims'}

    def test_the_real_nutrition_models_stay_out(self):
        """AC control on the real tree: nutrition defines and inherits the
        separate-database base, so it must still read as separate-database —
        the rewrite may not turn the honest user of the seam into a
        finding."""
        nutrition = (
            Path(__file__).resolve().parents[2] / 'app' / 'modules' / 'nutrition'
        )

        assert nutrition.is_dir()
        assert _on_separate_database(nutrition) is True

    def test_the_defining_file_is_recognized_in_a_ci_shaped_checkout(
        self, tmp_path: Path
    ):
        """End-to-end on a checkout whose absolute path holds ``app`` once
        — the CI shape: nutrition defines the separate-database base there,
        so it reads as separate-database. On a name read from the absolute
        path this exact tree came up one ``app`` short, the defining file
        stopped matching, and the gate flagged the products database's
        tables as core-untracked."""
        nutrition = tmp_path / 'backend' / 'app' / 'modules' / 'nutrition'
        nutrition.mkdir(parents=True)
        (nutrition / 'models.py').write_text(
            'from sqlalchemy.orm import DeclarativeBase\n\n\n'
            'class OFFBase(DeclarativeBase):\n'
            '    pass\n\n\n'
            'class ProbeProduct(OFFBase):\n'
            "    __tablename__ = 'nutrition_probe_products'\n",
            encoding='utf-8',
        )

        assert nutrition.is_dir()
        assert _on_separate_database(nutrition) is True


class TestConsumerMigrationExistenceCheck:
    def test_lint_refuses_a_community_module_without_migrations(self, tmp_path: Path):
        _write_community_module(tmp_path)

        errors = _check_module_migrations_exist(tmp_path)

        assert errors
        assert any('inv2039demo' in error for error in errors)


class TestConsumerMigrationDoctor:
    def test_doctor_diagnoses_a_stampless_community_module_for_real(
        self, tmp_path: Path, monkeypatch
    ):
        """With the blind helper the doctor read a community module's
        present tables as 'no tables' and answered 'fresh' — migrations
        would then run into tables that already exist. Seeing the tables,
        it answers what the state actually is: reconcilable by stamping."""
        from app.core import migration_doctor, module_migrations

        _write_community_module(tmp_path, with_migration=True)
        monkeypatch.setattr(migration_doctor, 'MODULES_ROOT', tmp_path)
        monkeypatch.setattr(module_migrations, 'MODULES_ROOT', tmp_path)

        schema = migration_doctor.SchemaState(
            frozenset({'inv2039demo_claims'}),
            frozenset({('inv2039demo_claims', 'id')}),
        )
        diagnosis = migration_doctor._diagnose_stampless(
            'inv2039demo', schema, frozenset()
        )

        assert diagnosis.status != 'fresh'
        assert diagnosis.status == 'reconcilable'


class TestConsumerUpgradeModulesStampDecision:
    def test_tables_outside_the_baseline_run_from_scratch(self):
        """A community module's tables were never part of the core
        baseline, so upgrade-modules must not stamp 001_initial over them
        — it must let the migrations create them.

        The decision function is pure, so the inputs here are not
        hand-written: they are the helper's real reading of a community
        module's models in this tree. The walk going blind on community
        code must fail right here, at the entrance to the decision —
        hand-written sets would pass all the way through a blind walk.
        """
        from app.cli.commands_db import _should_stamp_at_baseline
        from app.core.architecture_lint._quality_checks import (
            _collect_module_tablenames,
        )
        from app.core.module_migrations import MODULES_ROOT

        tables = _collect_module_tablenames(MODULES_ROOT / 'example_widgets')
        assert tables, (
            'the table walk read example_widgets as tableless — a community '
            'module would be stamped without its tables ever being checked'
        )
        assert _should_stamp_at_baseline(tables, set()) is False
        assert _should_stamp_at_baseline(tables, tables) is True
        # A module the helper reads as tableless keeps the old path.
        assert _should_stamp_at_baseline(set(), set()) is True


class TestSeparateDatabaseIsPerTable:
    """The exclusion covers the tables on the other database, not the module."""

    def test_a_module_with_both_kinds_reports_its_own_tables(self, tmp_path: Path):
        module = _write_community_module(tmp_path)
        (module / 'models.py').write_text(
            'from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column\n'
            'from app.modules.nutrition.models import OFFBase\n\n\n'
            'class CommunityBase(DeclarativeBase):\n'
            '    pass\n\n\n'
            'class Claim(CommunityBase):\n'
            "    __tablename__ = 'inv2039demo_claims'\n\n"
            '    id: Mapped[int] = mapped_column(primary_key=True)\n\n\n'
            'class Product(OFFBase):\n'
            "    __tablename__ = 'inv2039demo_products'\n\n"
            '    id: Mapped[int] = mapped_column(primary_key=True)\n',
            encoding='utf-8',
        )

        assert _collect_module_tablenames(module) == {'inv2039demo_claims'}
        errors = _check_module_migrations_exist(tmp_path)
        assert any('inv2039demo_claims' in e for e in errors)
        assert not any('inv2039demo_products' in e for e in errors)

    def test_a_module_with_only_separate_tables_reports_none(self, tmp_path: Path):
        module = tmp_path / 'onlyoff'
        module.mkdir()
        (module / 'models.py').write_text(
            'from app.modules.nutrition.models import OFFBase\n\n\n'
            'class Product(OFFBase):\n'
            "    __tablename__ = 'onlyoff_products'\n",
            encoding='utf-8',
        )

        assert _collect_module_tablenames(module) == set()


class TestExternalModuleRoots:
    def test_lint_asks_modules_outside_the_repo_tree(self, tmp_path: Path):
        from app.core.architecture_lint import _main

        assert _main.EXTERNAL_MODULES_ROOTS
        assert Path('/modules-workspace') in _main.EXTERNAL_MODULES_ROOTS
