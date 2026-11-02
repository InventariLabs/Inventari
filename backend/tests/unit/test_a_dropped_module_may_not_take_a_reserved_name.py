"""A dropped module directory may not take a name the core already owns.

The repository answers to some names with code — the feature names in
``TRUSTED_CORE_MODULES``, the virtual modules in
``VIRTUAL_TOGGLEABLE_MODULES``, the module directories it ships, and the
URL prefixes its own routers mount under ``/api/v1``. A directory
somebody drops under ``app/modules/`` bypasses the installer's guards
and the registry walks the filesystem, so discovery is the only gate it
meets. Without one, a drop named ``partners`` or ``labels`` attached
itself to the core's routes and permission space, and the core's routers
register first — so the module's identical paths were silently
unreachable while its new sub-paths answered under the core resource's
URL.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from app.core.module_registry import ModuleRegistry
from app.core.modules import BaseModule, ModuleMetadata


def _drop(tmp_path: Path, name: str, module_type: str = 'community') -> Path:
    """A hand-placed module directory: manifest, package, no module class."""
    module_dir = tmp_path / name
    module_dir.mkdir()
    (module_dir / 'manifest.json').write_text(
        json.dumps(
            {
                'name': name,
                'version': '1.0.0',
                'module_type': module_type,
                'capabilities': ['database'],
            }
        ),
        encoding='utf-8',
    )
    (module_dir / '__init__.py').write_text('', encoding='utf-8')
    return module_dir


def _rejection(registry: ModuleRegistry, name: str) -> str:
    rejected = {r.module_name: r.reason for r in registry.get_rejected_modules()}
    assert name in rejected, f'{name} was not rejected: {rejected}'
    return rejected[name]


class TestANameTheCoreAnswersTo:
    @pytest.mark.unit
    def test_a_core_feature_name_is_refused(self, tmp_path):
        registry = ModuleRegistry()
        _drop(tmp_path, 'items')

        registry.discover_modules(base_path=tmp_path)

        assert registry.get('items') is None
        assert 'reserved' in _rejection(registry, 'items').lower()

    @pytest.mark.unit
    def test_a_virtual_module_name_is_refused(self, tmp_path):
        registry = ModuleRegistry()
        _drop(tmp_path, 'partners')

        registry.discover_modules(base_path=tmp_path)

        assert registry.get('partners') is None
        assert 'reserved' in _rejection(registry, 'partners').lower()

    @pytest.mark.unit
    def test_an_in_tree_module_name_is_refused(self, tmp_path):
        registry = ModuleRegistry()
        _drop(tmp_path, 'equipment')

        registry.discover_modules(base_path=tmp_path)

        assert registry.get('equipment') is None
        assert 'reserved' in _rejection(registry, 'equipment').lower()

    @pytest.mark.unit
    def test_a_core_url_prefix_is_refused(self, tmp_path):
        registry = ModuleRegistry()
        _drop(tmp_path, 'labels')

        registry.discover_modules(base_path=tmp_path, extra_reserved_names={'labels'})

        assert registry.get('labels') is None
        assert 'reserved' in _rejection(registry, 'labels').lower()

    @pytest.mark.unit
    def test_a_free_name_still_loads(self, tmp_path, monkeypatch):
        """The guard refuses reserved names, not every drop."""
        registry = ModuleRegistry()

        class Drop(BaseModule):
            @property
            def metadata(self):
                return ModuleMetadata(
                    name='shelf_notes',
                    version='1.0.0',
                    display_name='Shelf notes',
                    description='',
                    icon='box',
                )

            def register_routes(self):
                from fastapi import APIRouter

                return APIRouter()

        package = types.ModuleType('app.modules.shelf_notes')
        package.Drop = Drop  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, 'app.modules.shelf_notes', package)
        _drop(tmp_path, 'shelf_notes')

        registry.discover_modules(base_path=tmp_path)

        assert registry.get('shelf_notes') is not None
        assert registry.get_rejected_modules() == []


class TestTheReservedListIsDerived:
    @pytest.mark.unit
    def test_the_url_names_come_off_the_router(self):
        """The URL half is read from the mounted router, not maintained by
        hand: a new core route reserves its segment the day it is added."""
        from app.core.module_safety import core_api_url_names

        class _Route:
            def __init__(self, path: str) -> None:
                self.path = path

        class _Router:
            prefix = '/api/v1'
            routes = [
                _Route('/auth/login'),
                _Route('/location-types'),
                _Route('/stock-moves/{move_id}'),
                _Route('/attachments/{attachment_id}'),
                _Route('/{path:path}'),
            ]

        assert core_api_url_names(_Router()) == {
            'auth',
            'location_types',
            'stock_moves',
            'attachments',
        }

    @pytest.mark.unit
    def test_a_lazy_include_carries_its_mount_prefix(self):
        """FastAPI keeps an included router as a wrapper whose prefix names
        the mount; the walker must read it (this is the shape the installed
        version builds) and still descend into the child."""
        from app.core.module_safety import core_api_url_names

        class _Route:
            def __init__(self, path: str) -> None:
                self.path = path

        class _Child:
            routes = [_Route('/login'), _Route('/logout')]

        class _IncludeContext:
            prefix = '/api/v1/auth'
            included_router = _Child()

        class _Wrapper:
            include_context = _IncludeContext()

        class _Router:
            prefix = '/api/v1'
            routes = [_Wrapper()]

        assert core_api_url_names(_Router()) == {'auth'}

    @pytest.mark.unit
    def test_every_core_source_is_in_the_reserved_list(self):
        from app.core.module_safety import (
            REPO_SHIPPED_MODULES,
            TRUSTED_CORE_MODULES,
            VIRTUAL_TOGGLEABLE_MODULES,
            reserved_module_names,
        )

        reserved = reserved_module_names(extra_reserved_names={'labels'})

        assert TRUSTED_CORE_MODULES <= reserved
        assert VIRTUAL_TOGGLEABLE_MODULES <= reserved
        assert REPO_SHIPPED_MODULES <= reserved
        assert 'labels' in reserved

    @pytest.mark.unit
    def test_the_running_app_reserves_its_own_url_segments(self):
        """The URL half is taken off the router the app actually mounts:
        this fails the day a core route is added without the segment
        becoming reserved."""
        from app.core.module_safety import (
            core_api_url_names,
            reserved_module_names,
        )
        from app.main import api_v1_router

        url_names = core_api_url_names(api_v1_router)

        assert {'auth', 'labels', 'partners', 'profiles', 'onboarding'} <= url_names
        assert {'items', 'partners', 'equipment', 'labels'} <= reserved_module_names(
            extra_reserved_names=url_names
        )

    @pytest.mark.unit
    def test_the_installer_refuses_the_derived_names(self):
        """``module install`` refuses the same names discovery does — the
        constants half of the set; a URL-only name is refused at discovery,
        which the CLI cannot see without importing the app."""
        from app.cli._module_meta import _get_reserved_module_names

        reserved = _get_reserved_module_names()

        assert {'items', 'partners', 'equipment'} <= reserved


class TestTheAuthorHearsItBeforeInstall:
    """``module validate`` and the scaffold refuse the name ``module install``
    would, in the same words — the author learns it before writing a module
    around the name, not after."""

    @pytest.mark.unit
    def test_validate_refuses_a_reserved_name(self, tmp_path):
        from typer.testing import CliRunner

        from manage import app

        _drop(tmp_path, 'settings')

        result = CliRunner().invoke(
            app, ['module', 'validate', '--base-path', str(tmp_path)]
        )

        assert result.exit_code == 1, result.output
        output = ' '.join(result.output.split())
        assert "'settings' is reserved: the core keeps a directory" in output
        assert 'A community module cannot take that name.' in output

    @pytest.mark.unit
    def test_validate_lets_the_repository_keep_its_own_names(self):
        from typer.testing import CliRunner

        from app.core._registry_class import REPO_MODULES_ROOT
        from manage import app

        result = CliRunner().invoke(
            app,
            [
                'module',
                'validate',
                '--base-path',
                str(REPO_MODULES_ROOT),
                '--module',
                'warehouse',
            ],
        )

        assert 'is reserved' not in result.output

    @pytest.mark.unit
    def test_the_scaffold_refuses_a_reserved_name(self, tmp_path, capsys):
        from app.cli._module_scaffold import scaffold_community_module

        with pytest.raises(SystemExit) as exc_info:
            scaffold_community_module('common', output_dir=str(tmp_path))

        assert exc_info.value.code == 1
        assert not (tmp_path / 'common').exists()
        output = ' '.join(capsys.readouterr().out.split())
        assert "'common' is reserved: the core keeps its own translations" in output
