"""Unit tests for the module install version gate.

The gate implements ``check_min_version`` + the guard in
``_do_install``; these tests pin the install-path behaviour: a module
declaring ``inventari_min_version`` newer than the platform must be
rejected with a clear error and exit code 1.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.mark.unit
class TestInstallVersionGate:
    """_do_install must reject modules requiring a newer platform version."""

    def _write_module_yaml(self, source_dir, *, min_version: str) -> None:
        backend_src = source_dir / 'backend'
        backend_src.mkdir(parents=True)
        (backend_src / '__init__.py').write_text('')
        (source_dir / 'module.yaml').write_text(
            f'name: test_version_gate\n'
            f'version: 0.1.0\n'
            f'inventari_min_version: "{min_version}"\n'
            f'author: test\n'
            f'description: test\n'
            f'license: MIT\n'
            f'homepage: ""\n'
            f'requires: []\n'
            f'components:\n'
            f'  backend: true\n'
            f'  frontend: false\n'
        )

    def test_install_rejected_when_min_version_newer_than_platform(
        self, tmp_path, capsys
    ):
        """min_version > platform must abort install with SystemExit(1)."""
        from app.cli import module_packaging

        source_dir = tmp_path / 'source'
        self._write_module_yaml(source_dir, min_version='999.0.0')

        with (
            patch.object(module_packaging, 'BACKEND_MODULES_DIR', tmp_path / 'backend'),
            patch.object(
                module_packaging, 'FRONTEND_MODULES_DIR', tmp_path / 'frontend'
            ),
            patch('app.cli._module_meta.BACKEND_MODULES_DIR', tmp_path / 'backend'),
            patch('app.cli._module_meta.FRONTEND_MODULES_DIR', tmp_path / 'frontend'),
            patch('app.cli._module_meta.TRACKING_FILE', tmp_path / 'tracking.json'),
        ):
            with pytest.raises(SystemExit) as exc_info:
                module_packaging._do_install(
                    source_dir,
                    original_source=str(source_dir),
                    allow_unsigned=True,  # version gate, not signing
                )

            assert exc_info.value.code == 1
            # nothing was copied
            assert not (tmp_path / 'backend' / 'test_version_gate').exists()
            # the rejection carries a clear, version-specific message
            captured = capsys.readouterr().out + capsys.readouterr().err
            assert '999.0.0' in captured

    def test_install_allowed_when_min_version_satisfied(self, tmp_path, capsys):
        """min_version <= platform must pass the version gate.

        The REAL gate runs here (no mock): '0.1.0' is satisfied by the
        current platform, so the install proceeds past the version check
        and aborts only at the next step (missing frontend dir) — the
        output must NOT carry the version-gate rejection message.
        """
        from app.cli import module_packaging

        source_dir = tmp_path / 'source'
        self._write_module_yaml(source_dir, min_version='0.1.0')

        with (
            patch.object(module_packaging, 'BACKEND_MODULES_DIR', tmp_path / 'backend'),
            patch.object(
                module_packaging, 'FRONTEND_MODULES_DIR', tmp_path / 'frontend'
            ),
            patch('app.cli._module_meta.BACKEND_MODULES_DIR', tmp_path / 'backend'),
            patch('app.cli._module_meta.FRONTEND_MODULES_DIR', tmp_path / 'frontend'),
            patch('app.cli._module_meta.TRACKING_FILE', tmp_path / 'tracking.json'),
        ):
            with pytest.raises(SystemExit) as exc_info:
                module_packaging._do_install(
                    source_dir,
                    original_source=str(source_dir),
                    allow_unsigned=True,  # version gate, not signing
                )
            assert exc_info.value.code == 1
            # the abort comes from a later step, not from the version gate
            captured = capsys.readouterr().out + capsys.readouterr().err
            assert 'requires Inventari' not in captured
