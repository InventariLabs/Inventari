"""Tests for module.yaml identity fields reaching the copied manifest.

The scaffold puts author, description, license and homepage in module.yaml,
but the registry reads the copied backend/manifest.json only. The installer
merges the identity fields into the copied manifest; without that every
community module introduced itself to the store as "Core Team" with an empty
description.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

MODULE_NAME = 'yaml_identity_probe'


def _write_package(source_dir: Path, yaml_identity: str = '') -> None:
    """A minimal valid package: backend only, manifest.json without identity."""
    backend_src = source_dir / 'backend'
    backend_src.mkdir(parents=True)
    (backend_src / '__init__.py').write_text('')
    (backend_src / 'module.py').write_text('module = None\n')
    (backend_src / 'manifest.json').write_text(
        '{\n'
        f'  "name": "{MODULE_NAME}",\n'
        '  "version": "0.1.0",\n'
        '  "display_name": "Yaml Identity Probe",\n'
        '  "module_type": "community",\n'
        '  "capabilities": []\n'
        '}\n'
    )
    (source_dir / 'module.yaml').write_text(
        f'name: {MODULE_NAME}\n'
        'version: 0.1.0\n'
        'inventari_min_version: "0.1.0"\n'
        f'{yaml_identity}'
        'requires: []\n'
        'components:\n'
        '  backend: true\n'
        '  frontend: false\n'
    )


def _install(source_dir: Path, tmp_path: Path) -> Path:
    from app.cli import module_packaging

    dest_backend = tmp_path / 'installed_backend'
    with (
        patch.object(module_packaging, 'BACKEND_MODULES_DIR', dest_backend),
        patch.object(module_packaging, 'FRONTEND_MODULES_DIR', tmp_path / 'fe'),
        patch('app.cli._module_meta.BACKEND_MODULES_DIR', dest_backend),
        patch('app.cli._module_meta.FRONTEND_MODULES_DIR', tmp_path / 'fe'),
        patch(
            'app.cli._module_meta.TRACKING_FILE', tmp_path / 'community_modules.json'
        ),
        # The manifest merge is the subject here; the AST walk is covered by
        # the rollback tests.
        patch('app.cli.module_packaging._run_ast_validation', return_value=[]),
    ):
        module_packaging._do_install(
            source_dir,
            original_source=str(source_dir),
            allow_unsigned=True,  # the subject here is the yaml merge, not signing
        )
    return dest_backend / MODULE_NAME


@pytest.mark.unit
class TestModuleYamlIdentityMerge:
    def test_install_writes_module_yaml_identity_into_manifest(self, tmp_path):
        source_dir = tmp_path / 'source'
        _write_package(
            source_dir,
            'author: "Jane Doe"\n'
            'description: "Tracks calibration tools."\n'
            'license: "MIT"\n'
            'homepage: "https://example.com/calibration"\n',
        )

        installed = _install(source_dir, tmp_path)

        manifest = json.loads((installed / 'manifest.json').read_text())
        assert manifest['author'] == 'Jane Doe'
        assert manifest['description'] == 'Tracks calibration tools.'
        assert manifest['license'] == 'MIT'
        assert manifest['homepage'] == 'https://example.com/calibration'

    def test_install_without_author_stays_unsigned(self, tmp_path):
        """No author in module.yaml must not sign the module as the core team."""
        source_dir = tmp_path / 'source'
        _write_package(source_dir)

        installed = _install(source_dir, tmp_path)

        manifest = json.loads((installed / 'manifest.json').read_text())
        assert 'author' not in manifest

    def test_install_keeps_manifest_author_when_yaml_author_absent(self, tmp_path):
        """module.yaml that says nothing about identity must not erase the
        manifest's own values — it wins only where it speaks."""
        source_dir = tmp_path / 'source'
        _write_package(source_dir)
        manifest_path = source_dir / 'backend' / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['author'] = 'Already Signed'
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')

        installed = _install(source_dir, tmp_path)

        merged = json.loads((installed / 'manifest.json').read_text())
        assert merged['author'] == 'Already Signed'
