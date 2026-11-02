"""A module outside this repository imports Core through the SDK, nothing else.

The install-time scan used to be a denylist: ``app.core.deps``,
``app.core.logging``, ``app.i18n.service`` and every other helper a shipped
module happened to use loaded fine, so an author copied them and each became a
contract nobody had promised to keep. The surface is now declared
(``MODULE_IMPORT_SURFACE``): a module installed from outside may reach
``app.core.contracts``, ``app.core.public_api`` and ``app.core.module_sdk``,
plus its own package. The modules this repository ships predate the door and
are held by the architecture lint's frozen list instead.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from app.cli._module_scaffold import scaffold_community_module
from app.core.architecture_lint._quality_checks_modules import _imported_modules
from app.core.module_safety import MODULE_IMPORT_SURFACE, REPO_SHIPPED_MODULES
from app.core.module_safety_analysis import (
    SafetyFinding,
    analyze_module_safety,
    on_module_import_surface,
)


def _community_module(
    tmp_path: Path,
    name: str = 'demo_mod',
    *,
    requires: list[str] | None = None,
    **files: str,
) -> Path:
    """A module directory that looks installed, with the files it ships."""
    module = tmp_path / name
    module.mkdir()
    (module / 'manifest.json').write_text(
        json.dumps(
            {
                'name': name,
                'version': '0.1.0',
                'module_type': 'community',
                'capabilities': ['database'],
                'requires': requires or [],
            }
        ),
        encoding='utf-8',
    )
    for filename, source in files.items():
        path = module / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8')
    return module


def _scan(module: Path, capabilities: list[str] | None = None) -> list[SafetyFinding]:
    return analyze_module_safety(module, capabilities or [], use_cache=False)


def _off_surface(findings: list[SafetyFinding]) -> list[str]:
    return [f.subject for f in findings if f.kind == 'off_surface_import']


@pytest.mark.unit
class TestTheDeclaredSurface:
    def test_the_three_paths_are_the_surface(self):
        assert MODULE_IMPORT_SURFACE == (
            'app.core.contracts',
            'app.core.public_api',
            'app.core.module_sdk',
        )

    @pytest.mark.parametrize(
        'imported',
        [
            'app.core.deps',
            'app.core.logging',
            'app.core.exceptions',
            'app.core.modules',
            'app.core.define_module',
            'app.core.upload_validation',
            'app.config',
            'app.i18n.service',
            'app.schemas.pagination',
        ],
    )
    def test_a_core_helper_a_shipped_module_uses_is_refused(self, tmp_path, imported):
        """Each of these loaded for a community module before the surface existed."""
        module = _community_module(
            tmp_path, **{'router.py': f'from {imported} import something\n'}
        )

        findings = _scan(module)

        assert _off_surface(findings) == [imported], findings

    def test_the_refusal_names_the_way_out(self, tmp_path):
        module = _community_module(
            tmp_path, **{'router.py': 'from app.core.deps import get_async_db\n'}
        )

        finding = _scan(module)[0]

        assert finding.kind == 'off_surface_import'
        assert 'app.core.module_sdk' in (finding.hint or '')
        assert 'app.core.contracts' in (finding.hint or '')

    def test_both_reporters_say_where_the_import_must_come_from(self, tmp_path):
        """The runtime rejection and the CLI line are what an author actually reads."""
        from app.cli.module_validator import _format_error
        from app.core.module_validator import _format_violation

        module = _community_module(
            tmp_path, **{'router.py': 'from app.core.deps import get_async_db\n'}
        )
        finding = _scan(module)[0]

        assert 'module SDK' in _format_violation(finding)
        cli_line = _format_error('demo_mod', finding)
        assert 'outside the module SDK' in cli_line
        assert 'app.core.module_sdk' in cli_line

    def test_the_surface_and_the_modules_own_files_are_allowed(self, tmp_path):
        module = _community_module(
            tmp_path,
            **{
                'module.py': 'from app.core.module_sdk import define_module\n',
                'schemas.py': 'from app.core.contracts import ItemDTO\n',
                'service.py': 'from app.core.public_api import core_api\n',
                'router.py': (
                    'from app.core.module_sdk import require_module\n'
                    'from app.modules.demo_mod.schemas import ItemDTO\n'
                    'from . import schemas\n'
                ),
            },
        )

        assert _scan(module) == []

    def test_another_modules_package_is_refused(self, tmp_path):
        """Cross-module access goes through the target's public API, not its tree."""
        module = _community_module(
            tmp_path,
            **{'service.py': 'from app.modules.warehouse import warehouse_api\n'},
        )

        assert _off_surface(_scan(module)) == ['app.modules.warehouse']

    def test_the_top_package_is_not_a_way_around_the_list(self, tmp_path):
        """``from app import core`` then ``core.deps`` is the same reach in two hops."""
        module = _community_module(
            tmp_path, **{'router.py': 'from app import core\n\nx = core.deps\n'}
        )

        assert _off_surface(_scan(module)) == ['app']

    def test_the_dot_boundary_is_the_path_boundary(self, tmp_path):
        """``app.core.contracts_x`` is another module, not ``contracts``."""
        module = _community_module(
            tmp_path, **{'router.py': 'from app.core.contracts_x import y\n'}
        )

        assert _off_surface(_scan(module)) == ['app.core.contracts_x']

    def test_a_module_the_repository_ships_keeps_its_imports(self, tmp_path):
        """Shipped modules predate the door; the lint's frozen list holds them."""
        assert 'warehouse' in REPO_SHIPPED_MODULES
        module = _community_module(
            tmp_path,
            'warehouse',
            **{'router.py': 'from app.core.logging import get_logger\n'},
        )

        assert _scan(module) == []

    def test_the_sdk_offers_the_core_base_and_the_module_base_apart(self):
        """Two bases, two owners: a shipped module's tables stay in Core's metadata."""
        from app.core import module_sdk
        from app.core.contracts import ModuleModelBase
        from app.database import Base

        assert module_sdk.CoreModelBase is Base
        assert module_sdk.ModuleModelBase is ModuleModelBase
        assert module_sdk.ModuleModelBase is not Base


@pytest.mark.unit
class TestTheDoorIntoAShippedModule:
    """Another module's public API, for a module that declares it depends on it.

    The warehouse seams — the pre-post check, the work-item providers, the
    pick order — are registered through ``warehouse_api``. A module from
    outside that may import only Core can use none of them, so the
    extension guide's patterns were for this repository's modules alone.
    The door is the one the cross-module rule already names (``<m>_api``),
    and only for a module the manifest lists under ``requires``: the
    dependency is a written decision, the way the frozen list is one for a
    shipped module.
    """

    _IMPORT = 'from app.modules.warehouse.warehouse_api import warehouse_api\n'

    def test_a_declared_dependencys_public_api_is_allowed(self, tmp_path):
        module = _community_module(
            tmp_path, requires=['warehouse'], **{'module.py': self._IMPORT}
        )

        assert _scan(module) == []

    def test_the_plain_import_form_is_the_same_door(self, tmp_path):
        module = _community_module(
            tmp_path,
            requires=['warehouse'],
            **{'module.py': 'import app.modules.warehouse.warehouse_api\n'},
        )

        assert _scan(module) == []

    def test_an_undeclared_dependency_is_refused_and_told_why(self, tmp_path):
        module = _community_module(tmp_path, **{'module.py': self._IMPORT})

        findings = _scan(module)

        assert _off_surface(findings) == ['app.modules.warehouse.warehouse_api']
        assert 'requires' in (findings[0].hint or '')

    def test_the_rest_of_a_declared_dependency_stays_closed(self, tmp_path):
        """The public API is the door; the module's own files are not."""
        module = _community_module(
            tmp_path,
            requires=['warehouse'],
            **{
                'service.py': (
                    'from app.modules.warehouse.services import post_document\n'
                    'from app.modules.warehouse.models import Document\n'
                )
            },
        )

        assert _off_surface(_scan(module)) == [
            'app.modules.warehouse.services',
            'app.modules.warehouse.models',
        ]

    def test_a_module_the_repository_does_not_ship_has_no_door(self, tmp_path):
        """Another installed module's code was never reviewed here."""
        module = _community_module(
            tmp_path,
            requires=['other_mod'],
            **{'module.py': 'from app.modules.other_mod.other_mod_api import x\n'},
        )

        assert _off_surface(_scan(module)) == ['app.modules.other_mod.other_mod_api']

    def test_the_verdict_follows_the_manifest(self, tmp_path):
        """The cache key holds the dependencies: a removed ``requires`` refuses."""
        module = _community_module(
            tmp_path, requires=['warehouse'], **{'module.py': self._IMPORT}
        )
        assert analyze_module_safety(module, []) == []

        manifest = json.loads((module / 'manifest.json').read_text(encoding='utf-8'))
        manifest['requires'] = []
        (module / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')

        assert _off_surface(analyze_module_safety(module, [])) == [
            'app.modules.warehouse.warehouse_api'
        ]


@pytest.mark.unit
class TestTheScaffold:
    @pytest.fixture
    def package(self, tmp_path) -> Path:
        scaffold_community_module('demo_mod', output_dir=str(tmp_path))
        return tmp_path / 'demo_mod' / 'backend'

    def _app_imports(self, package: Path) -> list[str]:
        """Every dotted ``app.`` name the scaffold's files reach, absolute.

        Third-party imports (`fastapi`, `sqlalchemy`, …) are the capability
        map's business, not the surface's; only the ``app.`` reach is judged
        here.
        """
        reached: list[str] = []
        for py_file in sorted(package.rglob('*.py')):
            rel = py_file.relative_to(package)
            if 'tests' in rel.parts:
                continue
            tree = ast.parse(py_file.read_text(encoding='utf-8'))
            package_parts = ('app', 'modules', 'demo_mod', *rel.parts[:-1])
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    reached.extend(
                        name
                        for name in _imported_modules(node, package_parts)
                        if name == 'app' or name.startswith('app.')
                    )
        return reached

    def test_the_scaffold_imports_only_through_the_surface(self, package):
        imports = self._app_imports(package)

        assert imports, 'the scaffold imports nothing — this test would prove nothing'
        assert [
            name for name in imports if not on_module_import_surface(name, 'demo_mod')
        ] == []

    def test_the_scaffold_passes_the_scan_as_an_untrusted_module(self, package):
        """The first thing an author installs must load under the allow-list.

        The installer copies ``backend/`` to ``backend_modules/<name>``, so the
        scan sees a directory named after the module; copying it the same way
        keeps the module's own imports resolving to its own package.
        """
        import shutil

        installed = package.parent.parent / 'installed' / 'demo_mod'
        shutil.copytree(package, installed)

        # The manifest declares `database` for SQLAlchemy, so the capability
        # check passes; what this asserts is the import surface.
        assert _scan(installed, ['database']) == []

    def test_the_scaffold_names_the_sdk_as_the_door(self, package):
        module_source = (package / 'module.py').read_text(encoding='utf-8')

        assert 'from app.core.module_sdk import define_module' in module_source


@pytest.mark.unit
def test_the_lint_collects_what_the_scan_refuses():
    """The runtime gate and the repository lint read the same surface."""
    from app.core.architecture_lint._constants import MODULES_ROOT
    from app.core.architecture_lint._quality_checks_modules import (
        collect_module_surface_imports,
    )

    live = collect_module_surface_imports(MODULES_ROOT)

    assert live, 'no module import was collected — the gates agree on nothing'
    for module, paths in live.items():
        for path in paths:
            assert not on_module_import_surface(path, module)
