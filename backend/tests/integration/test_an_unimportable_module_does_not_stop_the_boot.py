"""A module that cannot be imported does not keep the backend from starting.

The entrypoint runs ``db doctor`` before the migrations and refuses the boot
when it exits non-zero. The doctor's column-type check imported every module's
models, so one community package with a typo in an import raised out of it:
the container restarted forever, every user of the installation lost the app,
and the entrypoint blamed the migration state. Discovery already rejects such
a package and starts the backend without it; the doctor now says so and lets
the boot go on.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from manage import app

runner = CliRunner()

NAME = 'typo_mod'
TYPO = 'something_that_does_not_exist'


@pytest.fixture
def modules_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A module tree of one installed package whose import fails.

    Discovery imports a module as ``app.modules.<name>``, so the tree joins
    that package's search path; the doctor and the registry both read it in
    place of the real one, and a registry of its own keeps the rejection out
    of the process-wide one.
    """
    import app.cli.module_packaging as module_packaging
    import app.core._registry_class as registry_class
    import app.core.migration_doctor as migration_doctor
    import app.core.module_migrations as module_migrations
    import app.core.module_registry as module_registry
    import app.core.module_tracking as module_tracking
    import app.modules

    root = tmp_path / 'modules'
    package = root / NAME
    package.mkdir(parents=True)
    (package / '__init__.py').write_text(
        f'from app.core.module_sdk import {TYPO}\n', encoding='utf-8'
    )
    (package / 'models.py').write_text('', encoding='utf-8')
    (package / 'manifest.json').write_text(
        json.dumps({'name': NAME, 'version': '0.1.0', 'module_type': 'community'}),
        encoding='utf-8',
    )

    monkeypatch.setattr(app.modules, '__path__', [*app.modules.__path__, str(root)])
    monkeypatch.setattr(registry_class, 'REPO_MODULES_ROOT', root)
    monkeypatch.setattr(migration_doctor, 'MODULES_ROOT', root)
    monkeypatch.setattr(module_migrations, 'MODULES_ROOT', root)
    monkeypatch.setattr(
        module_registry, 'module_registry', registry_class.ModuleRegistry()
    )
    tracked = {NAME: {'version': '0.1.0'}}
    monkeypatch.setattr(module_tracking, 'load_module_tracking', lambda: tracked)
    monkeypatch.setattr(
        module_packaging, 'list_community_modules', lambda: list(tracked.items())
    )
    return root


@pytest.mark.integration
def test_the_pre_flight_check_passes_and_names_the_way_back(modules_root: Path):
    result = runner.invoke(app, ['db', 'doctor'])

    assert result.exit_code == 0, result.output
    assert f'Module {NAME} is rejected' in result.output
    assert TYPO in result.output
    assert f'module uninstall {NAME}' in result.output


@pytest.mark.integration
def test_module_list_names_the_rejection_instead_of_a_pending_restart(
    modules_root: Path,
):
    result = runner.invoke(app, ['module', 'list'])

    assert result.exit_code == 0, result.output
    assert 'rejected and do not load' in result.output
    assert f'{NAME}: Import failed' in result.output
    assert TYPO in result.output
    assert 'not yet active' not in result.output
