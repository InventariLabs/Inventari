"""A community module install must land both halves, or say which one it did not.

The backend container mounts backend/ at /app and nothing else, so the frontend
module tree was unreachable from the one process that installs modules. Both
halves were declared, one was copied, and the command still reported success —
the module then appeared in the store, switched on, and led nowhere.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

MODULE_YAML = (
    'name: {name}\n'
    'version: 0.1.0\n'
    'inventari_min_version: "0.1.0"\n'
    'author: test\n'
    'description: test\n'
    'license: MIT\n'
    'homepage: ""\n'
    'requires: []\n'
    'components:\n'
    '  backend: true\n'
    '  frontend: true\n'
)


def _make_source(tmp_path: Path, name: str) -> Path:
    """A minimal package declaring both halves, safe under AST validation."""
    source_dir = tmp_path / 'source'
    backend_src = source_dir / 'backend'
    backend_src.mkdir(parents=True)
    (backend_src / '__init__.py').write_text('')
    (backend_src / 'module.py').write_text(f'NAME = "{name}"\n')
    # AST safety validation reads the manifest to know which capabilities the
    # module declared, so a package without one never gets as far as copying.
    (backend_src / 'manifest.json').write_text(
        json.dumps(
            {
                'name': name,
                'version': '0.1.0',
                'inventari_min_version': '0.1.0',
                'display_name': 'Reach Probe',
                'description': 'test',
                'icon': 'box',
                'module_type': 'community',
                'capabilities': [],
                'requires': [],
            }
        )
    )

    frontend_src = source_dir / 'frontend'
    frontend_src.mkdir(parents=True)
    (frontend_src / 'module.ts').write_text(f'export const name = "{name}";\n')

    (source_dir / 'module.yaml').write_text(MODULE_YAML.format(name=name))
    return source_dir


@pytest.mark.unit
class TestFrontendModulesDirOverride:
    """The frontend half is the one a container can be missing, so it is the
    one that gets its own override — the mount point is not derivable from /app."""

    def test_env_var_points_the_install_at_the_mounted_tree(
        self, monkeypatch, tmp_path
    ):
        from app.cli import _module_meta

        mount = tmp_path / 'frontend-modules'
        mount.mkdir()
        monkeypatch.setenv('INVENTARI_FRONTEND_MODULES_DIR', str(mount))

        _root, _backend, frontend = _module_meta._resolve_project_dirs()

        assert frontend == mount.resolve()

    def test_without_the_env_var_detection_is_unchanged(self, monkeypatch):
        from app.cli import _module_meta

        monkeypatch.delenv('INVENTARI_FRONTEND_MODULES_DIR', raising=False)
        monkeypatch.delenv('INVENTARI_PROJECT_ROOT', raising=False)

        _root, backend, frontend = _module_meta._resolve_project_dirs()

        # Whichever layout the suite runs in, the two halves stay siblings.
        assert backend.parts[-2:] == ('app', 'modules')
        assert frontend.parts[-2:] == ('src', 'modules')


@pytest.mark.unit
class TestInstallReachesTheFrontendTree:
    def _install(self, monkeypatch, tmp_path, *, frontend_dir: Path):
        """Run an install, returning where it landed and how it exited."""
        from app.cli import module_packaging

        dest_backend = tmp_path / 'backend_modules'
        dest_backend.mkdir()
        tracking_file = tmp_path / 'community_modules.json'

        monkeypatch.setattr(module_packaging, 'BACKEND_MODULES_DIR', dest_backend)
        monkeypatch.setattr(module_packaging, 'FRONTEND_MODULES_DIR', frontend_dir)
        monkeypatch.setattr('app.cli._module_meta.BACKEND_MODULES_DIR', dest_backend)
        monkeypatch.setattr('app.cli._module_meta.FRONTEND_MODULES_DIR', frontend_dir)
        monkeypatch.setattr('app.cli._module_meta.TRACKING_FILE', tracking_file)

        source_dir = _make_source(tmp_path, 'reach_probe')
        exit_code = 0
        try:
            module_packaging._do_install(
                source_dir,
                original_source=str(source_dir),
                allow_unsigned=True,  # the subject here is frontend reach, not signing
            )
        except SystemExit as exc:
            exit_code = exc.code

        tracking = json.loads(tracking_file.read_text())['modules']['reach_probe']
        return dest_backend, tracking, exit_code

    def test_a_mounted_tree_gets_the_module_screens(
        self, monkeypatch, tmp_path, capsys
    ):
        frontend_dir = tmp_path / 'frontend_modules'
        frontend_dir.mkdir()

        dest_backend, tracking, exit_code = self._install(
            monkeypatch, tmp_path, frontend_dir=frontend_dir
        )

        assert (dest_backend / 'reach_probe' / 'module.py').exists()
        assert (frontend_dir / 'reach_probe' / 'module.ts').exists()
        assert tracking['has_frontend'] is True
        assert exit_code == 0
        assert 'installed successfully' in capsys.readouterr().out

    def test_an_unreachable_tree_is_named_along_with_the_way_out(
        self, monkeypatch, tmp_path, capsys
    ):
        # Not mounted: the directory simply is not there.
        frontend_dir = tmp_path / 'not-mounted' / 'modules'

        dest_backend, tracking, _exit_code = self._install(
            monkeypatch, tmp_path, frontend_dir=frontend_dir
        )

        assert (dest_backend / 'reach_probe' / 'module.py').exists()
        assert not frontend_dir.exists()
        assert tracking['has_frontend'] is False

        out = capsys.readouterr().out
        # The old message sent the reader to INVENTARI_PROJECT_ROOT, a variable
        # that appeared in no document and no compose file in the repository.
        assert 'INVENTARI_FRONTEND_MODULES_DIR' in out
        assert 'without its' in out


@pytest.mark.unit
class TestHalfAnInstallDoesNotReportSuccess:
    """Exit 0 and '✓ installed successfully!' were printed over a module
    whose screens never arrived — the same shape as a bootstrap announcing a
    dead app. The backend half is real and tracked, so this is not a rollback;
    it is a job left unfinished, and it has to read as one."""

    def test_a_module_with_no_screens_is_not_called_a_success(
        self, monkeypatch, tmp_path, capsys
    ):
        probe = TestInstallReachesTheFrontendTree()
        _dest, _tracking, exit_code = probe._install(
            monkeypatch, tmp_path, frontend_dir=tmp_path / 'absent' / 'modules'
        )

        out = capsys.readouterr().out
        assert 'installed successfully' not in out
        assert exit_code == 1

    def test_the_work_that_is_left_sits_under_next_steps(
        self, monkeypatch, tmp_path, capsys
    ):
        probe = TestInstallReachesTheFrontendTree()
        probe._install(
            monkeypatch, tmp_path, frontend_dir=tmp_path / 'absent' / 'modules'
        )

        out = capsys.readouterr().out
        steps = out.split('Next steps:', 1)
        assert len(steps) == 2, 'the run printed no next steps at all'
        # Reinstalling is the only way through: the guard refuses a module that
        # is already tracked, so 'run it again' would be advice that fails.
        assert 'module uninstall reach_probe' in steps[1]
        assert 'module install' in steps[1]

    def test_a_module_that_declares_no_frontend_still_succeeds(
        self, monkeypatch, tmp_path, capsys
    ):
        """Headless by design is not the same as headless by accident."""
        from app.cli import module_packaging

        dest_backend = tmp_path / 'backend_modules'
        dest_backend.mkdir()
        tracking_file = tmp_path / 'community_modules.json'
        frontend_dir = tmp_path / 'absent' / 'modules'

        monkeypatch.setattr(module_packaging, 'BACKEND_MODULES_DIR', dest_backend)
        monkeypatch.setattr(module_packaging, 'FRONTEND_MODULES_DIR', frontend_dir)
        monkeypatch.setattr('app.cli._module_meta.BACKEND_MODULES_DIR', dest_backend)
        monkeypatch.setattr('app.cli._module_meta.FRONTEND_MODULES_DIR', frontend_dir)
        monkeypatch.setattr('app.cli._module_meta.TRACKING_FILE', tracking_file)

        source_dir = _make_source(tmp_path, 'headless_probe')
        (source_dir / 'module.yaml').write_text(
            MODULE_YAML.format(name='headless_probe').replace(
                '  frontend: true', '  frontend: false'
            )
        )
        shutil.rmtree(source_dir / 'frontend')

        module_packaging._do_install(
            source_dir,
            original_source=str(source_dir),
            allow_unsigned=True,  # the subject here is frontend reach, not signing
        )

        assert 'installed successfully' in capsys.readouterr().out
