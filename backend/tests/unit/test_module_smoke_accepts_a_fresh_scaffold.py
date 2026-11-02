"""``module smoke`` on a module the quickstart has just generated and installed.

The community scaffold ships a model and its migration, so it declares the one
capability those imports need (`database`); smoke reads the declaration, it
does not infer it. Smoke used to fail the scaffold for declaring nothing, and
looked for the frontend half under ``./frontend/src/modules`` of whatever
directory it was started from rather than where the installer put it.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from app.cli import _module_meta, module_packaging
from manage import app


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """A scaffolded, installed community module, with the frontend mount away from the cwd."""
    backend = tmp_path / 'install' / 'backend_modules'
    frontend = tmp_path / 'install' / 'frontend_modules'
    frontend.mkdir(parents=True)
    for module in (_module_meta, module_packaging):
        monkeypatch.setattr(module, 'BACKEND_MODULES_DIR', backend)
        monkeypatch.setattr(module, 'FRONTEND_MODULES_DIR', frontend)
    monkeypatch.setattr(_module_meta, 'TRACKING_FILE', tmp_path / 'tracking.json')
    monkeypatch.setattr(_module_meta, 'LEGACY_TRACKING_FILE', tmp_path / 'legacy.json')
    # The cwd is not where the installer puts the frontend half.
    cwd = tmp_path / 'elsewhere'
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    runner = CliRunner()
    workspace = tmp_path / 'workspace'
    result = runner.invoke(
        app, ['module', 'new-community', 'warranty_tracker', '--output', str(workspace)]
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        app,
        ['module', 'install', str(workspace / 'warranty_tracker'), '--allow-unsigned'],
    )
    assert result.exit_code == 0, result.output
    return runner, backend, frontend


@pytest.mark.unit
def test_smoke_passes_the_scaffold_it_installed(installed):
    runner, backend, _ = installed
    result = runner.invoke(
        app, ['module', 'smoke', 'warranty_tracker', '--base-path', str(backend)]
    )
    assert result.exit_code == 0, result.output
    assert '✗' not in result.output


@pytest.mark.unit
def test_smoke_finds_the_frontend_half_where_the_installer_put_it(installed):
    runner, backend, frontend = installed
    assert (frontend / 'warranty_tracker' / 'module.ts').is_file()
    result = runner.invoke(
        app, ['module', 'smoke', 'warranty_tracker', '--base-path', str(backend)]
    )
    assert 'frontend module.ts exists' in result.output, result.output
    assert 'frontend module dir' not in result.output


@pytest.mark.unit
def test_smoke_does_not_fail_a_module_that_has_no_frontend_half(installed):
    runner, backend, frontend = installed
    import shutil

    shutil.rmtree(frontend / 'warranty_tracker')
    result = runner.invoke(
        app, ['module', 'smoke', 'warranty_tracker', '--base-path', str(backend)]
    )
    assert result.exit_code == 0, result.output
