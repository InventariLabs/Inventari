from pathlib import Path

from app.cli.module_validator import validate_safety
from app.core.module_validator import _find_safety_violations


def test_validate_module_detects_forbidden_import_in_test_named_root_file(tmp_path):
    module_dir = tmp_path / 'test_module'
    module_dir.mkdir()

    (module_dir / 'test_payload.py').write_text(
        'from app.models.item import Item\n',
        encoding='utf-8',
    )

    errors = validate_safety(module_dir, declared_capabilities=[])

    assert errors
    assert 'FORBIDDEN import' in errors[0]


def test_validate_module_detects_undeclared_capability(tmp_path):
    module_dir = tmp_path / 'network_module'
    module_dir.mkdir()

    (module_dir / 'api.py').write_text(
        'import requests\n',
        encoding='utf-8',
    )

    # Empty capabilities should trigger error for requests
    errors = validate_safety(module_dir, declared_capabilities=[])

    assert errors
    assert 'UNDECLARED capability "network"' in errors[0]


def test_validate_module_allows_declared_capability(tmp_path):
    module_dir = tmp_path / 'safe_network_module'
    module_dir.mkdir()

    (module_dir / 'api.py').write_text(
        'import requests\n',
        encoding='utf-8',
    )

    # Declared capability should pass
    errors = validate_safety(module_dir, declared_capabilities=['network'])

    assert not errors


class TestTheScanOpensWhatExecutes:
    """``models.py`` runs at package import and ``migrations/`` run at install.

    Both were skipped by the scan, so a module could carry a forbidden import
    in one of the two files that execute without any discovery code and pass
    validation with a clean report. The scan must read them; the only files it
    may still skip are the module's own tests, which never ship.
    """

    def _module_dir(self, tmp_path: Path) -> Path:
        module_dir = tmp_path / 'community_thing'
        module_dir.mkdir()
        return module_dir

    def test_a_forbidden_import_in_models_py_rejects_the_module(self, tmp_path):
        module_dir = self._module_dir(tmp_path)
        models = module_dir / 'models.py'
        models.write_text('from app.models.item import Item\n', encoding='utf-8')

        errors = validate_safety(module_dir, declared_capabilities=[])

        assert errors
        assert 'FORBIDDEN import' in errors[0]

        models.write_text(
            'from app.core.module_sdk import ModuleModelBase\n', encoding='utf-8'
        )
        assert validate_safety(module_dir, declared_capabilities=[]) == []

    def test_a_forbidden_import_in_a_migration_rejects_the_module(self, tmp_path):
        module_dir = self._module_dir(tmp_path)
        versions = module_dir / 'migrations' / 'versions'
        versions.mkdir(parents=True)
        (versions / '001_initial.py').write_text('import socket\n', encoding='utf-8')

        errors = validate_safety(module_dir, declared_capabilities=[])

        assert errors
        assert 'FORBIDDEN import' in errors[0]

    def test_an_undeclared_capability_in_models_py_is_reported(self, tmp_path):
        module_dir = self._module_dir(tmp_path)
        (module_dir / 'models.py').write_text(
            'from sqlalchemy.orm import Mapped\n', encoding='utf-8'
        )

        errors = validate_safety(module_dir, declared_capabilities=[])

        assert errors
        assert 'UNDECLARED capability "database"' in errors[0]

    def test_the_registry_sees_the_same_violation_in_models_py(self, tmp_path):
        module_dir = self._module_dir(tmp_path)
        (module_dir / 'models.py').write_text(
            'from app.models.item import Item\n', encoding='utf-8'
        )

        assert _find_safety_violations(module_dir, [])


class TestATypeCheckingGuardIsNotAnExemption:
    """A ``TYPE_CHECKING`` guard does not take a block out of the scan.

    Python binds names in more ways than any heuristic can enumerate — a
    guard honoured on recognition was a pocket in every file the scan reads:
    the block under it runs while the report claims the file is clean. The
    scan therefore reads every statement, however the block is guarded, and a
    genuinely type-only import is a narrow CORE_EXEMPTIONS entry with a
    justification instead.
    """

    def _assert_is_a_violation(self, tmp_path: Path, source: str) -> None:
        module_dir = tmp_path / 'community_thing'
        module_dir.mkdir()
        (module_dir / 'models.py').write_text(source, encoding='utf-8')

        errors = validate_safety(module_dir, declared_capabilities=[])

        assert errors
        assert 'FORBIDDEN import' in errors[0]

    def test_a_real_typing_guard_is_still_scanned(self, tmp_path):
        self._assert_is_a_violation(
            tmp_path,
            'from typing import TYPE_CHECKING\n'
            'if TYPE_CHECKING:\n'
            '    from app.models.item import Item\n',
        )

    def test_the_typing_attribute_form_is_still_scanned(self, tmp_path):
        self._assert_is_a_violation(
            tmp_path,
            'import typing\nif typing.TYPE_CHECKING:\n    import subprocess\n',
        )

    def test_a_self_declared_guard_is_scanned(self, tmp_path):
        self._assert_is_a_violation(
            tmp_path,
            'TYPE_CHECKING = True\nif TYPE_CHECKING:\n    import subprocess\n',
        )

    def test_a_tuple_unpacking_binding_is_scanned(self, tmp_path):
        self._assert_is_a_violation(
            tmp_path,
            'TYPE_CHECKING, _unused = True, None\n'
            'if TYPE_CHECKING:\n'
            '    import subprocess\n',
        )

    def test_a_loop_target_binding_is_scanned(self, tmp_path):
        self._assert_is_a_violation(
            tmp_path,
            'for TYPE_CHECKING in (True,):\n'
            '    pass\n'
            'if TYPE_CHECKING:\n'
            '    import subprocess\n',
        )

    def test_a_globals_binding_is_scanned(self, tmp_path):
        self._assert_is_a_violation(
            tmp_path,
            "globals()['TYPE_CHECKING'] = True\n"
            'if TYPE_CHECKING:\n'
            '    import subprocess\n',
        )

    def test_an_else_branch_is_scanned(self, tmp_path):
        self._assert_is_a_violation(
            tmp_path,
            'from typing import TYPE_CHECKING\n'
            'if TYPE_CHECKING:\n'
            '    pass\n'
            'else:\n'
            '    import socket\n',
        )
