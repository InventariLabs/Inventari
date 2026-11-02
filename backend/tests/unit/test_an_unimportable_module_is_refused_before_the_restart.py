"""A backend package that cannot be imported is refused before the restart.

The safety scan reads import paths, not the names they import, so a typo in
``from app.core.module_sdk import ...`` passed both ``module install`` and
``module validate``: the installer printed "installed successfully", validate
printed "Module validation passed" with exit code 0, and the package was
rejected only at the next start of the backend. Both now ask the interpreter.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from app.cli import module_packaging
from manage import app

runner = CliRunner()

NAME = 'typo_mod'
TYPO = 'something_that_does_not_exist'

MODULE_YAML = (
    f'name: {NAME}\n'
    'version: 0.1.0\n'
    'inventari_min_version: "0.1.0"\n'
    'author: test\n'
    'description: a module with a typo in an import\n'
    'license: MIT\n'
    'homepage: ""\n'
    'requires: []\n'
    'components:\n'
    '  backend: true\n'
    '  frontend: false\n'
)


def _backend(root: Path, init: str) -> Path:
    """A community backend tree whose package runs *init* on import."""
    root.mkdir(parents=True)
    (root / '__init__.py').write_text(init, encoding='utf-8')
    (root / 'manifest.json').write_text(
        json.dumps(
            {
                'name': NAME,
                'version': '0.1.0',
                'inventari_min_version': '0.1.0',
                'category': 'integrations',
                'display_name': 'Typo Module',
                'description': 'a module with a typo in an import',
                'icon': 'package',
                'module_type': 'community',
                'requires': [],
                'capabilities': [],
                'permissions': [],
            }
        ),
        encoding='utf-8',
    )
    (root / 'i18n').mkdir()
    (root / 'i18n' / 'en.json').write_text('{}', encoding='utf-8')
    return root


BROKEN = f'from app.core.module_sdk import {TYPO}\n'


@pytest.mark.unit
class TestModuleValidate:
    def test_an_unimportable_package_fails_validation(self, tmp_path: Path) -> None:
        _backend(tmp_path / NAME, BROKEN)

        result = runner.invoke(
            app, ['module', 'validate', '--base-path', str(tmp_path), '--module', NAME]
        )

        assert result.exit_code == 1, result.output
        assert 'Module validation passed' not in result.output
        assert 'cannot be imported' in result.output
        assert TYPO in result.output

    def test_an_importable_package_still_passes(self, tmp_path: Path) -> None:
        _backend(tmp_path / NAME, 'LABEL = "fine"\n')

        result = runner.invoke(
            app, ['module', 'validate', '--base-path', str(tmp_path), '--module', NAME]
        )

        assert result.exit_code == 0, result.output
        assert 'Module validation passed' in result.output

    def test_a_package_the_safety_scan_refused_is_not_imported(
        self, tmp_path: Path
    ) -> None:
        # Importing it would run the very code the scan just refused.
        marker = tmp_path / 'executed'
        _backend(
            tmp_path / NAME,
            f'import subprocess\nopen({str(marker)!r}, "w").close()\n',
        )

        result = runner.invoke(
            app, ['module', 'validate', '--base-path', str(tmp_path), '--module', NAME]
        )

        assert result.exit_code == 1, result.output
        assert 'subprocess' in result.output
        assert not marker.exists()


@pytest.fixture
def install_env(tmp_path: Path):
    """Point the installer's destinations and tracking at tmp_path."""
    dest_backend = tmp_path / 'installed_backend'
    dest_frontend = tmp_path / 'installed_frontend'
    tracking_file = tmp_path / 'community_modules.json'
    with (
        patch.object(module_packaging, 'BACKEND_MODULES_DIR', dest_backend),
        patch.object(module_packaging, 'FRONTEND_MODULES_DIR', dest_frontend),
        patch('app.cli._module_meta.BACKEND_MODULES_DIR', dest_backend),
        patch('app.cli._module_meta.FRONTEND_MODULES_DIR', dest_frontend),
        patch('app.cli._module_meta.TRACKING_FILE', tracking_file),
    ):
        yield dest_backend, tracking_file


@pytest.mark.unit
class TestModuleInstall:
    def test_an_unimportable_package_is_refused_and_rolled_back(
        self, tmp_path: Path, install_env, capsys
    ) -> None:
        dest_backend, tracking_file = install_env
        source = tmp_path / 'source'
        _backend(source / 'backend', BROKEN)
        (source / 'module.yaml').write_text(MODULE_YAML, encoding='utf-8')

        with pytest.raises(SystemExit) as exit_info:
            module_packaging.install_module(str(source), allow_unsigned=True)

        out = capsys.readouterr().out
        assert exit_info.value.code == 1
        assert TYPO in out
        assert 'installed successfully' not in out
        assert not (dest_backend / NAME).exists()
        assert not tracking_file.exists() or NAME not in tracking_file.read_text()

    def test_a_package_the_safety_scan_refused_is_not_imported(
        self, tmp_path: Path, install_env, capsys
    ) -> None:
        # The import probe runs the package, so it has to come after the scan.
        marker = tmp_path / 'executed'
        source = tmp_path / 'source'
        _backend(
            source / 'backend',
            f'import subprocess\nopen({str(marker)!r}, "w").close()\n',
        )
        (source / 'module.yaml').write_text(MODULE_YAML, encoding='utf-8')

        with pytest.raises(SystemExit) as exit_info:
            module_packaging.install_module(str(source), allow_unsigned=True)

        assert exit_info.value.code == 1
        assert 'subprocess' in capsys.readouterr().out
        assert not marker.exists()
