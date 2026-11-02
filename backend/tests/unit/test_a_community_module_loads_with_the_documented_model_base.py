"""A community module built the way the documents say is loadable.

The guide told an author to inherit ``app.database.Base``, and the install-time
safety scan refuses ``app.database`` to a module outside this repository — so a
module written exactly as documented was rejected at load, and no sanctioned
declarative base existed for the module's own tables. The contract surface now
exports one (``ModuleModelBase``), the guide, the quickstart and the community
scaffold use it, and this file walks the author's path end to end: scaffold,
install it as an untrusted (unsigned) package, let module discovery load it.

The last test pins the refusal that made the export necessary: the import the
guide used to show still does not load. If that ever starts passing, the
sanctioned base is the only thing between an author and a refused install, and
the documents must say so for a reason.
"""

from __future__ import annotations

import importlib
import json
import re
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.cli import _module_meta, module_packaging
from app.core.contracts import ModuleModelBase
from app.core.module_migrations import discover_modules_with_migrations
from app.core.module_registry import ModuleRegistry
from app.core.module_safety_analysis import analyze_module_safety
from manage import app

MODULE = 'demo_mod'


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """An installation tree of its own: the checkout is never written to."""
    backend = tmp_path / 'install' / 'backend_modules'
    backend.mkdir(parents=True)
    frontend = tmp_path / 'install' / 'frontend_modules'
    frontend.mkdir(parents=True)
    for module in (_module_meta, module_packaging):
        monkeypatch.setattr(module, 'BACKEND_MODULES_DIR', backend)
        monkeypatch.setattr(module, 'FRONTEND_MODULES_DIR', frontend)
    monkeypatch.setattr(_module_meta, 'TRACKING_FILE', tmp_path / 'tracking.json')
    monkeypatch.setattr(_module_meta, 'LEGACY_TRACKING_FILE', tmp_path / 'legacy.json')
    return tmp_path


@pytest.fixture
def installed(workspace):
    """The scaffolded package, installed as an untrusted one."""
    package = workspace / MODULE
    result = CliRunner().invoke(
        app,
        ['module', 'new-community', MODULE, '--output', str(workspace)],
    )
    assert result.exit_code == 0, result.output
    result = CliRunner().invoke(
        app, ['module', 'install', str(package), '--allow-unsigned']
    )
    assert result.exit_code == 0, result.output
    return workspace / 'install' / 'backend_modules' / MODULE


@pytest.fixture
def loadable(installed, monkeypatch):
    """Make the temporary installation importable as ``app.modules.<name>``."""
    import app.modules as app_modules

    backend = installed.parent
    monkeypatch.setattr(
        app_modules, '__path__', [str(backend), *list(app_modules.__path__)]
    )
    before = set(sys.modules)
    # Nothing else in the process declares on the module base (the in-repo
    # modules use the core's), so whatever it holds after the test is this
    # module's, and the teardown can clear all of it.
    assert not ModuleModelBase.metadata.tables, 'a test left a module table on the base'
    yield installed
    for name in set(sys.modules) - before:
        if name == f'app.modules.{MODULE}' or name.startswith(f'app.modules.{MODULE}.'):
            del sys.modules[name]
    # Importing the models mapped a class and declared its table on the
    # process-wide base; left there, the next test that imports the same
    # module is refused ("Table ... is already defined for this MetaData").
    ModuleModelBase.registry.dispose()
    ModuleModelBase.metadata.clear()


def _tablename(models_source: str) -> str:
    match = re.search(r"__tablename__ = '([^']+)'", models_source)
    assert match, 'the scaffolded models.py declares no table'
    return match.group(1)


@pytest.mark.unit
class TestTheScaffold:
    def test_models_inherit_the_module_base_and_never_the_core_one(self, installed):
        """A scaffold that shows ``app.database`` hands every author the
        import the scan refuses — the defect this base exists to close."""
        source = (installed / 'models.py').read_text(encoding='utf-8')

        assert 'from app.core.contracts import ModuleModelBase' in source
        assert re.search(r'^class \w+\(ModuleModelBase\):', source, re.MULTILINE)
        assert 'from app.database import' not in source
        assert 'import app.database' not in source

    def test_the_shipped_migration_creates_the_modeled_table(self, installed):
        """A model without the revision that creates it is a module that
        installs and then fails on its first query."""
        table = _tablename((installed / 'models.py').read_text(encoding='utf-8'))

        migration = (
            installed / 'migrations' / 'versions' / '001_initial.py'
        ).read_text(encoding='utf-8')

        assert f"'{table}'" in migration

    def test_the_migration_environment_is_part_of_the_package(self, installed):
        """Alembic finds ``env.py`` beside ``versions/``; without it the
        platform cannot apply the chain it just installed."""
        assert (installed / 'migrations' / 'env.py').is_file()
        assert (installed / 'migrations' / 'versions' / '001_initial.py').is_file()


@pytest.mark.unit
class TestTheAuthorsPath:
    def test_an_unsigned_module_installs_and_discovery_loads_it(self, loadable):
        # Discovery runs the install-time safety scan before it imports the
        # module; the scaffold's app imports are exactly the declared surface
        # (contracts, public_api, module_sdk), so this load *is* the
        # allow-list check. The scan is asserted on its own in
        # test_a_module_imports_through_the_sdk.py.
        assert analyze_module_safety(loadable, ['database'], use_cache=False) == []

        registry = ModuleRegistry()

        registry.discover_modules(base_path=loadable.parent)

        rejected = {r.module_name: r.reason for r in registry.get_rejected_modules()}
        assert MODULE not in rejected, rejected
        assert registry.get(MODULE) is not None

    def test_the_platform_finds_the_migration_chain(self, installed):
        assert MODULE in discover_modules_with_migrations(installed.parent)

    def test_module_tables_stay_out_of_the_core_metadata(self, loadable):
        """The core's autogenerate reads ``Base.metadata``; a community table
        in it would be proposed as a core migration on every dev box that has
        the module installed."""
        from app.core.contracts import ModuleModelBase
        from app.database import Base

        models = importlib.import_module(f'app.modules.{MODULE}.models')
        table = models.Record.__tablename__

        assert table in ModuleModelBase.metadata.tables
        assert table not in Base.metadata.tables


@pytest.mark.unit
def test_the_import_the_guide_used_to_show_is_still_refused(tmp_path: Path):
    """``from app.database import Base`` — the sentence the guide printed —
    never reaches the loader. The scan refuses it before a module is imported."""
    module = tmp_path / 'legacy_mod'
    module.mkdir()
    (module / 'manifest.json').write_text(
        json.dumps(
            {
                'name': 'legacy_mod',
                'version': '0.1.0',
                'module_type': 'community',
                'capabilities': ['database'],
            }
        ),
        encoding='utf-8',
    )
    (module / 'models.py').write_text(
        'from app.database import Base\n\n\n'
        'class Note(Base):\n'
        "    __tablename__ = 'legacy_notes'\n",
        encoding='utf-8',
    )

    findings = analyze_module_safety(module, ['database'], use_cache=False)

    assert any(
        finding.kind == 'forbidden_import'
        and finding.subject.startswith('app.database')
        for finding in findings
    ), findings
