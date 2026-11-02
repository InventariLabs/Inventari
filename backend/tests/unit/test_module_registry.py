import json
import sys
import types

from fastapi import APIRouter

from app.core.module_registry import ModuleRegistry
from app.core.modules import BaseModule, ModuleMetadata


class MockModule(BaseModule):
    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name='mock_module',
            version='1.0.0',
            display_name='Mock',
            description='Mock module for testing',
            icon='box',
        )

    def register_routes(self) -> APIRouter:
        return APIRouter()


class DepModule(BaseModule):
    """Module with configurable name and requires list for dependency tests."""

    def __init__(
        self,
        name: str,
        requires: list[str] | None = None,
        optional_requires: list[str] | None = None,
    ) -> None:
        self._name = name
        self._requires = requires or []
        self._optional_requires = optional_requires or []

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name=self._name,
            version='1.0.0',
            display_name=self._name,
            description='Dep module',
            icon='box',
            requires=self._requires,
            optional_requires=self._optional_requires,
        )

    def register_routes(self) -> APIRouter:
        return APIRouter()


def test_module_registry_register_and_get():
    registry = ModuleRegistry()
    module = MockModule()

    registry.register(module)

    assert registry.get('mock_module') == module
    assert len(registry.get_all()) == 1


def test_module_registry_duplicate_registration():
    registry = ModuleRegistry()
    module = MockModule()

    registry.register(module)
    registry.register(module)  # Should not raise error, just skip

    assert len(registry.get_all()) == 1


def test_module_registry_discover_empty_dir(tmp_path):
    registry = ModuleRegistry()
    # Point to an empty temp directory
    registry.discover_modules(base_path=tmp_path)

    assert len(registry.get_all()) == 0


def test_module_registry_rejects_module_without_manifest(tmp_path):
    registry = ModuleRegistry()
    module_dir = tmp_path / 'bad_module'
    module_dir.mkdir()
    (module_dir / '__init__.py').write_text('', encoding='utf-8')

    registry.discover_modules(base_path=tmp_path)

    rejected = registry.get_rejected_modules()
    assert len(rejected) == 1
    assert rejected[0].module_name == 'bad_module'
    assert 'manifest.json' in rejected[0].reason


def test_module_registry_rejects_forbidden_model_import(tmp_path):
    registry = ModuleRegistry()
    module_dir = tmp_path / 'bad_module'
    module_dir.mkdir()

    (module_dir / 'manifest.json').write_text(
        json.dumps(
            {
                'name': 'bad_module',
                'version': '1.0.0',
                'module_type': 'community',
                'capabilities': ['database'],
            }
        ),
        encoding='utf-8',
    )
    (module_dir / '__init__.py').write_text('', encoding='utf-8')
    (module_dir / 'module.py').write_text(
        'from app.models.item import Item\n',
        encoding='utf-8',
    )

    registry.discover_modules(base_path=tmp_path)

    rejected = registry.get_rejected_modules()
    assert len(rejected) == 1
    assert rejected[0].module_name == 'bad_module'
    assert 'FORBIDDEN import' in rejected[0].reason


def test_module_registry_rejects_forbidden_import_in_test_named_root_file(tmp_path):
    registry = ModuleRegistry()
    module_dir = tmp_path / 'test_module'
    module_dir.mkdir()

    (module_dir / 'manifest.json').write_text(
        json.dumps(
            {
                'name': 'test_module',
                'version': '1.0.0',
                'module_type': 'community',
                'capabilities': ['database'],
            }
        ),
        encoding='utf-8',
    )
    (module_dir / '__init__.py').write_text('', encoding='utf-8')
    (module_dir / 'test_payload.py').write_text(
        'from app.models.item import Item\n',
        encoding='utf-8',
    )

    registry.discover_modules(base_path=tmp_path)

    rejected = registry.get_rejected_modules()
    assert len(rejected) == 1
    assert rejected[0].module_name == 'test_module'
    assert 'FORBIDDEN import' in rejected[0].reason


def test_module_registry_detects_undeclared_capability(tmp_path):
    registry = ModuleRegistry()
    module_dir = tmp_path / 'network_module'
    module_dir.mkdir()

    (module_dir / 'manifest.json').write_text(
        json.dumps(
            {
                'name': 'network_module',
                'version': '1.0.0',
                'module_type': 'community',
                'capabilities': [],  # No network capability
            }
        ),
        encoding='utf-8',
    )
    (module_dir / '__init__.py').write_text('', encoding='utf-8')
    (module_dir / 'api.py').write_text(
        'import requests\n',
        encoding='utf-8',
    )

    registry.discover_modules(base_path=tmp_path)

    rejected = registry.get_rejected_modules()
    assert len(rejected) == 1
    assert 'UNDECLARED capability "network"' in rejected[0].reason


def test_a_module_built_in_code_reads_as_what_its_manifest_declares(
    tmp_path, monkeypatch
):
    """A BaseModule subclass writes its metadata in code, and code forgot
    what the manifest declares — four in-tree modules read as touching
    nothing, Webhooks among them, whose whole work is outbound HTTP. The
    manifest is the one declaration point: discovery overlays the declared
    capabilities and trust level onto the instance the same way it overlays
    the version. The class below omits both fields on purpose — the
    assertions only hold when the overlay ran. The title is community here:
    a directory the repository does not ship may not claim above community
    at all (see test_a_dropped_module_cannot_crown_itself), and the
    capabilities overlay is the same code path for either title.
    """
    registry = ModuleRegistry()

    class CodeModule(BaseModule):
        def __init__(self) -> None:
            # One stable metadata object, the way every in-tree module holds
            # it — a property returning a fresh instance each access could
            # not carry any registry overlay, including the version sync.
            self._metadata = ModuleMetadata(
                name='code_module',
                version='1.0.0',
                display_name='Code module',
                description='Metadata built in code, capabilities forgotten.',
                icon='box',
            )

        @property
        def metadata(self) -> ModuleMetadata:
            return self._metadata

        def register_routes(self) -> APIRouter:
            return APIRouter()

    package = types.ModuleType('app.modules.code_module')
    package.CodeModule = CodeModule  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, 'app.modules.code_module', package)

    module_dir = tmp_path / 'code_module'
    module_dir.mkdir()
    (module_dir / 'manifest.json').write_text(
        json.dumps(
            {
                'name': 'code_module',
                'version': '1.0.0',
                'module_type': 'community',
                'capabilities': ['database', 'network'],
            }
        ),
        encoding='utf-8',
    )
    (module_dir / '__init__.py').write_text('', encoding='utf-8')

    registry.discover_modules(base_path=tmp_path)

    module = registry.get('code_module')
    assert module is not None
    assert module.metadata.capabilities == ['database', 'network']
    assert module.metadata.module_type == 'community'


# ---------------------------------------------------------------------------
# _validate_dependencies — cascading rejection and rejected-module exclusion
# ---------------------------------------------------------------------------


def test_validate_dependencies_rejects_module_depending_on_rejected():
    """A module whose dependency was rejected must also be rejected.

    Regression: previously ``_rejected_modules`` keys were counted as
    'available', so module B requiring rejected module A would pass.
    """
    registry = ModuleRegistry()
    registry.register(DepModule('mod_a', requires=[]))
    registry.register(DepModule('mod_b', requires=['mod_a']))

    # Simulate mod_a being rejected by safety validator
    registry._reject('mod_a', 'simulated safety violation')
    del registry._modules['mod_a']

    registry._validate_dependencies()

    assert registry.get('mod_b') is None
    rejected_names = {r.module_name for r in registry.get_rejected_modules()}
    assert 'mod_b' in rejected_names


def test_validate_dependencies_cascades_transitively():
    """If A is missing, B (requires A) and C (requires B) must all be rejected.

    Regression: previously the ``registered`` snapshot was computed once,
    so C passed because B was still in the stale set after removal.
    """
    registry = ModuleRegistry()
    registry.register(DepModule('mod_b', requires=['mod_a']))
    registry.register(DepModule('mod_c', requires=['mod_b']))
    # mod_a is NOT registered at all

    registry._validate_dependencies()

    assert registry.get('mod_b') is None
    assert registry.get('mod_c') is None
    rejected_names = {r.module_name for r in registry.get_rejected_modules()}
    assert 'mod_b' in rejected_names
    assert 'mod_c' in rejected_names


def test_validate_dependencies_keeps_modules_with_satisfied_deps():
    """Modules whose dependencies are all present should survive validation."""
    registry = ModuleRegistry()
    registry.register(DepModule('mod_a', requires=[]))
    registry.register(DepModule('mod_b', requires=['mod_a']))

    registry._validate_dependencies()

    assert registry.get('mod_a') is not None
    assert registry.get('mod_b') is not None
    assert len(registry.get_rejected_modules()) == 0


# ---------------------------------------------------------------------------
# optional_requires — soft edges fail loudly on a typo, never on a switched-off
# companion, and never cascade through the fixpoint
# ---------------------------------------------------------------------------


def test_validate_dependencies_rejects_an_unknown_optional_name():
    """A mistyped soft dependency is still a typo — it must fail loudly."""
    registry = ModuleRegistry()
    registry.register(DepModule('mod_b', optional_requires=['mod_typo']))

    registry._validate_dependencies()

    assert registry.get('mod_b') is None
    rejected = {r.module_name: r.reason for r in registry.get_rejected_modules()}
    assert 'mod_typo' in rejected['mod_b']


def test_validate_dependencies_keeps_a_registered_optional_companion():
    """Registered is enough — per-organization enablement is not load state."""
    registry = ModuleRegistry()
    registry.register(DepModule('mod_a'))
    registry.register(DepModule('mod_b', optional_requires=['mod_a']))

    registry._validate_dependencies()

    assert registry.get('mod_a') is not None
    assert registry.get('mod_b') is not None
    assert len(registry.get_rejected_modules()) == 0


def test_validate_dependencies_accepts_an_always_on_optional_name():
    """Always-on names need no registration, same as for hard requires."""
    registry = ModuleRegistry()
    registry.register(DepModule('mod_b', optional_requires=['items']))

    registry._validate_dependencies()

    assert registry.get('mod_b') is not None
    assert len(registry.get_rejected_modules()) == 0


def test_validate_dependencies_optional_rejection_does_not_cascade():
    """The soft check runs once after the fixpoint and does not re-enter it.

    mod_b is rejected over its own typo; mod_c's hard edge to mod_b was
    already validated and the soft pass deliberately does not restart the
    cascade — a module with a manifest typo is fixed, not built upon.
    """
    registry = ModuleRegistry()
    registry.register(DepModule('mod_b', optional_requires=['mod_typo']))
    registry.register(DepModule('mod_c', requires=['mod_b']))

    registry._validate_dependencies()

    assert registry.get('mod_b') is None
    assert registry.get('mod_c') is not None
