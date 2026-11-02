"""Tests for community module install rollback.

Verifies that when safety validation fails (or any exception occurs after
files are copied), the copied directory is cleaned up — not left on disk.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.mark.unit
class TestInstallRollback:
    """Rollback must clean up copied files on ANY exception."""

    def test_safety_validation_failure_triggers_rollback(self, tmp_path):
        """A module with AST safety violations must be cleaned up, not left on disk.

        Previously the rollback handler only caught (OSError, PermissionError,
        json.JSONDecodeError), so RuntimeError('Safety validation failed')
        propagated without cleanup — files stayed on disk.
        """
        from app.cli import module_packaging

        # --- Set up a fake source directory ---
        source_dir = tmp_path / 'source'
        backend_src = source_dir / 'backend'
        backend_src.mkdir(parents=True)
        (backend_src / '__init__.py').write_text('')
        (backend_src / 'module.py').write_text(
            '# Malicious module that should fail AST validation\n'
            'import os\n'
            'os.system("rm -rf /")  # safety violation\n'
        )
        (source_dir / 'module.yaml').write_text(
            'name: test_rollback\n'
            'version: 0.1.0\n'
            'inventari_min_version: "0.1.0"\n'
            'author: test\n'
            'description: test\n'
            'license: MIT\n'
            'homepage: ""\n'
            'requires: []\n'
            'components:\n'
            '  backend: true\n'
            '  frontend: false\n'
        )

        # --- Point module dirs to tmp_path ---
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
            # _do_install raises SystemExit(1) on validation failure
            with pytest.raises(SystemExit) as exc_info:
                module_packaging._do_install(
                    source_dir, original_source=str(source_dir)
                )

            assert exc_info.value.code == 1

            # CRITICAL: the copied directory must NOT exist (rollback worked)
            assert not (dest_backend / 'test_rollback').exists(), (
                'Rollback failed: backend directory left on disk after '
                'safety validation failure'
            )

    def test_generic_exception_triggers_rollback(self, tmp_path):
        """Any Exception (not just OSError) during copy must trigger rollback."""
        from app.cli import module_packaging

        source_dir = tmp_path / 'source'
        backend_src = source_dir / 'backend'
        backend_src.mkdir(parents=True)
        (backend_src / '__init__.py').write_text('')
        (source_dir / 'module.yaml').write_text(
            'name: test_generic_rollback\n'
            'version: 0.1.0\n'
            'inventari_min_version: "0.1.0"\n'
            'author: test\n'
            'description: test\n'
            'license: MIT\n'
            'homepage: ""\n'
            'requires: []\n'
            'components:\n'
            '  backend: true\n'
            '  frontend: false\n'
        )

        dest_backend = tmp_path / 'installed_backend'
        tracking_file = tmp_path / 'community_modules.json'

        call_count = 0

        def _failing_ast_validation(module_dir):
            """Simulate a RuntimeError after files are copied."""
            nonlocal call_count
            call_count += 1
            raise RuntimeError('Simulated safety validation crash')

        with (
            patch.object(module_packaging, 'BACKEND_MODULES_DIR', dest_backend),
            patch.object(module_packaging, 'FRONTEND_MODULES_DIR', tmp_path / 'fe'),
            patch('app.cli._module_meta.BACKEND_MODULES_DIR', dest_backend),
            patch('app.cli._module_meta.FRONTEND_MODULES_DIR', tmp_path / 'fe'),
            patch('app.cli._module_meta.TRACKING_FILE', tracking_file),
            patch(
                'app.cli.module_packaging._run_ast_validation',
                side_effect=_failing_ast_validation,
            ),
        ):
            with pytest.raises(SystemExit):
                module_packaging._do_install(
                    source_dir, original_source=str(source_dir)
                )

            assert not (dest_backend / 'test_generic_rollback').exists(), (
                'Rollback failed: directory left on disk after RuntimeError'
            )
