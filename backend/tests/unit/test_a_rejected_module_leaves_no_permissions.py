"""A module discovery refuses leaves no permission behind.

Discovery registers a manifest's permission definitions before it runs the
safety scan, and a module refused there — or later, for a dependency that did
not load — kept them: the roles editor, the API key dialog and the built-in
role defaults still offered permissions of a module that never loaded, and a
role ticked with one granted something no endpoint of the installation guards.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest
from fastapi import APIRouter

from app.core.module_registry import ModuleRegistry
from app.core.modules import BaseModule, ModuleMetadata

NAME = 'permdemo'
KEY = f'{NAME}:read'


def _drop(tmp_path: Path, *, init: str = '', requires: list[str] | None = None):
    module_dir = tmp_path / NAME
    module_dir.mkdir()
    (module_dir / 'manifest.json').write_text(
        json.dumps(
            {
                'name': NAME,
                'version': '1.0.0',
                'module_type': 'community',
                'requires': requires or [],
                'permissions': [{'key': KEY, 'default_roles': ['member']}],
            }
        ),
        encoding='utf-8',
    )
    (module_dir / '__init__.py').write_text(init, encoding='utf-8')
    return module_dir


class _Loaded(BaseModule):
    def __init__(self) -> None:
        self._metadata = ModuleMetadata(
            name=NAME,
            version='1.0.0',
            display_name='Permission demo',
            description='',
            icon='box',
            requires=['a_module_that_is_not_here'],
        )

    @property
    def metadata(self) -> ModuleMetadata:
        return self._metadata

    def register_routes(self) -> APIRouter:
        return APIRouter()


def _offered(registry: ModuleRegistry) -> list[str]:
    catalog = registry.get_permissions_catalog()
    modules = catalog['modules']
    assert isinstance(modules, list)
    return [
        *registry.get_all_permissions(),
        *registry.get_default_permissions_for_role('member'),
        *(p['key'] for group in modules for p in group['permissions']),
    ]


@pytest.mark.unit
def test_a_module_the_safety_scan_refused_offers_no_permission(tmp_path):
    registry = ModuleRegistry()
    _drop(tmp_path, init='import subprocess\n')

    registry.discover_modules(base_path=tmp_path)

    assert NAME in {r.module_name for r in registry.get_rejected_modules()}
    assert KEY not in _offered(registry)


@pytest.mark.unit
def test_a_module_refused_for_a_missing_dependency_offers_no_permission(
    tmp_path, monkeypatch
):
    registry = ModuleRegistry()
    _drop(tmp_path, requires=['a_module_that_is_not_here'])
    package = types.ModuleType(f'app.modules.{NAME}')
    package.Loaded = _Loaded  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, f'app.modules.{NAME}', package)

    registry.discover_modules(base_path=tmp_path)

    assert registry.get(NAME) is None
    assert NAME in {r.module_name for r in registry.get_rejected_modules()}
    assert KEY not in _offered(registry)


@pytest.mark.unit
def test_a_module_that_loads_still_offers_its_permission(tmp_path, monkeypatch):
    """The control: the permission is withdrawn because of the refusal."""
    registry = ModuleRegistry()
    _drop(tmp_path)
    package = types.ModuleType(f'app.modules.{NAME}')

    class _Fine(_Loaded):
        def __init__(self) -> None:
            super().__init__()
            self._metadata.requires = []

    package.Fine = _Fine  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, f'app.modules.{NAME}', package)

    registry.discover_modules(base_path=tmp_path)

    assert registry.get(NAME) is not None
    assert KEY in _offered(registry)
