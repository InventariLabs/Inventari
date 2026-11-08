"""One package, four gates, one verdict.

``module validate``, ``module install`` and ``module upgrade`` run ahead of the
next start, and each used to disagree with module discovery about a package:
discovery refused a manifest whose ``name`` differs from its directory, a
module from outside the repository claiming ``official``, and a platform floor
above the running version, while the three commands printed success and the
module was rejected at the restart. The other way round, ``install`` and
``upgrade`` refused ``requires: [items]`` — they looked for a directory — while
discovery loads it, since an always-on feature is part of the platform.
And ``validate`` could not read a package at all: it looked for
``<name>/manifest.json``, and a package keeps its manifest in ``backend/``.

Each fixture below goes through all four, as an author's package.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.cli import _module_meta, _module_upgrade, module_packaging
from app.core.module_registry import ModuleRegistry
from manage import app

NAME = 'accord_mod'

#: The package the scaffold would write, cut to what discovery needs to load it.
INIT = (
    'from fastapi import APIRouter\n\n'
    'from app.core.module_sdk import define_module\n\n'
    'module = define_module(router=APIRouter())\n'
)


def _package(
    root: Path,
    *,
    manifest_name: str = NAME,
    module_type: str = 'community',
    floor: str = '0.1.0',
    requires: tuple[str, ...] = (),
) -> Path:
    package = root / 'packages' / NAME
    backend = package / 'backend'
    (backend / 'i18n').mkdir(parents=True)
    (package / 'module.yaml').write_text(
        f'name: {NAME}\n'
        'version: 0.2.0\n'
        'inventari_min_version: "0.1.0"\n'
        'author: test\n'
        'description: one package through every gate\n'
        'license: MIT\n'
        'homepage: ""\n'
        f'requires: {json.dumps(list(requires))}\n'
        'components:\n'
        '  backend: true\n'
        '  frontend: false\n',
        encoding='utf-8',
    )
    (backend / '__init__.py').write_text(INIT, encoding='utf-8')
    (backend / 'manifest.json').write_text(
        json.dumps(
            {
                'name': manifest_name,
                'version': '0.2.0',
                'inventari_min_version': floor,
                'display_name': 'Accord',
                'description': 'one package through every gate',
                'icon': 'package',
                'module_type': module_type,
                'requires': list(requires),
                'capabilities': [],
            }
        ),
        encoding='utf-8',
    )
    (backend / 'i18n' / 'en.json').write_text('{}', encoding='utf-8')
    return package


@pytest.fixture
def installation(tmp_path, monkeypatch):
    """An installation tree of its own: the checkout is never written to."""
    backend = tmp_path / 'install' / 'backend_modules'
    backend.mkdir(parents=True)
    frontend = tmp_path / 'install' / 'frontend_modules'
    frontend.mkdir(parents=True)
    for module in (_module_meta, module_packaging, _module_upgrade):
        monkeypatch.setattr(module, 'BACKEND_MODULES_DIR', backend)
        monkeypatch.setattr(module, 'FRONTEND_MODULES_DIR', frontend)
    monkeypatch.setattr(_module_meta, 'TRACKING_FILE', tmp_path / 'tracking.json')
    monkeypatch.setattr(_module_meta, 'LEGACY_TRACKING_FILE', tmp_path / 'legacy.json')
    return backend


def _validate(package: Path) -> bool:
    result = CliRunner().invoke(
        app,
        ['module', 'validate', '--base-path', str(package.parent), '--module', NAME],
    )
    return result.exit_code == 0


def _install(package: Path, installed: Path) -> bool:
    result = CliRunner().invoke(
        app, ['module', 'install', str(package), '--allow-unsigned']
    )
    landed = (installed / NAME).exists()
    assert landed == (result.exit_code == 0), result.output
    return result.exit_code == 0


def _upgrade(package: Path, installed: Path) -> bool:
    """Upgrade over a v0.1.0 that tracking already knows."""
    shutil.rmtree(installed / NAME, ignore_errors=True)
    _module_meta._save_tracking(
        {NAME: {'version': '0.1.0', 'source': 'earlier', 'has_backend': True}}
    )
    result = CliRunner().invoke(
        app, ['module', 'upgrade', str(package), '--allow-unsigned']
    )
    recorded = _module_meta._load_tracking()[NAME]['version']
    assert (recorded == '0.2.0') == (result.exit_code == 0), result.output
    return result.exit_code == 0


def _discover(package: Path, root: Path, monkeypatch) -> bool:
    """Load the package the way the next start would, from the backend half
    laid out under its name."""
    import app.modules as app_modules

    modules_root = root / 'discovered'
    shutil.copytree(package / 'backend', modules_root / NAME)
    monkeypatch.setattr(
        app_modules, '__path__', [str(modules_root), *list(app_modules.__path__)]
    )
    registry = ModuleRegistry()
    try:
        registry.discover_modules(base_path=modules_root)
    finally:
        for name in [n for n in sys.modules if n.startswith(f'app.modules.{NAME}')]:
            del sys.modules[name]
    loaded = registry.get(NAME) is not None
    rejected = NAME in {r.module_name for r in registry.get_rejected_modules()}
    assert loaded != rejected
    return loaded


CASES = {
    'a manifest name other than the directory': ({'manifest_name': 'other_mod'}, False),
    'an official claim from outside the repository': (
        {'module_type': 'official'},
        False,
    ),
    'a platform floor above the running version': ({'floor': '99.0.0'}, False),
    'a requirement on an always-on feature': ({'requires': ('items',)}, True),
    'nothing unusual': ({}, True),
}


@pytest.mark.unit
@pytest.mark.parametrize(('shape', 'loads'), CASES.values(), ids=CASES)
def test_every_gate_gives_the_verdict_discovery_gives(
    tmp_path, installation, monkeypatch, shape, loads
):
    package = _package(tmp_path, **shape)

    verdicts = {
        'discovery': _discover(package, tmp_path, monkeypatch),
        'validate': _validate(package),
        'install': _install(package, installation),
        'upgrade': _upgrade(package, installation),
    }

    assert verdicts == dict.fromkeys(verdicts, loads)


@pytest.mark.unit
def test_validate_names_why_a_package_is_refused(tmp_path, installation):
    package = _package(tmp_path, manifest_name='other_mod')

    result = CliRunner().invoke(
        app,
        ['module', 'validate', '--base-path', str(package.parent), '--module', NAME],
    )

    assert result.exit_code == 1
    assert "Manifest name 'other_mod' does not match directory 'accord_mod'" in (
        result.output
    )


@pytest.mark.unit
def test_validate_reads_a_package_the_scan_refuses(tmp_path, installation):
    """The package is read, not skipped: its backend goes through the scan."""
    package = _package(tmp_path)
    (package / 'backend' / 'helpers.py').write_text(
        'import subprocess\n', encoding='utf-8'
    )

    result = CliRunner().invoke(
        app, ['module', 'validate', '--base-path', str(package.parent)]
    )

    assert result.exit_code == 1, result.output
    assert 'subprocess' in result.output


@pytest.mark.unit
def test_allow_core_does_not_spare_a_module_from_outside(tmp_path, installation):
    package = _package(tmp_path)
    (package / 'backend' / 'helpers.py').write_text(
        'import subprocess\n', encoding='utf-8'
    )

    result = CliRunner().invoke(
        app,
        [
            'module',
            'validate',
            '--base-path',
            str(package.parent),
            '--module',
            NAME,
            '--allow-core',
        ],
    )

    assert result.exit_code == 1, result.output
    assert 'subprocess' in result.output
    assert '--allow-core covers only the modules this repository ships' in (
        result.output
    )


@pytest.mark.unit
@pytest.mark.parametrize(('switch', 'passes'), [([], False), (['--allow-core'], True)])
def test_allow_core_still_spares_a_module_the_repository_ships(
    monkeypatch, switch, passes
):
    """The control: the switch keeps its one job. The scan is made to refuse
    everything, so a pass means it was not consulted."""
    from app.cli import module_validator
    from app.core._registry_class import REPO_MODULES_ROOT

    monkeypatch.setattr(
        module_validator, 'validate_safety', lambda *_args: ['printing: scanned']
    )

    result = CliRunner().invoke(
        app,
        [
            'module',
            'validate',
            '--base-path',
            str(REPO_MODULES_ROOT),
            '--module',
            'printing',
            *switch,
        ],
    )

    assert (result.exit_code == 0) == passes, result.output
    assert '--allow-core covers only' not in result.output
