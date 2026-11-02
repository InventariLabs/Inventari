"""Test that ``upgrade-modules`` creates tables for new modules, not stamps.

Regression test for a bug where ``upgrade-modules`` stamped every module
with an empty version table at ``001_initial`` without verifying that the
module's tables actually exist. For new modules whose tables were never
in the core baseline, this skipped table creation — causing subsequent
migrations (e.g. ``ALTER TABLE``) to crash with ``UndefinedTable``.

With the fix, ``upgrade-modules`` only stamps when the module's tables
already exist in the DB; otherwise it runs migrations from scratch.
"""

import importlib

import pytest
from sqlalchemy import create_engine, inspect, text

from app.core.architecture_lint._quality_checks import (
    _collect_module_tablenames,
)
from app.core.db_isolation import isolated_db_url as _isolated_db_url
from app.core.module_migrations import MODULES_ROOT, get_version_table_name

MODULES_WITH_TABLES = sorted(
    name
    for name in (
        d.name
        for d in MODULES_ROOT.iterdir()
        if (d / 'migrations' / 'versions').is_dir()
    )
    if _collect_module_tablenames(MODULES_ROOT / name)
)


@pytest.fixture
def isolated_db_url():
    """Empty database with core tables but NO module tables."""
    with _isolated_db_url('stamp_guard') as test_url:
        # Create all Base.metadata tables, then drop every module table +
        # version table so only core tables remain.
        import app.core.template_models  # noqa: F401
        import app.models  # noqa: F401
        from app.database import Base

        engine = create_engine(test_url)
        Base.metadata.create_all(engine)
        with engine.connect() as conn:
            for module_name in MODULES_WITH_TABLES:
                version_tbl = get_version_table_name(module_name)
                conn.execute(text(f'DROP TABLE IF EXISTS "{version_tbl}" CASCADE'))
                for tbl in _collect_module_tablenames(MODULES_ROOT / module_name):
                    conn.execute(text(f'DROP TABLE IF EXISTS "{tbl}" CASCADE'))
            conn.commit()
        engine.dispose()

        yield test_url


@pytest.mark.integration
class TestUpgradeModulesStampGuard:
    """Verify ``upgrade-modules`` runs migrations from scratch for new modules."""

    def test_module_tables_created_when_not_in_baseline(
        self, isolated_db_url, monkeypatch
    ):
        """Tables must be created, not stamped, when they don't exist."""
        monkeypatch.setenv('DATABASE_URL', isolated_db_url)

        from app.cli.commands_db import upgrade_modules

        upgrade_modules()

        engine = create_engine(isolated_db_url)
        insp = inspect(engine)
        all_tables = set(insp.get_table_names())

        # Every module that owns tables should have them created.
        for module_name in MODULES_WITH_TABLES:
            expected = _collect_module_tablenames(MODULES_ROOT / module_name)
            for tbl in expected:
                assert tbl in all_tables, (
                    f'{module_name}: table "{tbl}" missing '
                    f'— upgrade-modules stamped without creating it'
                )

            # Version table should be populated (at head), not empty.
            version_tbl = get_version_table_name(module_name)
            with engine.connect() as conn:
                row = conn.execute(
                    text(f'SELECT version_num FROM "{version_tbl}"')
                ).scalar()
            assert row is not None, (
                f'{module_name}: version table empty after upgrade-modules'
            )

        engine.dispose()

    def test_module_tables_preserved_when_in_baseline(
        self, isolated_db_url, monkeypatch
    ):
        """Pre-existing baseline tables should be stamped (not re-created)."""
        # Pre-create one module's tables manually (simulating baseline).
        module_name = MODULES_WITH_TABLES[0]
        expected_tables = _collect_module_tablenames(MODULES_ROOT / module_name)

        engine = create_engine(isolated_db_url)
        import app.core.template_models  # noqa: F401
        import app.models  # noqa: F401
        from app.database import Base

        tbl_objs = [t for t in Base.metadata.sorted_tables if t.name in expected_tables]
        Base.metadata.create_all(engine, tables=tbl_objs)
        engine.dispose()

        # Drop the version table to force a fresh stamp decision.
        version_tbl = get_version_table_name(module_name)
        engine = create_engine(isolated_db_url)
        with engine.connect() as conn:
            conn.execute(text(f'DROP TABLE IF EXISTS "{version_tbl}" CASCADE'))
            conn.commit()
        engine.dispose()

        monkeypatch.setenv('DATABASE_URL', isolated_db_url)
        from app.cli.commands_db import upgrade_modules

        upgrade_modules()

        # Tables still exist and version is populated.
        engine = create_engine(isolated_db_url)
        insp = inspect(engine)
        all_tables = set(insp.get_table_names())
        for tbl in expected_tables:
            assert tbl in all_tables
        with engine.connect() as conn:
            row = conn.execute(
                text(f'SELECT version_num FROM "{version_tbl}"')
            ).scalar()
        assert row is not None
        engine.dispose()

    def test_a_module_whose_import_is_rejected_is_not_stamped(
        self, isolated_db_url, monkeypatch
    ):
        """Stamping a rejected module wrote a version row for tables that
        did not exist; the later install hook saw the head reached, no-op'd,
        and the tables never came into being. The entrypoint now refuses to
        touch a module the app cannot import."""
        monkeypatch.setenv('DATABASE_URL', isolated_db_url)

        from app.core import module_migrations

        ran: list[tuple] = []
        monkeypatch.setattr(
            module_migrations,
            'discover_modules_with_migrations',
            lambda modules_root=None: ['inv2163ghost'],
        )
        monkeypatch.setattr(
            module_migrations,
            'run_module_migrations',
            lambda *a, **k: ran.append(a),
        )

        from app.cli.commands_db import upgrade_modules

        upgrade_modules()

        assert ran == [], 'a rejected module must not be stamped or migrated'
        engine = create_engine(isolated_db_url)
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT to_regclass('alembic_version_inv2163ghost')")
            ).scalar()
        engine.dispose()
        assert rows is None, 'no version row may exist for a rejected module'

    @staticmethod
    def _rejection_fixture(
        monkeypatch, isolated_db_url, module_name: str, reason: str
    ) -> list[tuple]:
        """A module discovery has rejected, whose code still imports clean.

        The safety validator refuses code the interpreter accepts (a
        forbidden import is ordinary, importable Python), so simulating the
        shape needs both halves: a rejection record in the registry — what
        discovery decided — and an import that succeeds — what the old
        import-only probe saw.
        """
        import types

        monkeypatch.setenv('DATABASE_URL', isolated_db_url)

        from app.core import module_migrations
        from app.core.module_registry import module_registry
        from app.core.module_validator import RejectedModule

        module_registry._rejected_modules[module_name] = RejectedModule(
            module_name=module_name, reason=reason
        )

        real_import = importlib.import_module

        def import_module(name, *args, **kwargs):
            if name == f'app.modules.{module_name}':
                return types.ModuleType(name)  # syntactically valid: imports
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(importlib, 'import_module', import_module)
        # bootstrap re-runs discovery over the real tree; the record is
        # already seeded, so the command under test needs no re-scan.
        monkeypatch.setattr('app.cli.commands_db.bootstrap_db', lambda: None)
        monkeypatch.setattr(
            module_migrations,
            'discover_modules_with_migrations',
            lambda modules_root=None: [module_name],
        )
        ran: list[tuple] = []
        monkeypatch.setattr(
            module_migrations,
            'run_module_migrations',
            lambda *a, **k: ran.append(a),
        )
        return ran

    def test_a_module_rejected_for_safety_is_not_touched_even_though_it_imports(
        self, isolated_db_url, monkeypatch
    ):
        """The safety validator rejects code that imports cleanly; a probe
        that only asks the interpreter sees nothing wrong and the module
        got stamped and migrated behind the rejection's back — one run
        saying 'Rejected module X' and '✔ X: migrated from scratch'."""
        from app.cli.commands_db import console, upgrade_modules

        ran = self._rejection_fixture(
            monkeypatch,
            isolated_db_url,
            'inv2277unsafe',
            'FORBIDDEN import in inv2277unsafe/router.py:1 -> app.database',
        )

        with console.capture() as capture:
            upgrade_modules()

        output = capture.get()
        assert ran == [], 'a module discovery rejected must not be stamped or migrated'
        engine = create_engine(isolated_db_url)
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT to_regclass('alembic_version_inv2277unsafe')")
            ).scalar()
        engine.dispose()
        assert rows is None, 'no version row may exist for a rejected module'
        assert 'FORBIDDEN import' in output, (
            "the refusal must name discovery's own reason"
        )
        assert '✔ inv2277unsafe' not in output, (
            'one run must not refuse and greet the same module'
        )

    def test_a_module_rejected_transitively_is_not_touched(
        self, isolated_db_url, monkeypatch
    ):
        """Missing ``requires`` fall away transitively — the registry's
        fixpoint rejects dependents of the rejected. That shape also passes
        an import probe, so it must reach the gate through the same
        records."""
        from app.cli.commands_db import upgrade_modules

        ran = self._rejection_fixture(
            monkeypatch,
            isolated_db_url,
            'inv2277orphan',
            'Missing required module or dependency failed: equipment',
        )

        upgrade_modules()

        assert ran == [], (
            'a transitively rejected module must not be stamped or migrated'
        )
        engine = create_engine(isolated_db_url)
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT to_regclass('alembic_version_inv2277orphan')")
            ).scalar()
        engine.dispose()
        assert rows is None
