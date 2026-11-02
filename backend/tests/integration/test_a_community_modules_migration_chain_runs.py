"""The community scaffold's migration chain is a real one.

The scaffold used to create a ``models.py`` with no model and no migrations at
all, so the guide's migration advice had nothing to run — and a community author
had no ``env.py`` to run it with. What the package ships now is proved the way
the platform applies it: ``run_module_migrations`` against an empty database,
through the package's own ``env.py``. Upgrade creates the table the model
declares, downgrade removes it, and the chain records itself in a version table
of the module's own.
"""

from __future__ import annotations

import sys

import pytest
from sqlalchemy import create_engine, inspect
from typer.testing import CliRunner

from app.cli import _module_meta, module_packaging
from app.core import module_migrations
from app.core.contracts import ModuleModelBase
from app.core.db_isolation import isolated_db_url
from manage import app

MODULE = 'demo_mod'

pytestmark = pytest.mark.integration


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """A scaffolded package, installed as an unsigned one, importable as a module."""
    backend = tmp_path / 'install' / 'backend_modules'
    backend.mkdir(parents=True)
    frontend = tmp_path / 'install' / 'frontend_modules'
    frontend.mkdir(parents=True)
    for module in (_module_meta, module_packaging):
        monkeypatch.setattr(module, 'BACKEND_MODULES_DIR', backend)
        monkeypatch.setattr(module, 'FRONTEND_MODULES_DIR', frontend)
    monkeypatch.setattr(_module_meta, 'TRACKING_FILE', tmp_path / 'tracking.json')
    monkeypatch.setattr(_module_meta, 'LEGACY_TRACKING_FILE', tmp_path / 'legacy.json')

    runner = CliRunner()
    result = runner.invoke(
        app, ['module', 'new-community', MODULE, '--output', str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        app, ['module', 'install', str(tmp_path / MODULE), '--allow-unsigned']
    )
    assert result.exit_code == 0, result.output

    import app.modules as app_modules

    monkeypatch.setattr(
        app_modules, '__path__', [str(backend), *list(app_modules.__path__)]
    )
    monkeypatch.setattr(module_migrations, 'MODULES_ROOT', backend)
    before = set(sys.modules)
    # Nothing else in the process declares on the module base (the in-repo
    # modules use the core's), so whatever it holds after the test is this
    # module's, and the teardown can clear all of it.
    assert not ModuleModelBase.metadata.tables, 'a test left a module table on the base'
    yield backend / MODULE
    for name in set(sys.modules) - before:
        if name == f'app.modules.{MODULE}' or name.startswith(f'app.modules.{MODULE}.'):
            del sys.modules[name]
    # Importing the models mapped a class and declared its table on the
    # process-wide base; left there, the next test that imports the same
    # module is refused ("Table ... is already defined for this MetaData").
    ModuleModelBase.registry.dispose()
    ModuleModelBase.metadata.clear()


def _tables(db_url: str) -> set[str]:
    engine = create_engine(db_url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _create_organizations(db_url: str) -> None:
    """The core tables the module's foreign key chain needs, and no others."""
    from app.database import Base
    from app.models.organization import Organization
    from app.models.user import User

    engine = create_engine(db_url)
    try:
        Base.metadata.create_all(
            engine, tables=[User.__table__, Organization.__table__]
        )
    finally:
        engine.dispose()


@pytest.mark.integration
def test_the_scaffolds_model_persists_its_first_row(installed):
    """The model an author starts from must survive its first flush.

    ``ModuleModelBase``'s metadata holds the module's tables only, so an
    ORM-level ``ForeignKey('organizations.id')`` has no target to resolve and
    the first flush raises ``NoReferencedTableError``. The row persists, and
    the database still enforces the constraint the migration declared.
    """
    from sqlalchemy.orm import Session

    from app.models.organization import Organization

    table = f'{MODULE}_records'

    with isolated_db_url('community') as db_url:
        _create_organizations(db_url)
        module_migrations.run_module_migrations(MODULE, 'upgrade', db_url=db_url)

        from app.modules.demo_mod.models import Record

        engine = create_engine(db_url)
        try:
            with Session(engine) as session:
                organization = Organization(name='Demo Org')
                session.add(organization)
                session.flush()
                record = Record(organization_id=organization.id)
                session.add(record)
                session.flush()
                assert record.id is not None
                session.rollback()

            foreign_keys = inspect(engine).get_foreign_keys(table)
        finally:
            engine.dispose()

    assert any(
        fk['constrained_columns'] == ['organization_id']
        and fk['referred_table'] == 'organizations'
        for fk in foreign_keys
    ), foreign_keys


@pytest.mark.integration
def test_upgrade_creates_the_table_and_downgrade_removes_it(installed):
    table = f'{MODULE}_records'

    with isolated_db_url('community') as db_url:
        _create_organizations(db_url)

        module_migrations.run_module_migrations(MODULE, 'upgrade', db_url=db_url)
        tables = _tables(db_url)

        assert table in tables
        assert f'alembic_version_{MODULE}' in tables

        module_migrations.run_module_migrations(MODULE, 'downgrade', db_url=db_url)

        assert table not in _tables(db_url)
