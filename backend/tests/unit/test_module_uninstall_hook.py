"""Unit tests for the on_uninstall hook wiring in CLI uninstall.

The hook belongs to ``--drop-data`` now. Its default implementation
downgrades the module's migrations to base, so running it is the same act
as dropping every table the module owns for every organization — not
something a plain uninstall does. What these tests pin is unchanged for
the path that does ask for it: the hook runs before any file is removed,
and a hook that fails aborts the uninstall with the files still in place.
"""

import pytest

import app.cli.module_packaging as packaging


@pytest.fixture
def module_dirs(tmp_path, monkeypatch):
    backend_dir = tmp_path / 'backend_modules'
    frontend_dir = tmp_path / 'frontend_modules'
    backend_dir.mkdir()
    frontend_dir.mkdir()
    monkeypatch.setattr(packaging, 'BACKEND_MODULES_DIR', backend_dir)
    monkeypatch.setattr(packaging, 'FRONTEND_MODULES_DIR', frontend_dir)
    monkeypatch.setattr(packaging, '_get_reserved_module_names', lambda: frozenset())
    # The orphan report and the installation record both need a database;
    # neither is what this file is about.
    monkeypatch.setattr(packaging, '_print_orphan_report', lambda *a, **k: None)
    monkeypatch.setattr(packaging, '_forget_installation_record', lambda *a, **k: None)
    return backend_dir, frontend_dir


def _tracking(name: str) -> dict:
    return {name: {'version': '1.0.0', 'has_backend': True, 'has_frontend': False}}


@pytest.mark.unit
class TestDropDataRunsHook:
    def test_hook_runs_before_files_deleted(self, module_dirs, monkeypatch):
        backend_dir, _ = module_dirs
        module_dir = backend_dir / 'community_mod'
        module_dir.mkdir()
        (module_dir / 'module.py').write_text('# module')

        saved: list[dict] = []
        calls: list[str] = []
        monkeypatch.setattr(
            packaging, '_load_tracking', lambda: _tracking('community_mod')
        )
        monkeypatch.setattr(packaging, '_save_tracking', saved.append)
        monkeypatch.setattr(
            packaging, '_run_on_uninstall_hook', lambda name: calls.append(name)
        )

        packaging.uninstall_module('community_mod', force=True, drop_data=True)

        assert calls == ['community_mod']
        assert not module_dir.exists()
        assert saved == [{}]

    def test_hook_failure_aborts_and_keeps_files(self, module_dirs, monkeypatch):
        backend_dir, _ = module_dirs
        module_dir = backend_dir / 'community_mod'
        module_dir.mkdir()

        saved: list[dict] = []
        monkeypatch.setattr(
            packaging, '_load_tracking', lambda: _tracking('community_mod')
        )
        monkeypatch.setattr(packaging, '_save_tracking', saved.append)

        def failing_hook(name: str) -> None:
            raise SystemExit(1)

        monkeypatch.setattr(packaging, '_run_on_uninstall_hook', failing_hook)

        with pytest.raises(SystemExit):
            packaging.uninstall_module('community_mod', force=True, drop_data=True)

        assert module_dir.exists(), 'files must stay when the hook fails'
        assert saved == [], 'tracking must not be updated on abort'


@pytest.mark.unit
class TestRunOnUninstallHook:
    def test_invokes_module_hook(self, monkeypatch):
        calls: list[str] = []

        class FakeModule:
            def on_uninstall(self, context: object) -> None:
                calls.append('ran')

        monkeypatch.setattr(
            'app.core.module_registry.module_registry.get',
            lambda name: FakeModule(),
        )

        packaging._run_on_uninstall_hook('community_mod')
        assert calls == ['ran']

    def test_missing_module_warns_and_continues(self, monkeypatch):
        monkeypatch.setattr(
            'app.core.module_registry.module_registry.get', lambda name: None
        )
        # Must not raise
        packaging._run_on_uninstall_hook('ghost_mod')

    def test_hook_exception_becomes_system_exit(self, monkeypatch):
        class FakeModule:
            def on_uninstall(self, context: object) -> None:
                raise RuntimeError('downgrade failed')

        monkeypatch.setattr(
            'app.core.module_registry.module_registry.get',
            lambda name: FakeModule(),
        )

        with pytest.raises(SystemExit):
            packaging._run_on_uninstall_hook('community_mod')
