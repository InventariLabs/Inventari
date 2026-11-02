"""``module smoke`` asks of a module what that module needs, and no more.

It failed 7 of the 15 modules the platform ships - api_keys, stats, vision,
webhooks on "uses moduleNav", maker on "schemas.py exists", nutrition on
"router.py exists", printing on its frontend catalogs - each a shape the
codebase uses on purpose: a module that lives in settings has no navigation,
maker splits its schemas, nutrition serves no HTTP route, and printing's one
page is a deep link from a printed label that reads the core's namespaces.
A module author pointed at ``make module-smoke`` met red on the reference
modules. Each rule is now asked only where it applies, and the tests below
keep each one failing a module that really misses what it needs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.cli import _module_meta
from manage import app

MODULES_ROOT = Path(__file__).resolve().parents[2] / 'app' / 'modules'
SHIPPED = sorted(path.parent.name for path in MODULES_ROOT.glob('*/manifest.json'))

pytestmark = pytest.mark.unit


def _smoke(name: str, base: Path = MODULES_ROOT):
    return CliRunner().invoke(app, ['module', 'smoke', name, '--base-path', str(base)])


@pytest.mark.parametrize('name', SHIPPED)
def test_every_shipped_module_passes_smoke(name):
    result = _smoke(name)

    assert result.exit_code == 0, result.output


# -- a module built in a temporary tree, one rule broken at a time ----------

_MANIFEST = {
    'name': 'probe_mod',
    'module_type': 'community',
    'version': '0.1.0',
    'capabilities': [],
}

_ROUTED_MODULE = (
    'from app.core.module_sdk import define_module\n'
    'from .router import router\n'
    'module = define_module(router=router)\n'
)
_ROUTELESS_MODULE = (
    'from fastapi import APIRouter\n'
    'from app.core.module_sdk import define_module\n'
    'module = define_module(router=APIRouter())\n'
)
_NAVIGATED_TS = (
    'moduleRegistry.register({\n'
    '  name: "probe_mod",\n'
    '  launcher: { displayName: "probe_mod:title", icon: Box },\n'
    '  routes: [{ path: "/probe", component: Page }],\n'
    '  moduleNav: { basePath: "/probe", items: [] },\n'
    '});\n'
)


@pytest.fixture
def probe(tmp_path, monkeypatch):
    backend = tmp_path / 'backend_modules' / 'probe_mod'
    frontend = tmp_path / 'frontend_modules' / 'probe_mod'
    for directory in (backend / 'i18n', frontend / 'i18n', frontend / 'pages'):
        directory.mkdir(parents=True)
    (backend / 'manifest.json').write_text(json.dumps(_MANIFEST))
    (backend / '__init__.py').write_text('')
    (backend / 'module.py').write_text(_ROUTED_MODULE)
    (backend / 'router.py').write_text(
        'from fastapi import APIRouter\nrouter = APIRouter()\n'
    )
    (backend / 'schemas.py').write_text('')
    (backend / 'i18n' / 'en.json').write_text('{}')
    (frontend / 'module.ts').write_text(_NAVIGATED_TS)
    (frontend / 'pages' / 'Page.tsx').write_text(
        'const { t } = useTranslation("probe_mod");\n'
    )
    (frontend / 'i18n' / 'en.json').write_text('{"title": "Probe"}')
    monkeypatch.setattr(_module_meta, 'FRONTEND_MODULES_DIR', frontend.parent)
    return backend, frontend


def _smoke_probe(backend: Path):
    return _smoke('probe_mod', backend.parent)


def test_the_probe_module_passes_as_built(probe):
    backend, _ = probe

    result = _smoke_probe(backend)

    assert result.exit_code == 0, result.output
    # English is all a community package owes: a line per language it chose
    # not to ship would read as a problem above the passing verdict.
    assert 'missing' not in result.output, result.output


def test_a_module_with_pages_and_a_tile_still_needs_module_nav(probe):
    backend, frontend = probe
    ts = frontend / 'module.ts'
    ts.write_text(
        ts.read_text().replace('  moduleNav: { basePath: "/probe", items: [] },\n', '')
    )

    result = _smoke_probe(backend)

    assert result.exit_code == 1
    assert '✗ uses moduleNav' in result.output


def test_a_settings_only_module_needs_no_module_nav(probe):
    backend, frontend = probe
    (frontend / 'module.ts').write_text(
        'moduleRegistry.register({\n'
        '  name: "probe_mod",\n'
        '  routes: [],\n'
        '  settingsSections: [{ title: "probe_mod:title", path: "probe" }],\n'
        '});\n'
    )

    result = _smoke_probe(backend)

    assert result.exit_code == 0, result.output


def test_a_hidden_tile_with_a_deep_link_needs_no_module_nav(probe):
    backend, frontend = probe
    (frontend / 'module.ts').write_text(
        'moduleRegistry.register({\n'
        '  name: "probe_mod",\n'
        '  launcher: { displayName: "", icon: Box, hidden: true },\n'
        '  routes: [{ path: "/labels/scan/:code", component: Page }],\n'
        '});\n'
    )

    result = _smoke_probe(backend)

    assert result.exit_code == 0, result.output


def test_a_module_reading_its_own_namespace_needs_its_catalogs(probe):
    backend, frontend = probe
    (frontend / 'i18n' / 'en.json').unlink()

    result = _smoke_probe(backend)

    assert result.exit_code == 1
    assert '✗ frontend i18n/en.json' in result.output


def test_a_module_reading_only_core_namespaces_needs_no_catalogs(probe):
    backend, frontend = probe
    (frontend / 'i18n' / 'en.json').unlink()
    (frontend / 'pages' / 'Page.tsx').write_text(
        'const { t } = useTranslation(["labels", "common"]);\n'
    )
    ts = frontend / 'module.ts'
    ts.write_text(ts.read_text().replace('"probe_mod:title"', '""'))

    result = _smoke_probe(backend)

    assert result.exit_code == 0, result.output


def test_split_schemas_count_as_schemas(probe):
    backend, _ = probe
    (backend / 'schemas.py').unlink()
    (backend / '_schemas_orders.py').write_text('')

    result = _smoke_probe(backend)

    assert result.exit_code == 0, result.output


def test_a_module_with_no_schemas_at_all_still_fails(probe):
    backend, _ = probe
    (backend / 'schemas.py').unlink()

    result = _smoke_probe(backend)

    assert result.exit_code == 1
    assert '✗ schemas' in result.output


def test_a_module_that_serves_no_route_needs_no_router(probe):
    backend, _ = probe
    (backend / 'router.py').unlink()
    (backend / 'module.py').write_text(_ROUTELESS_MODULE)

    result = _smoke_probe(backend)

    assert result.exit_code == 0, result.output


def test_a_module_that_serves_routes_without_a_router_still_fails(probe):
    backend, _ = probe
    (backend / 'router.py').unlink()

    result = _smoke_probe(backend)

    assert result.exit_code == 1
    assert '✗ router.py exists' in result.output
